import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
import cv2
from hint_selection import sam_instances,combine_masks,preserve_brush_changes,pick_object,prompt_requests


class SelectionMath(unittest.TestCase):
    def test_instances_retain_ids_and_overlap_picks_smallest(self):
        masks=np.zeros((2,1,10,20),bool)
        masks[0,0,1:9,1:19]=True;masks[1,0,3:6,5:9]=True
        objects=sam_instances({'out_binary_masks':masks,'out_obj_ids':np.array([8,12])},(20,40))
        self.assertEqual(set(objects),{8,12})
        self.assertEqual(pick_object(objects,.35,.45),12)
        self.assertEqual(pick_object(objects,.7,.6),8)
        self.assertIsNone(pick_object(objects,0,0))
        result=combine_masks(objects,{12},(20,40))
        self.assertEqual(result[8,14],255);self.assertEqual(result[12,28],0)

    def test_selection_changes_keep_brush_corrections(self):
        old=np.zeros((10,20),np.uint8);old[2:8,2:8]=255
        current=old.copy();current[3,3]=0;current[0,0]=255
        new=old.copy();new[2:8,12:18]=255
        changed=preserve_brush_changes(current,old,new)
        self.assertEqual(changed[3,3],0);self.assertEqual(changed[0,0],255)
        self.assertEqual(changed[3,14],255)

    def test_first_point_cache_adapter_keeps_new_mask_and_other_objects(self):
        from sam_hint_backend import adapt_interactive_frames
        class Model:
            def _build_sam2_output(self,state,index,refined=None):
                if index not in state['cached_frame_outputs']:return {}
                result=state['cached_frame_outputs'][index].copy()
                if refined:result.update(refined)
                return result
        class Predictor:model=Model()
        predictor=adapt_interactive_frames(Predictor())
        state={'cached_frame_outputs':{}}
        self.assertEqual(predictor.model._build_sam2_output(state,0,{1:'mask'}),{1:'mask'})
        state['cached_frame_outputs'][0]={1:'old'}
        self.assertEqual(predictor.model._build_sam2_output(state,0,{2:'new'}),{1:'old',2:'new'})

    def test_point_box_text_protocol_and_validation(self):
        recipe={'text':None,'box':None,'groups':[{'id':1,'points':[[.3,.5],[.6,.8]],'labels':[1,0]}]}
        requests=prompt_requests(recipe)
        self.assertNotIn('text',requests[0]);self.assertEqual(requests[0]['obj_id'],1)
        self.assertEqual(requests[0]['point_labels'],[1,0])
        recipe['text']='person';self.assertEqual(prompt_requests(recipe)[0],{'text':'person'})
        requests=prompt_requests({'box':[.1,.2,.3,.4]})
        self.assertEqual(requests[0]['bounding_boxes'],[[.1,.2,.3,.4]])
        for invalid in ({}, {'box':[.9,.2,.3,.4]}, {'groups':[{'id':1,'points':[[.2,.3]],'labels':[0]}]},
                        {'groups':[{'id':1,'points':[[1.2,.3]],'labels':[1]}]}):
            with self.assertRaises(ValueError):prompt_requests(invalid)


class SelectionGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_canvas_normalizes_clicks_and_dragged_boxes_with_letterboxing(self):
        from PySide6.QtCore import Qt,QPoint
        from PySide6.QtGui import QImage
        from PySide6.QtTest import QTest
        from linux_hint_editor import HintCanvas
        canvas=HintCanvas();canvas.resize(400,300)
        canvas.image=QImage(200,100,QImage.Format_RGB32);canvas.image.fill(Qt.red)
        mask=canvas.image.copy();mask.fill(Qt.black);canvas.set_mask(mask)
        points=[];boxes=[];picks=[]
        canvas.pointRequested.connect(lambda x,y,k:points.append((x,y,k)))
        canvas.boxRequested.connect(boxes.append)
        canvas.objectPicked.connect(lambda x,y,r:picks.append((x,y,r)))
        canvas.show();self.app.processEvents()
        try:
            canvas.mode='point_keep'
            QTest.mouseClick(canvas,Qt.LeftButton,pos=QPoint(100,100))
            QTest.mouseClick(canvas,Qt.RightButton,pos=QPoint(300,200))
            self.assertEqual(points,[(.25,.25,True),(.75,.75,False)])
            self.assertEqual(canvas.mask.pixelColor(50,25).red(),0)
            canvas.mode='box'
            QTest.mousePress(canvas,Qt.LeftButton,pos=QPoint(300,200))
            QTest.mouseMove(canvas,QPoint(100,100))
            QTest.mouseRelease(canvas,Qt.LeftButton,pos=QPoint(100,100))
            self.assertEqual(boxes,[[.25,.25,.5,.5]])
            canvas.mode='pick';QTest.mouseClick(canvas,Qt.RightButton,pos=QPoint(200,150))
            self.assertEqual(picks,[(.5,.5,True)])
        finally:canvas.close()

    def test_object_picker_preserves_brush_and_undo_restores_metadata(self):
        from PySide6.QtCore import QSettings,QPointF
        from linux_hint_editor import HintEditor
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir()
            cv2.imwrite(str(source/'frame.png'),np.full((100,200,3),(10,180,10),np.uint8))
            editor=HintEditor(Path.cwd(),source,QSettings(str(root/'s.ini'),QSettings.IniFormat),linear=False)
            try:
                end=time.monotonic()+12
                while editor.busy and time.monotonic()<end:self.app.processEvents();time.sleep(.01)
                self.assertFalse(editor.busy)
                a=np.zeros((100,200),np.uint8);a[20:80,20:80]=255
                b=np.zeros((100,200),np.uint8);b[20:80,120:180]=255
                editor.object_masks={1:a,2:b};editor.selected={1,2}
                editor.canvas.set_mask(editor.mask_image(np.maximum(a,b)),undo=False)
                editor.update_object_list()
                editor.canvas.remember();editor.canvas.last=None;editor.canvas.brush=8
                editor.canvas.paint_line(QPointF(50,50),False)
                revision=editor.revision
                editor.pick_selection(.75,.5)
                self.assertEqual(editor.selected,{1});self.assertEqual(editor.revision,revision)
                current=editor.image_array(editor.canvas.mask)
                self.assertEqual(current[50,50],0);self.assertEqual(current[50,150],0)
                editor.canvas.undo()
                self.assertEqual(editor.selected,{1,2})
                self.assertEqual(editor.image_array(editor.canvas.mask)[50,50],0)
                self.assertEqual(editor.image_array(editor.canvas.mask)[50,150],255)
                editor.canvas.redo();self.assertEqual(editor.selected,{1})
                editor.clear_mask();self.assertFalse(editor.object_masks)
                editor.canvas.undo();self.assertEqual(set(editor.object_masks),{1,2})
            finally:editor.reject()

    def test_first_dot_replaces_seed_and_failed_prompt_rolls_back(self):
        from PySide6.QtCore import QSettings
        from linux_hint_editor import HintEditor
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir()
            cv2.imwrite(str(source/'frame.png'),np.full((50,100,3),127,np.uint8))
            editor=HintEditor(Path.cwd(),source,QSettings(str(root/'s.ini'),QSettings.IniFormat),linear=False)
            try:
                end=time.monotonic()+12
                while editor.busy and time.monotonic()<end:self.app.processEvents();time.sleep(.01)
                seed=np.full((50,100),255,np.uint8);editor.canvas.set_mask(editor.mask_image(seed),undo=False)
                editor.pending_snapshot=editor.canvas.snapshot();editor.pending_kind='refine'
                editor.active_object=1;editor.recipe['groups']=[dict(id=1,points=[[.5,.5]],labels=[1])]
                object_mask=np.zeros((50,100),np.uint8);object_mask[10:40,30:70]=255
                path=root/'obj.png';cv2.imwrite(str(path),object_mask)
                editor.receive_objects([{'id':1,'mask':str(path)}])
                np.testing.assert_array_equal(editor.image_array(editor.canvas.mask),object_mask)
                editor.rollback_pending()
                self.assertFalse(editor.recipe['groups']);self.assertFalse(editor.object_masks)
                np.testing.assert_array_equal(editor.image_array(editor.canvas.mask),seed)
            finally:editor.reject()


if __name__=='__main__':unittest.main()
