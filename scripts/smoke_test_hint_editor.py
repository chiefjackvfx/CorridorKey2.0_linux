#!/usr/bin/env python3
"""Local GPU integration: SAM dialog → brush → hint attachment → CK preview/render."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ['OPENCV_IO_ENABLE_OPENEXR']='1'
from pathlib import Path
import argparse
import sys
import tempfile
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import cv2
import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings,QTimer,QProcess,QPointF,Qt
from linux_app import Window
from linux_hint_editor import HintEditor


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',required=True)
    parser.add_argument('--prompt',default='person')
    parser.add_argument('--reuse-hint',help='Reuse a previously verified native-size hint for CK-only validation.')
    parser.add_argument('--render',action='store_true',help='Render two frames at half internal resolution.')
    args=parser.parse_args()
    os.environ.pop('QT_QPA_PLATFORM_PLUGIN_PATH',None)
    app=QApplication([])
    base=ROOT/'outputs/hint-editor-smoke';base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        w=Window(QSettings(str(Path(tmp)/'settings.ini'),QSettings.IniFormat))
        w.auto_preview.setChecked(False)
        w.add_paths([args.source]);w.show()
        phase=['load'];errors=[];dimensions=[]
        def wait(condition):
            end=time.monotonic()+180
            while not condition():
                app.processEvents();time.sleep(.02)
                if 'Preview failed:' in w.view_note.text():
                    raise AssertionError(w.view_note.text())
                if time.monotonic()>end:
                    raise AssertionError(w.view_note.text()+'\n'+w.log.toPlainText())
        def factory(*values,**kwargs):
            editor=HintEditor(*values,**kwargs)
            editor.prompt.setText(args.prompt)
            timer=QTimer(editor);timer.setInterval(30)
            end=time.monotonic()+180
            def drive():
                try:
                    if time.monotonic()>end:raise TimeoutError(editor.status.text())
                    if editor.busy:return
                    if phase[0]=='load':
                        assert editor.native_hw,editor.status.text()
                        dimensions.append(editor.native_hw)
                        editor.generate_sam();phase[0]='sam'
                    elif phase[0]=='sam':
                        assert editor.status.text().startswith('Mask ready'),editor.status.text()
                        gray=editor.canvas.mask.convertToFormat(QImage.Format_Grayscale8)
                        # Masks must contain foreground and background, not an empty/full hint.
                        pixels=np.frombuffer(gray.constBits(),np.uint8)
                        assert pixels.max()==255 and pixels.min()==0
                        c=editor.canvas
                        before=c.mask.copy();c.remember();c.last=None
                        c.paint_line(QPointF(20,20),False);c.undo()
                        assert c.mask==before
                        editor.grab().save(str(base/'sam-editor.png'))
                        editor.save_and_accept();timer.stop();phase[0]='saved'
                except Exception as exc:
                    errors.append(str(exc));timer.stop();editor.reject()
            timer.timeout.connect(drive);timer.start()
            return editor
        try:
            if args.reuse_hint:
                hint=Path(args.reuse_hint).resolve()
                existing=cv2.imread(str(hint),cv2.IMREAD_UNCHANGED)
                dimensions.append(existing.shape[:2])
                w.hint.setText(str(hint));w.hint_mode.setCurrentIndex(w.hint_mode.findData('first'))
            else:
                with patch('linux_hint_editor.HintEditor',side_effect=factory):
                    w.create_hint()
                assert not errors,errors
                assert phase[0]=='saved',phase
            hint=Path(w.hint.text());assert hint.is_file()
            mask=cv2.imread(str(hint),cv2.IMREAD_UNCHANGED)
            assert mask.ndim==2 and mask.shape==dimensions[0]
            assert w.hint_mode.currentData()=='first'
            if not args.reuse_hint:
                assert not w.preview_engine.suspended
            print('PASS: saved hint attached to selected clip' if args.reuse_hint else
                  'PASS: real SAM 3.1 dialog, brush undo, native hint save, selected-clip attachment',flush=True)
            w.resolution.setCurrentIndex(w.resolution.findData(.25))
            w.memory.setCurrentIndex(w.memory.findData('low'))
            w.auto_preview.setChecked(True)
            wait(lambda:bool(w.preview_images))
            assert w.viewer.slider.value()==0
            print('PASS: CK automatically keys with the generated hint after SAM releases GPU',flush=True)
            if args.render:
                w.auto_preview.setChecked(False)
                w.resolution.setCurrentIndex(w.resolution.findData(.5))
                w.frames.setValue(2);w.format.setCurrentIndex(w.format.findData('exr'))
                w.destination.setText(str(base/'results'))
                w.start_queue();wait(lambda:w.start_button.isEnabled())
                data=w.queue.currentItem().data(Qt.UserRole)
                assert data['state']=='Done',w.log.toPlainText()
                paths=[p for folder in data['passes'].values() for p in Path(folder).glob('*.exr')];assert len(paths)==8
                for path in paths:
                    image=cv2.imread(str(path),cv2.IMREAD_UNCHANGED)
                    assert image.shape[:2]==dimensions[0] and np.isfinite(image).all()
                print('PASS: two full-size frames rendered with the SAM-generated first-frame hint',flush=True)
            print('Hint saved:',hint,flush=True)
        finally:
            if w.process.state()!=QProcess.NotRunning:
                w.stop_queue();w.force_stop(w.process.processId());w.process.waitForFinished(5000)
            w.close()


if __name__=='__main__':main()
