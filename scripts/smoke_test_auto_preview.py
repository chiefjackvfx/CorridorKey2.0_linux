#!/usr/bin/env python3
"""Verify automatic keying, frame/settings refresh, and preview/render exclusion."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import subprocess
import sys
import tempfile
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QProcess, QSettings, Qt
from PySide6.QtWidgets import QApplication
from linux_app import Window


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory(prefix='ck2-auto-test-') as temporary:
        directory = Path(temporary)
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, temporary)
        source = directory/'input.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'color=c=green:s=512x288:r=24:d=0.2', '-vf',
                        'drawbox=x=200:y=40:w=100:h=200:color=red:t=fill',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)], check=True)
        window = Window(QSettings(str(directory/'settings.ini'), QSettings.IniFormat))
        window.show()
        def wait(condition, timeout=120):
            deadline = time.monotonic()+timeout
            while not condition():
                app.processEvents()
                time.sleep(.02)
                if time.monotonic() > deadline:
                    raise AssertionError(window.view_note.text()+'\n'+window.log.toPlainText())
        try:
            window.add_paths([source])
            wait(lambda: bool(window.preview_images))
            assert window.queue.item(0).data(Qt.UserRole)['state'] == 'Queued'
            assert window.view_mode.currentData() == 'checker'
            assert not window.viewer.canvas.pixmap.isNull()
            pid = window.preview_engine.process.processId()
            print('PASS: import automatically produces keyed preview without rendering', flush=True)
            window.viewer.slider.setValue(2)
            wait(lambda: bool(window.preview_images))
            assert window.preview_engine.process.processId() == pid
            assert window.viewer.slider.value() == 2
            window.despill.setValue(.3)
            window.despill.setValue(.7)
            wait(lambda: bool(window.preview_images))
            assert window.preview_engine.process.processId() == pid
            print('PASS: scrubbing and settings reuse the loaded model', flush=True)
            window.destination.setText(str(directory/'renders'))
            window.frames.setValue(2)
            window.start_queue()
            assert window.preview_engine.process.state() == QProcess.NotRunning
            assert window.preview_engine.suspended
            wait(lambda: window.start_button.isEnabled())
            assert window.queue.item(0).data(Qt.UserRole)['state'] == 'Done', window.log.toPlainText()
            print('PASS: preview releases GPU before full rendering', flush=True)
            window.auto_preview.setChecked(False)
            assert window.preview_engine.process.state() == QProcess.NotRunning
        finally:
            if window.process.state() != QProcess.NotRunning:
                window.stop_queue()
                window.force_stop(window.process.processId())
                window.process.waitForFinished(5000)
            window.close()
    print('PASS: automatic preview smoke test', flush=True)


if __name__ == '__main__':
    main()
