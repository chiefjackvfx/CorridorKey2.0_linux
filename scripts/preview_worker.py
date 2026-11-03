#!/usr/bin/env python3
"""Persistent CUDA preview worker: JSON requests on stdin, JSON replies on stdout."""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'


def extract(source, index, fps, destination):
    source = Path(source)
    destination.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        frames = sorted(p for p in source.iterdir() if p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.exr'})
        if not 0 <= index < len(frames):
            raise ValueError('Requested frame is outside the input or hint sequence.')
        target = destination / ('frame' + frames[index].suffix)
        target.symlink_to(frames[index].resolve())
    else:
        target = destination / 'frame.png'
        subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(index/fps), '-i', str(source),
                        '-frames:v', '1', '-threads', '1', str(target)], check=True,
                       stdout=subprocess.DEVNULL, stderr=sys.stderr, timeout=30)
        if not target.exists():
            raise ValueError('No frame at the requested time in the input or hint video.')
    return target


def prepare_preview_input(frame, work, max_dimension=1280):
    """Resize into a new directory, never through an input symlink.

    Bounding the physical preview input caps viewer size and GPU use.
    Internal resolution then scales model input relative to this preview plate.
    """
    import cv2
    pixels = cv2.imread(str(frame), cv2.IMREAD_UNCHANGED)
    if pixels is None:
        raise ValueError('Cannot decode input frame.')
    height, width = pixels.shape[:2]
    if max(height, width) <= max_dimension:
        return frame.parent
    scale = max_dimension / max(height, width)
    resized = cv2.resize(pixels, (max(1, round(width*scale)), max(1, round(height*scale))),
                         interpolation=cv2.INTER_LANCZOS4)
    directory = Path(work) / 'preview_input'
    directory.mkdir()
    # Keep linear EXR values as float; PNG is sufficient for decoded video/JPEG.
    destination = directory / ('frame.exr' if frame.suffix.lower() == '.exr' else 'frame.png')
    if not cv2.imwrite(str(destination), resized):
        raise RuntimeError('Unable to write the resized preview input.')
    return directory


def prepare_preview_hint(hint, preview_input, work):
    """Match the temporary hint to the resized frame; keep originals untouched."""
    import cv2
    import numpy as np
    frame = next(Path(preview_input).iterdir())
    target = cv2.imread(str(frame), cv2.IMREAD_UNCHANGED)
    pixels = cv2.imread(str(hint), cv2.IMREAD_UNCHANGED)
    if target is None or pixels is None:
        raise ValueError('Cannot decode preview hint.')
    if pixels.shape[:2] == target.shape[:2]:
        return hint
    pixels = cv2.resize(pixels, (target.shape[1], target.shape[0]), interpolation=cv2.INTER_LANCZOS4)
    extension = '.exr' if np.issubdtype(pixels.dtype, np.floating) else '.png'
    destination = Path(work) / ('preview_hint' + extension)
    if not cv2.imwrite(str(destination), pixels):
        raise RuntimeError('Unable to write the resized preview hint.')
    return destination


def main():
    output = sys.stdout
    def reply(data):
        output.write(json.dumps(data) + '\n')
        output.flush()
    with contextlib.redirect_stdout(sys.stderr):
        import cv2
        import numpy as np
        from corridorkey.runtime import RuntimePaths, InferenceConfig, WriterConfig, load_model, run_inference
        model = load_model(RuntimePaths.from_package(ROOT), device='cuda')
    reply({'ready': True})
    for line in sys.stdin:
        request = json.loads(line)
        try:
            with contextlib.redirect_stdout(sys.stderr):
                work = Path(request['work'])
                frame = extract(request['source'], request['frame'], request['fps'], work / 'input')
                preview_input = prepare_preview_input(frame, work)
                options = request['options']
                if options.get('input_color_space') == 'acescg' and not Path(request['source']).is_dir():
                    raise ValueError('ACEScg input requires an image sequence.')
                hint = None
                if options['hint_mode'] == 'video':
                    hint = extract(options['hint_path'], request['frame'], request['fps'], work / 'hint')
                elif options['hint_mode'] == 'first' and request['frame'] == 0:
                    candidate = Path(options['hint_path'])
                    hint = extract(candidate, 0, request['fps'], work / 'hint') if candidate.is_dir() else candidate
                if hint is not None:
                    hint = prepare_preview_hint(hint, preview_input, work)
                cfg = InferenceConfig(hann_chunk=1, hann_stride=1, auto_vram=False,
                    low_vram=options['memory']=='low', num_frames=1, carry_hint=False,
                    hint_quality=options['hint_quality'], despill_strength=options['despill'],
                    frame_dir_linear=options['linear'] and Path(request['source']).is_dir(),
                    frame_dir_fps=request['fps'], model_scale=options.get('model_scale', 1.0),
                    cutout_premultiplied=options.get('cutout_premultiplied', False),
                    keep_original=options.get('keep_original', False),
                    input_color_space=options.get('input_color_space', 'rec709'),
                    outputs={'alpha', 'fg', 'checker', 'cutout'}, output_format='exr',
                    temp_dir=work / 'scratch')
                run_inference(model, str(preview_input), str(work/'output'), cfg, WriterConfig(),
                              initial_hint_path=str(hint) if hint else None, hint_video_path=None)
                results = {}
                for channel in ('alpha', 'fg', 'checker', 'cutout'):
                    path = next((work/'output').glob(f'*_{channel}*_exr/*.exr'))
                    data = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
                    if channel == 'cutout' and cfg.cutout_premultiplied:
                        # PNG/Qt expects straight RGB; unassociate before display encoding.
                        alpha = data[..., 3:4]
                        data[..., :3] = np.divide(data[..., :3], alpha,
                            out=np.zeros_like(data[..., :3]), where=alpha > 1e-8)
                    if channel != 'alpha':
                        rgb = np.maximum(data[..., :3], 0)
                        data[..., :3] = np.where(rgb <= .0031308, rgb*12.92, 1.055*np.power(rgb, 1/2.4)-.055)
                    target = work / f'{channel}.png'
                    if not cv2.imwrite(str(target), (np.clip(data, 0, 1)*255).astype(np.uint8)):
                        raise RuntimeError('Unable to write preview image.')
                    results[channel] = str(target)
            reply({'id': request['id'], 'images': results})
        except Exception as exc:
            reply({'id': request['id'], 'error': str(exc)})


if __name__ == '__main__':
    main()
