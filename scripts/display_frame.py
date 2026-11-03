#!/usr/bin/env python3
"""Decode and color-correct an original or rendered frame for the viewer."""
import os
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
from color_management import acescg_to_linear709
path, space, linear = sys.argv[1:4]
premultiplied = len(sys.argv) > 4 and sys.argv[4] == '1'
if len(sys.argv) > 5:
    decoded = subprocess.run(['ffmpeg', '-v', 'error', '-ss', sys.argv[5], '-i', path,
        '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-threads', '1', 'pipe:1'],
        check=True, stdout=subprocess.PIPE, timeout=25)
    image = cv2.imdecode(np.frombuffer(decoded.stdout, np.uint8), cv2.IMREAD_UNCHANGED)
else:
    image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
if image is None:
    raise ValueError('Unable to decode display frame')
if image.dtype == np.uint8:
    image = image.astype(np.float32)/255
elif image.dtype == np.uint16:
    image = image.astype(np.float32)/65535
else:
    image = image.astype(np.float32)
# Unassociate in the stored encoding before linear/display conversion.
if premultiplied and image.ndim == 3 and image.shape[2] == 4:
    alpha = image[..., 3:4]
    image[..., :3] = np.divide(image[..., :3], alpha,
        out=np.zeros_like(image[..., :3]), where=alpha > 1e-8)
scale = min(1, 1280/max(image.shape[:2]))
image = cv2.resize(image, (max(1, round(image.shape[1]*scale)), max(1, round(image.shape[0]*scale))))
rgb = image[..., :3][..., ::-1]
if space == 'acescg':
    rgb = acescg_to_linear709(rgb)
if linear == '1' or space == 'acescg':
    rgb = np.maximum(rgb, 0)
    rgb = np.where(rgb <= .0031308, rgb*12.92, 1.055*np.power(rgb, 1/2.4)-.055)
image[..., :3] = rgb[..., ::-1]
ok, data = cv2.imencode('.png', (np.clip(image, 0, 1)*255).astype(np.uint8))
if not ok:
    raise RuntimeError('Cannot encode display frame')
sys.stdout.buffer.write(data.tobytes())
