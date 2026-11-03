"""Read-only update inspection and explicit fast-forward update orchestration."""
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from runtime_support import ROOT, environment, python_path

REPOSITORY='https://github.com/chiefjackvfx/CorridorKey2.0.git'
BRANCH='master'
REF='refs/remotes/origin/master'
LEGACY_LAUNCHER='CorridorKey_DRAG_CLIPS_HERE.bat'


@dataclass
class UpdateStatus:
    current: str='unknown'
    target: str=''
    has_update: bool=False
    can_update: bool=False
    message: str='Not checked yet.'
    notes: str=''


def git(root,*args,timeout=30):
    env=environment(root);env.update(GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='Never',GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=10')
    return subprocess.run(['git',*args],cwd=root,env=env,check=True,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout).stdout.rstrip('\r\n')


def blocking_changes(root, target):
    """Permit an unstaged legacy-launcher edit only if the update leaves it alone.

    Git can preserve unrelated working-tree edits during a fast-forward. Staged
    changes, submodule changes, other files, and incoming edits still block.
    """
    records=git(root,'status','--porcelain=v1','-z','--untracked-files=normal').split('\0')
    blockers=[];index=0
    while index<len(records):
        record=records[index];index+=1
        if not record:continue
        code,path=record[:2],record[3:]
        if 'R' in code or 'C' in code:
            index+=1  # Porcelain -z includes the original path after a rename/copy.
        if code==' M' and path==LEGACY_LAUNCHER:
            incoming=git(root,'diff','--name-only','-z','HEAD',target,'--',LEGACY_LAUNCHER)
            if not incoming:continue
        blockers.append(f'{code} {path}')
    return blockers


def changelog_entries(text):
    entries=[('All changes',text)]
    for match in re.finditer(r'^##\s+([^\n]+)\n(.*?)(?=^##\s+|\Z)',text,re.M|re.S):
        entries.append((match[1].strip(),match[0].strip()))
    return entries


def incoming_notes(local,remote):
    previous=set(local.splitlines())
    new=[line for line in remote.splitlines() if line.startswith('- ') and line not in previous]
    if new: return '\n'.join(new)
    entries=changelog_entries(remote)
    return entries[1][1] if len(entries)>1 else 'No changelog notes were supplied for these commits.'


def check_updates(root=ROOT,fetch=True,repository=REPOSITORY):
    root=Path(root);status=UpdateStatus()
    try:
        if not shutil.which('git'): raise RuntimeError('Git is missing. Install Git to enable updates.')
        status.current=git(root,'rev-parse','HEAD')
        remote=git(root,'remote','get-url','origin')
        allowed={repository,repository.removesuffix('.git')}
        if repository==REPOSITORY: allowed.add('git@github.com:chiefjackvfx/CorridorKey2.0.git')
        if remote not in allowed: raise RuntimeError('origin must point to chiefjackvfx/CorridorKey2.0 for self-updates.')
        if fetch: git(root,'fetch','--no-tags','origin',f'{BRANCH}:{REF}')
        status.target=git(root,'rev-parse',REF)
        def read_notes(ref):
            try:return git(root,'show',f'{ref}:CHANGELOG.md')
            except subprocess.CalledProcessError:return ''
        local=read_notes('HEAD')
        remote_notes=read_notes(status.target)
        status.notes=incoming_notes(local,remote_notes)
        branch=git(root,'branch','--show-current')
        dirty=blocking_changes(root,status.target)
        ahead,behind=map(int,git(root,'rev-list','--left-right','--count',f'HEAD...{status.target}').split())
        status.has_update=bool(behind)
        if branch!=BRANCH: status.message=f'Updates require master; current branch: {branch or "detached HEAD"}.'
        elif dirty: status.message='Local changes prevent updating:\n'+'\n'.join(dirty[:10])+'\nCommit or resolve these changes manually.'
        elif ahead and behind: status.message='Local and published history diverged. Resolve manually.'
        elif ahead: status.message='This checkout has local commits ahead of the published version.'
        elif behind: status.message=f'{behind} new commit(s) available.';status.can_update=True
        else: status.message='Up to date.'
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        status.can_update=False
        detail=getattr(exc,'stderr',None) or str(exc)
        status.message='Update check unavailable: '+detail.strip()[:1000]
    return status


def apply_update(root,target):
    root=Path(root)
    if not re.fullmatch('[0-9a-f]{40}',target): raise RuntimeError('Invalid update commit.')
    status=check_updates(root,fetch=False)
    if not status.can_update or status.target!=target:
        raise RuntimeError('Update state changed: '+status.message)
    print('Fast-forwarding to checked commit:',target,flush=True)
    git(root,'merge','--ff-only',target,timeout=120)
    print('Synchronizing initialized submodules.',flush=True)
    git(root,'submodule','sync','--recursive',timeout=60)
    git(root,'submodule','update','--recursive',timeout=300)


def wait_for_exit(pid,timeout=120):
    deadline=time.monotonic()+timeout
    if os.name=='nt':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x100000,False,pid)
        if handle:
            try:
                if kernel.WaitForSingleObject(handle,int(timeout*1000))!=0: raise RuntimeError('Application did not close; update cancelled.')
            finally: kernel.CloseHandle(handle)
    else:
        while True:
            try: os.kill(pid,0)
            except ProcessLookupError: return
            if time.monotonic()>deadline: raise RuntimeError('Application did not close; update cancelled.')
            time.sleep(.25)


def updater(root,pid,target):
    root=Path(root)
    # Launching from managed Python keeps Windows venv files unlocked.
    from runtime_setup import setup_lock
    wait_for_exit(pid)
    with setup_lock(root), setup_lock(root, 'application.lock'): apply_update(root,target)
    command=(['powershell.exe','-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'setup_runtime.ps1')]
             if os.name=='nt' else ['bash',str(root/'setup_runtime.sh')])
    subprocess.run([*command,'--skip-weights'],cwd=root,env=environment(root),check=True)
    subprocess.Popen([str(python_path(root)),str(root/'scripts/launch.py')],cwd=root,env=environment(root),
                     start_new_session=os.name!='nt')


if __name__=='__main__':
    if sys.argv[1:2] in (['--check'],['--inspect']):
        print(json.dumps(asdict(check_updates(fetch=sys.argv[1]=='--check'))))
    elif sys.argv[1:2]==['--apply']:
        try: updater(ROOT,int(sys.argv[2]),sys.argv[3])
        except Exception as exc:
            print('UPDATE FAILED:',exc,getattr(exc,'stderr','') or '', '\nRun Install / Repair, resolve any Git errors, and launch again.',flush=True)
            atomic=ROOT/'.runtime/update-failed.txt';atomic.write_text(str(exc),encoding='utf-8')
            raise SystemExit(1)
