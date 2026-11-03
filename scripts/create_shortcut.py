"""Create a platform-appropriate project-local shortcut for this installation."""
import base64
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
if os.name=='nt':
    def ps_string(value):return "'"+str(value).replace("'","''")+"'"
    script=("$s=(New-Object -ComObject WScript.Shell).CreateShortcut("+ps_string(ROOT/'CorridorKey2-Windows.lnk')+");"
            "$s.TargetPath="+ps_string(ROOT/'windows_run.bat')+";$s.WorkingDirectory="+ps_string(ROOT)+";$s.Save()")
    encoded=base64.b64encode(script.encode('utf-16le')).decode('ascii')
    subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-EncodedCommand',encoded],check=True)
else:
    subprocess.run([sys.executable,str(ROOT/'scripts/create_linux_launcher.py')],check=True)
