"""Launch Qt workers in owned process trees on Windows and Linux."""
import os
from pathlib import Path
import signal
import sys
from PySide6.QtCore import QProcessEnvironment
from runtime_support import environment


def start_worker(process, command):
    env = QProcessEnvironment()
    for key, value in environment().items():
        env.insert(key, value)
    process.setProcessEnvironment(env)
    if os.name == 'nt':
        process.start(sys.executable, ['-u', str(Path(__file__).parent/'scripts/worker_host.py'), *map(str, command)])
    else:
        process.start('setsid', list(map(str, command)))


def signal_tree(pid, sig):
    if not pid:
        return
    if os.name == 'nt':
        # The worker host owns a kill-on-close Job Object containing descendants.
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(1, False, pid)
        if handle:
            try: kernel.TerminateProcess(handle, 1)
            finally: kernel.CloseHandle(handle)
    else:
        try: os.killpg(pid, sig)
        except ProcessLookupError: pass
