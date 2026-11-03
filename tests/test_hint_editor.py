import os
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['OPENCV_IO_ENABLE_OPENEXR']='1'
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from hint_tools import screen_mask,union_sam_masks,save_hint,load_hint_frame
from sam_hint_backend import adapt_session_arguments


class HintImages(unittest.TestCase):
    def test_screen_seed_retains_subject_and_removes_screen(self):
        image=np.full((40,80,3),(10,180,10),np.uint8)
        image[10:30,30:50]=(10,10,200)
        mask=screen_mask(image)
        self.assertEqual(mask[0,0],0)
        self.assertEqual(mask[20,40],255)

    def test_sam_union_and_empty_results(self):
        masks=np.zeros((2,1,10,20),bool)
        masks[0,0,2:5,2:5]=True;masks[1,0,6:9,12:15]=True
        mask=union_sam_masks({'out_binary_masks':masks},(20,40))
        self.assertEqual(mask[6,6],255);self.assertEqual(mask[14,26],255)
        self.assertEqual(mask[0,0],0)
        with self.assertRaises(ValueError):union_sam_masks({'out_binary_masks':np.zeros((0,10,20))},(10,20))

    def test_native_size_export_and_source_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source';source.mkdir()
            path=source/'frame.exr'
            cv2.imwrite(str(path),np.full((100,200,3),.18,np.float32))
            before=path.read_bytes()
            image,hw=load_hint_frame(source,max_dimension=80)
            self.assertEqual(image.shape,(40,80,3));self.assertEqual(hw,(100,200))
            self.assertTrue(115<image[0,0,0]<120)
            target=Path(tmp)/'hint.png'
            save_hint(np.full((40,80),180,np.uint8),hw,target)
            mask=cv2.imread(str(target),cv2.IMREAD_UNCHANGED)
            self.assertEqual(mask.shape,(100,200));self.assertEqual(mask[0,0],180)
            self.assertEqual(before,path.read_bytes())

    def test_sam_session_adapter_drops_only_unsupported_false_flag(self):
        class Model:
            def init_state(self,resource_path,offload_video_to_cpu=False):
                return resource_path,offload_video_to_cpu
        class Predictor:model=Model()
        predictor=adapt_session_arguments(Predictor())
        self.assertEqual(predictor.model.init_state(resource_path='frames',offload_state_to_cpu=False,offload_video_to_cpu=True),('frames',True))
        with self.assertRaises(ValueError):predictor.model.init_state(resource_path='frames',offload_state_to_cpu=True)


class HintGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def wait(self,condition):
        deadline=time.monotonic()+12
        while not condition() and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.assertTrue(condition())

    def test_brush_coordinates_undo_and_redo(self):
        from PySide6.QtGui import QImage
        from PySide6.QtCore import Qt,QPoint
        from PySide6.QtTest import QTest
        from linux_hint_editor import HintCanvas
        canvas=HintCanvas();canvas.resize(400,300)
        canvas.image=QImage(200,100,QImage.Format_RGB32);canvas.image.fill(Qt.red)
        mask=QImage(200,100,QImage.Format_RGB32);mask.fill(Qt.black)
        canvas.set_mask(mask);canvas.brush=12;canvas.show();self.app.processEvents()
        try:
            # Letterboxed image occupies y=50..250; center maps to (100,50).
            QTest.mouseClick(canvas,Qt.LeftButton,pos=QPoint(200,150))
            self.assertGreater(canvas.mask.pixelColor(100,50).red(),240)
            canvas.undo();self.assertEqual(canvas.mask.pixelColor(100,50).red(),0)
            canvas.redo();self.assertGreater(canvas.mask.pixelColor(100,50).red(),240)
            QTest.mouseClick(canvas,Qt.RightButton,pos=QPoint(200,150))
            self.assertEqual(canvas.mask.pixelColor(100,50).red(),0)
        finally:canvas.close()

    def test_editor_loads_and_saves_native_hint_without_gpu(self):
        from PySide6.QtCore import QSettings,QProcess
        from linux_hint_editor import HintEditor
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir()
            cv2.imwrite(str(source/'frame.png'),np.full((120,240,3),(10,180,10),np.uint8))
            editor=HintEditor(Path.cwd(),source,QSettings(str(root/'settings.ini'),QSettings.IniFormat),linear=False)
            try:
                self.wait(lambda:not editor.busy)
                self.assertEqual(editor.native_hw,(120,240))
                self.assertFalse(editor.canvas.image.isNull())
                self.assertEqual(editor.process.state(),QProcess.Running)
                with patch('hint_tools.save_hint') as save:
                    editor.save_and_accept()
                    self.assertEqual(save.call_args.args[1],(120,240))
                    self.assertTrue(editor.saved_path.endswith('.png'))
                self.assertEqual(editor.process.state(),QProcess.NotRunning)
            finally:editor.reject()

    def test_hint_settings_follow_each_clip_and_queue(self):
        from PySide6.QtCore import QSettings,Qt
        from linux_app import Window
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'a.mp4';b=root/'b.mp4';a.touch();b.touch()
            hint=root/'hint.png';cv2.imwrite(str(hint),np.full((10,10),255,np.uint8))
            w=Window(QSettings(str(root/'settings.ini'),QSettings.IniFormat))
            w.auto_preview.setChecked(False)
            try:
                w.add_paths([a,b]);w.hint.setText(str(hint));w.hint_mode.setCurrentIndex(w.hint_mode.findData('first'))
                w.queue.setCurrentRow(1);self.assertEqual(w.hint.text(),'')
                w.queue.setCurrentRow(0);self.assertEqual(w.hint.text(),str(hint))
                w.destination.setText(str(root/'output'))
                with patch.object(w,'check_installation'):
                    w.start_queue()
                self.assertEqual(w.jobs[0][1].hint_path,str(hint))
                self.assertEqual(w.jobs[1][1].hint_mode,'none')
                self.assertEqual(w.jobs[1][1].hint_path,'')
            finally:w.jobs=[];w.close()


if __name__=='__main__':unittest.main()
