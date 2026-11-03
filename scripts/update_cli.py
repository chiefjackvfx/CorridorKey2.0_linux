"""Explicit updater launcher for users outside the GUI."""
from pathlib import Path
import json
import os
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app_update import check_updates
from runtime_support import environment


def main():
    status=check_updates();print(status.message)
    if not status.can_update:return 0 if not status.has_update else 1
    print(status.notes)
    if input('Close all CK2 windows, then update and restart? [y/N] ').lower()!='y':return 0
    state=ROOT/'.runtime/state.json'
    python=json.loads(state.read_text()).get('base_python') if state.exists() else None
    if not python:print('Run Install / Repair first.');return 1
    # This launcher exits before the independent managed interpreter changes venv.
    logs=ROOT/'logs/updates';logs.mkdir(parents=True,exist_ok=True)
    with (logs/'manual-update.log').open('wb') as handle:
        subprocess.Popen([python,'-u',str(ROOT/'app_update.py'),'--apply',str(os.getpid()),status.target],cwd=ROOT,env=environment(),
                         stdout=handle,stderr=subprocess.STDOUT,start_new_session=os.name!='nt',
                         creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.DETACHED_PROCESS) if os.name=='nt' else 0)
    print('Update started. Log: logs/updates/manual-update.log');return 0


if __name__=='__main__':raise SystemExit(main())
