"""Project-local executable discovery shared by launchers and workers."""
import os
from pathlib import Path
import sys
from app_cache import cache_environment

ROOT = Path(__file__).resolve().parent


def environment(root=ROOT):
    env = os.environ.copy()
    env.update(cache_environment(root))
    for name in ('TRANSFORMERS_CACHE', 'PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
        env.pop(name, None)
    env['PYTHONNOUSERSITE'] = '1'
    tools = Path(root) / '.runtime' / 'ffmpeg' / 'bin'
    env['PATH'] = str(tools) + os.pathsep + env.get('PATH', '')
    env['OPENCV_IO_ENABLE_OPENEXR'] = '1'
    env['PYTHONUTF8'] = '1'
    return env


def configure(root=ROOT):
    os.environ.update(environment(root))
    import tempfile
    tempfile.tempdir = os.environ['TEMP']
    sys.pycache_prefix = os.environ['PYTHONPYCACHEPREFIX']
    for name in ('TRANSFORMERS_CACHE', 'PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
        os.environ.pop(name, None)


def python_path(root=ROOT):
    return Path(root) / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
