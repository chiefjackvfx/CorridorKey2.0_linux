#!/usr/bin/env python3
"""GPU integration: ACEScg sequence, full preview cache, reuse, invalidation, export."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ['OPENCV_IO_ENABLE_OPENEXR']='1'
import sys, tempfile, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import cv2
import numpy as np
from PySide6.QtCore import QSettings,Qt,QProcess
from PySide6.QtWidgets import QApplication
from linux_app import Window
from unittest.mock import patch


def main():
    os.environ.pop('QT_QPA_PLATFORM_PLUGIN_PATH',None)
    app=QApplication([])
    with tempfile.TemporaryDirectory(prefix='ck-cache-color-test-') as temp:
        root=Path(temp); source=root/'source'; source.mkdir()
        for i in range(3):
            frame=np.full((288,512,3),(.05,.6,.05),np.float32)
            cv2.rectangle(frame,(200+i*5,40),(300+i*5,240),(.05,.12,.7),-1)
            cv2.imwrite(str(source/f'{i:04d}.exr'),frame)
        window=Window(QSettings(str(root/'settings.ini'),QSettings.IniFormat))
        window.input_space.setCurrentIndex(window.input_space.findData('acescg'))
        def wait(condition):
            deadline=time.monotonic()+120
            while not condition():
                app.processEvents();time.sleep(.02)
                if time.monotonic()>deadline:
                    raise AssertionError(window.view_note.text()+'\n'+window.log.toPlainText())
        try:
            window.add_paths([source])
            wait(lambda: bool(window.preview_images))
            window.cache_selected_clip()
            wait(lambda: window.preview_engine.background_done==3 and not window.preview_engine.busy)
            assert len(window.preview_engine.frames.entries)==3
            with patch.object(window.preview_engine.process,'write') as write:
                window.viewer.slider.setValue(2)
                assert window.preview_images
                assert 'Cached key' in window.view_note.text()
                window.viewer.slider.setValue(0)
                write.assert_not_called()
            print('PASS: entire ACEScg clip cached; revisits require no inference',flush=True)
            window.despill.setValue(.7)
            wait(lambda: bool(window.preview_images))
            assert len(window.preview_engine.frames.entries)==4
            print('PASS: changed settings invalidate cached preview',flush=True)
            window.format.setCurrentIndex(window.format.findData('exr'))
            window.destination.setText(str(root/'out'))
            window.start_queue()
            wait(lambda: window.start_button.isEnabled())
            data=window.queue.item(0).data(Qt.UserRole)
            assert data['state']=='Done',window.log.toPlainText()
            metadata=next((Path(data['job_dir'])/'render').glob('*settings.txt')).read_text()
            assert 'Input Color Space: acescg' in metadata
            assert 'Output Primaries: Rec.709/sRGB D65' in metadata
            assert sum(len(list(Path(folder).glob('*.exr'))) for folder in data['passes'].values())==12
            print('PASS: ACEScg full render writes linear Rec.709 EXRs and color metadata',flush=True)
            window.clear_preview_cache()
            # Stop immediately, before the debounced replacement preview runs.
            window.auto_preview.setChecked(False)
            assert not window.preview_engine.frames.entries
        finally:
            if window.process.state()!=QProcess.NotRunning:
                window.stop_queue();window.force_stop(window.process.processId());window.process.waitForFinished(5000)
            window.close()


if __name__=='__main__':main()
