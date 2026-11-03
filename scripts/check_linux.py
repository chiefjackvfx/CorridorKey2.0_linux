#!/usr/bin/env python3
"""Report actionable Linux prerequisites; return nonzero until inference is ready."""
from pathlib import Path
import importlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    failures = []
    print(f'Python {sys.version.split()[0]} — {sys.executable}', flush=True)
    for module in ('torch', 'torchvision', 'cv2', 'transformers', 'timm',
                   'safetensors', 'einops', 'scipy', 'utils3d', 'PySide6'):
        try:
            importlib.import_module(module)
            print(f'OK: {module}', flush=True)
        except Exception as exc:
            failures.append(f'{module}: {exc}; rerun ./1-install.sh')
    for executable in ('ffmpeg', 'ffprobe', 'setsid'):
        if not shutil.which(executable):
            failures.append(f'{executable} missing from PATH')
    if shutil.which('ffmpeg'):
        result = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'],
                                capture_output=True, text=True)
        for encoder in ('libx264', 'prores_ks'):
            if encoder not in result.stdout:
                failures.append(f'FFmpeg encoder {encoder} unavailable')
    try:
        import torch
        if not torch.cuda.is_available():
            failures.append('CUDA unavailable. Check nvidia-smi and the NVIDIA driver.')
        else:
            index = torch.cuda.current_device()
            capability = torch.cuda.get_device_capability(index)
            print(f'GPU: {torch.cuda.get_device_name(index)}; CUDA {torch.version.cuda}', flush=True)
            if capability[0] < 8:
                failures.append('CK2.0 requires an Ampere (RTX 30-series) or newer GPU.')
            # Exercise the installed CUDA kernels, not just device detection.
            x = torch.ones((32, 32), device='cuda')
            assert (x @ x).sum().item() == 32768
            print('OK: CUDA computation', flush=True)
    except Exception as exc:
        failures.append(f'CUDA computation: {exc}')
    for relative in ('weights/corridorkey_v2.safetensors',
                     'weights/foundation_stats.safetensors',
                     'vfms/cradio/C-RADIOv4-SO400M/model.safetensors',
                     'vfms/cradio/C-RADIOv4-SO400M/config.json',
                     'vfms/moge/model.pt',
                     'vfms/rvm/pretrain_rvm_small16_256_204031069.npz'):
        path = ROOT / relative
        if not path.is_file() or not path.stat().st_size:
            failures.append(f'Missing {relative}; run venv/bin/python scripts/download_weights.py')
    for failure in failures:
        print(f'FAIL: {failure}', flush=True)
    print('Ready for inference.' if not failures else 'Inference is not ready.', flush=True)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
