"""Disposable application storage relative to the installation, never AppData."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def cache_path(category, root=ROOT):
    relative = Path(category)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Cache categories must stay inside the project cache.')
    return Path(root).resolve() / '.cache' / relative


def cache_directory(category, root=ROOT):
    directory = cache_path(category, root)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def cache_environment(root=ROOT):
    directory = cache_directory('temp', root)
    base = directory.parent
    return {
        'TMP': str(directory), 'TEMP': str(directory), 'TMPDIR': str(directory),
        'XDG_CACHE_HOME': str(base / 'xdg'),
        'HF_HOME': str(base / 'huggingface'),
        'HF_HUB_CACHE': str(base / 'huggingface/hub'),
        'HUGGINGFACE_HUB_CACHE': str(base / 'huggingface/hub'),
        'HF_ASSETS_CACHE': str(base / 'huggingface/assets'),
        'HF_XET_CACHE': str(base / 'huggingface/xet'),
        'TORCH_EXTENSIONS_DIR': str(base / 'torch-extensions'),
        'MPLCONFIGDIR': str(base / 'matplotlib'),
        'TORCH_HOME': str(base / 'torch'),
        'TORCHINDUCTOR_CACHE_DIR': str(base / 'torchinductor'),
        'TRITON_CACHE_DIR': str(base / 'triton'),
        'CUDA_CACHE_PATH': str(base / 'cuda'),
        'NUMBA_CACHE_DIR': str(base / 'numba'),
        'PIP_CACHE_DIR': str(base / 'pip'),
        'UV_CACHE_DIR': str(base / 'uv'),
        'PYTHONPYCACHEPREFIX': str(base / 'python'),
    }
