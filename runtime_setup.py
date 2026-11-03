"""Transactional, project-local Python environment and FFmpeg provisioning."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import uuid
import zipfile
from runtime_support import ROOT, environment, python_path, configure
from app_cache import cache_directory

SAM_REVISION = 'f1647e8d0c1d280991f4d1b7d974c2704537fe66'
RELEASE = 'autobuild-2026-11-03-12-50'
FFMPEG = {
    'Linux': ('ffmpeg-n8.1.3-32-g760d10603e-linux64-gpl-8.1.tar.xz', '5bbfd617d5473c91c8f1fdd1dd8507e8fdc6aa6db0e531f65c95a15486ecacb7'),
    'Windows': ('ffmpeg-n8.1.3-32-g760d10603e-win64-gpl-8.1.zip', 'f41877437ec23e4619e5507180a020005738fe09376fdfcd3fdc0f4c549afc7c'),
}


def atomic_json(path, value):
    path = Path(path); temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2), encoding='utf-8'); os.replace(temp, path)


@contextmanager
def setup_lock(root, name="setup.lock"):
    """OS-held lock automatically releases after a crash; no stale PID guessing."""
    runtime = Path(root)/'.runtime'; runtime.mkdir(exist_ok=True)
    with (runtime/name).open('a+b') as handle:
        handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc: raise RuntimeError('Another setup or updater is running.') from exc
        try: yield
        finally:
            handle.seek(0)
            if os.name == 'nt': msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(handle, fcntl.LOCK_UN)


def run(args, root=ROOT, **kwargs):
    print('+', ' '.join(map(str,args)), flush=True)
    return subprocess.run(list(map(str,args)), cwd=root, env=environment(root), check=True, **kwargs)


def fingerprint(root, sam):
    digest = hashlib.sha256()
    for name in ('requirements.txt','requirements-linux.txt','constraints-runtime.txt','runtime_setup.py'):
        digest.update((Path(root)/name).read_bytes())
    digest.update(f'3.12|2.9.1|0.24.1|cu128|{sam}|{SAM_REVISION}'.encode())
    return digest.hexdigest()


def verify(python, root=ROOT, sam=False):
    code = '''import sys, importlib, torch, torchvision, numpy
assert sys.version_info[:2] == (3,12), 'Python 3.12 required'
assert torch.__version__.split('+')[0] == '2.9.1'
assert torchvision.__version__.split('+')[0] == '0.24.1'
assert torch.version.cuda == '12.8'
assert int(numpy.__version__.split('.')[0]) < 2
for name in ['PySide6.QtWidgets','cv2','transformers','timm','safetensors','einops','scipy','utils3d']:
    importlib.import_module(name)
'''
    if sam: code += "from sam_hint_backend import prepare_sam_imports\nprepare_sam_imports()\nimport sam3, pycocotools, psutil\n"
    run([python,'-c',code],root, timeout=180)
    run([python,'-m','pip','check'],root,timeout=120)


def recover(root):
    root=Path(root); journal=root/'.runtime/migration.json'
    if not journal.exists(): return
    state=json.loads(journal.read_text())
    backup=state.get('backup')
    if backup and (not backup.startswith('venv-') or len(backup)!=37 or any(c not in '0123456789abcdef' for c in backup[5:])):
        raise RuntimeError('Invalid environment recovery journal.')
    saved=root/'.runtime/backups'/backup if backup else None
    canonical=root/'venv'
    if canonical.is_symlink() or (saved is not None and saved.is_symlink()):
        raise RuntimeError('Refusing linked environment recovery paths.')
    if not state.get('complete'):
        if saved is not None and saved.exists():
            if canonical.exists(): shutil.rmtree(canonical)
            saved.rename(canonical)
        elif saved is None and canonical.exists(): shutil.rmtree(canonical)
        if 'previous_state' in state:
            if state['previous_state'] is None:(root/'.runtime/state.json').unlink(missing_ok=True)
            else:atomic_json(root/'.runtime/state.json',state['previous_state'])
    journal.unlink()


def fetch_verified(url, destination, checksum):
    destination=Path(destination); temporary=destination.with_suffix('.download')
    try:
        with urllib.request.urlopen(url,timeout=60) as src, temporary.open('wb') as dst:
            shutil.copyfileobj(src,dst)
        if hashlib.sha256(temporary.read_bytes()).hexdigest()!=checksum:
            raise RuntimeError('Download checksum mismatch: '+url)
        os.replace(temporary,destination)
    finally: temporary.unlink(missing_ok=True)


def ensure_ffmpeg(root=ROOT):
    root=Path(root); target=root/'.runtime/ffmpeg'
    name,checksum=FFMPEG[platform.system()]
    receipt=target/'build.json'
    if receipt.exists() and json.loads(receipt.read_text()).get('sha256')==checksum:
        try:
            verify_ffmpeg(root); return
        except (OSError,RuntimeError,subprocess.SubprocessError):
            print('Repairing managed FFmpeg files.',flush=True)
    downloads=cache_directory('downloads',root)
    archive=downloads/name
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest()!=checksum:
        fetch_verified(f'https://github.com/BtbN/FFmpeg-Builds/releases/download/{RELEASE}/{name}',archive,checksum)
    with tempfile.TemporaryDirectory(dir=cache_directory('temp',root),prefix='ffmpeg-') as temp:
        stage=Path(temp)
        if name.endswith('.zip'):
            with zipfile.ZipFile(archive) as z:
                if any(Path(n).is_absolute() or '..' in Path(n).parts or '\\' in n for n in z.namelist()): raise RuntimeError('Unsafe archive')
                z.extractall(stage)
        else:
            with tarfile.open(archive) as t: t.extractall(stage,filter='data')
        extracted=next(p for p in stage.iterdir() if p.is_dir())
        atomic_json(extracted/'build.json',{'sha256':checksum,'release':RELEASE})
        old=root/'.runtime/ffmpeg-backup'
        if old.exists(): shutil.rmtree(old)
        if target.exists(): target.rename(old)
        try:
            extracted.rename(target); verify_ffmpeg(root)
        except BaseException:
            if target.exists(): shutil.rmtree(target)
            if old.exists(): old.rename(target)
            raise
        if old.exists(): shutil.rmtree(old)


def verify_ffmpeg(root):
    for program,flag,tokens in [('ffmpeg','-encoders',('libx264','prores_ks')),('ffmpeg','-decoders',('exr',)),('ffprobe','-version',('ffprobe',))]:
        exe=Path(root)/'.runtime/ffmpeg/bin'/(program+('.exe' if os.name=='nt' else ''))
        result=run([exe,'-hide_banner',flag],root,capture_output=True,text=True,timeout=30)
        if any(token not in result.stdout for token in tokens): raise RuntimeError(f'{program} lacks required codecs')


def prepare(root, uv, base_python, sam=None, repair=False):
    root=Path(root)
    with setup_lock(root), setup_lock(root, "application.lock"):
        recover(root)
        state_path=root/'.runtime/state.json'
        state=json.loads(state_path.read_text()) if state_path.exists() else {}
        sam=state.get('sam',False) if sam is None else sam
        signature=fingerprint(root,sam)
        ensure_ffmpeg(root)
        python=python_path(root)
        if not repair and state.get('fingerprint')==signature and python.exists():
            try:verify(python,root,sam)
            except (OSError,RuntimeError,subprocess.SubprocessError):
                print('Environment verification failed; rebuilding with rollback.',flush=True)
            else:
                (root/'.runtime/update-failed.txt').unlink(missing_ok=True)
                print('Environment already current.'); return
        backup=None; canonical=root/'venv'; journal=root/'.runtime/migration.json'
        if canonical.is_symlink() or getattr(canonical,'is_junction',lambda:False)():
            raise RuntimeError('Refusing to replace a linked venv. Use a project-local environment.')
        if canonical.exists():
            backup='venv-'+uuid.uuid4().hex
            (root/'.runtime/backups').mkdir(exist_ok=True)
        atomic_json(journal,{'backup':backup,'complete':False,'previous_state':state if state_path.exists() else None})
        try:
            if backup: canonical.rename(root/'.runtime/backups'/backup)
            run([uv,'venv','--python',base_python,canonical],root)
            run([uv,'pip','install','--python',python,'pip'],root)
            run([uv,'pip','install','--python',python,'torch==2.9.1','torchvision==0.24.1','--index-url','https://download.pytorch.org/whl/cu128'],root)
            run([uv,'pip','install','--python',python,'--constraint','constraints-runtime.txt','-r','requirements-linux.txt'],root)
            if sam:
                sam_path=root/'third_party/sam3'
                if not (sam_path/'.git').exists():
                    run(['git','submodule','update','--init','third_party/sam3'],root)
                rev=run(['git','-C',sam_path,'rev-parse','HEAD'],root,capture_output=True,text=True).stdout.strip()
                if rev!=SAM_REVISION: raise RuntimeError('Unexpected SAM source revision; leaving source untouched.')
                run([uv,'pip','install','--python',python,'--constraint','constraints-runtime.txt','-e',sam_path,'pycocotools','psutil'],root)
            verify(python,root,sam)
            atomic_json(state_path,{'sam':sam,'fingerprint':signature,'base_python':str(base_python)})
            atomic_json(journal,{'backup':backup,'complete':True})
        except BaseException:
            recover(root); raise
        journal.unlink()
        (root/'.runtime/update-failed.txt').unlink(missing_ok=True)
        print('Environment ready. Previous environment retained for recovery:',backup or 'none')


def main():
    configure()
    parser=argparse.ArgumentParser(); parser.add_argument('--uv',required=True);parser.add_argument('--python',required=True)
    choice=parser.add_mutually_exclusive_group();choice.add_argument('--sam',action='store_true',default=None);choice.add_argument('--no-sam',dest='sam',action='store_false')
    parser.add_argument('--repair',action='store_true');parser.add_argument('--skip-weights',action='store_true')
    args=parser.parse_args()
    if args.sam is None and not (ROOT/'.runtime/state.json').exists():
        # Preserve an existing optional installation during the first migration.
        existing=python_path()
        installed=False
        if existing.exists():
            try:
                installed=subprocess.run([str(existing),'-c',"import importlib.util; raise SystemExit(0 if importlib.util.find_spec('sam3') else 1)"],
                                         env=environment(),capture_output=True,timeout=30).returncode==0
            except (OSError,subprocess.TimeoutExpired):pass
        if sys.stdin.isatty():
            answer=input('Install optional SAM 3.1 support? Checkpoint supplied separately. '+('[Y/n] ' if installed else '[y/N] ')).strip().lower()
            args.sam=(answer!='n') if installed else answer=='y'
        else:args.sam=installed
    if not shutil.which('git'):raise RuntimeError('Install Git before running setup.')
    prepare(ROOT,args.uv,args.python,args.sam,args.repair)
    if not args.skip_weights: run([python_path(),'scripts/download_weights.py'])
    run([python_path(),'scripts/create_shortcut.py'])
    print('Software ready. Run the Check launcher to verify GPU, driver, and weights.')


if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('Setup failed:',exc, '\nRun Install / Repair again. Existing model weights were preserved.',file=sys.stderr)
        raise SystemExit(1)
