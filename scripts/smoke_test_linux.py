#!/usr/bin/env python3
"""Exercise the GUI queue with real CUDA inference and verify video/EXR exports."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('OPENCV_IO_ENABLE_OPENEXR', '1')

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QApplication
from linux_app import Window


def main():
    base = ROOT / 'outputs/linux-smoke'
    frames = base / 'input-frames'
    frames.mkdir(parents=True, exist_ok=True)
    for index in range(4):
        frame = np.full((288, 512, 3), (25, 190, 30), dtype=np.uint8)
        cv2.ellipse(frame, (250 + index * 5, 150), (65, 100), 0, 0, 360, (60, 70, 200), -1)
        cv2.imwrite(str(frames / f'{index:04d}.png'), frame)
    clip = base / 'synthetic.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', '24', '-i', str(frames / '%04d.png'),
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(clip)], check=True)
    # Importing cv2 can inject its own Qt plugin paths.
    os.environ.pop('QT_QPA_PLATFORM_PLUGIN_PATH', None)
    app = QApplication([])
    settings_dir = tempfile.TemporaryDirectory(prefix='ck2-smoke-settings-')
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, settings_dir.name)
    QSettings.setDefaultFormat(QSettings.IniFormat)
    window = Window(QSettings(str(Path(settings_dir.name)/'settings.ini'), QSettings.IniFormat))
    window.auto_preview.setChecked(False)
    window.destination.setText(str(base / 'results'))
    window.temporal.setCurrentIndex(window.temporal.findData(4))
    window.carry_quality.setValue(.85)
    window.show()
    for export, source in [('video', clip), ('exr', frames)]:
        window.format.setCurrentIndex(window.format.findData(export))
        window.add_paths([str(source)])
        window.queue.setCurrentRow(window.queue.count() - 1)
        item = window.queue.currentItem()
        window.start_queue()
        deadline = time.monotonic() + 300
        while not window.start_button.isEnabled():
            app.processEvents()
            time.sleep(.02)
            if time.monotonic() > deadline:
                window.stop_queue()
                window.force_stop(window.process.processId())
                window.process.waitForFinished(5000)
                raise TimeoutError(window.log.toPlainText())
        data = item.data(Qt.UserRole)
        assert data['state'] == 'Done', window.log.toPlainText()
        output = Path(data['output'])
        if export == 'video':
            videos = sorted(p for folder in data['passes'].values() for p in Path(folder).iterdir())
            assert len(videos) == 4, videos
            for video in videos:
                metadata = json.loads(subprocess.check_output([
                    'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_streams', '-of', 'json', str(video)]))
                stream = metadata['streams'][0]
                assert (stream['width'], stream['height'], int(stream['nb_frames'])) == (512, 288, 4), stream
                if video.suffix == '.mov':
                    assert stream['codec_name'] == 'prores' and 'a' in stream['pix_fmt'], stream
        else:
            images = sorted(p for folder in data['passes'].values() for p in Path(folder).glob('*.exr'))
            assert len(images) == 16, images
            for image in images:
                pixels = cv2.imread(str(image), cv2.IMREAD_UNCHANGED)
                assert pixels.shape[:2] == (288, 512) and np.isfinite(pixels).all()
                if 'cutout' in image.name:
                    assert pixels.shape[2] == 4
        print(f'PASS: GUI queue → CUDA → {export}: {output}', flush=True)
        for channel in ('alpha', 'fg', 'checker', 'cutout'):
            window.view_mode.setCurrentIndex(window.view_mode.findData(channel))
            deadline = time.monotonic() + 15
            while window.viewer.canvas.pixmap.isNull():
                app.processEvents()
                time.sleep(.02)
                assert time.monotonic() < deadline, f'Viewer failed: {export}/{channel}'
            assert window.viewer.slider.maximum() == 3
        print(f'PASS: {export} rendered-channel viewer', flush=True)
    window.grab().save(str(base / 'desktop.png'))
    window.close()
    settings_dir.cleanup()
    print('PASS: Linux GPU desktop smoke test', flush=True)


if __name__ == '__main__':
    main()
