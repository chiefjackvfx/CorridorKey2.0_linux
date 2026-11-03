#!/usr/bin/env python3
"""Real SAM 3.1/Qt integration: points, exclude dots, boxes, and object picking."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ['OPENCV_IO_ENABLE_OPENEXR']='1'
import argparse
from pathlib import Path
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings,Qt,QPoint
from PySide6.QtTest import QTest
from linux_hint_editor import HintEditor


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',required=True)
    parser.add_argument('--point',nargs=2,type=float,default=[.435,.48])
    parser.add_argument('--second-point',nargs=2,type=float,default=[.57,.50])
    parser.add_argument('--box',nargs=4,type=float,default=[.41,.12,.22,.23])
    parser.add_argument('--prompt',default='person')
    args=parser.parse_args()
    app=QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        settings=QSettings(str(Path(tmp)/'settings.ini'),QSettings.IniFormat)
        editor=HintEditor(ROOT,args.source,settings)
        editor.show()
        def wait():
            end=time.monotonic()+150
            while editor.busy:
                app.processEvents();time.sleep(.02)
                if time.monotonic()>end:raise AssertionError(editor.status.text())
            assert not editor.status.text().startswith(('Generation failed','Could not','Hint worker')),editor.status.text()+'\n'+editor.errors[-1500:]
        def point(x,y):
            rect=editor.canvas.image_rect()
            return QPoint(round(rect.x()+x*rect.width()),round(rect.y()+y*rect.height()))
        def click(x,y,button=Qt.LeftButton):
            QTest.mouseClick(editor.canvas,button,pos=point(x,y));wait()
        try:
            wait();editor.clear_mask()
            editor.tool.setCurrentIndex(editor.tool.findData('point_keep'))
            click(*args.point)
            assert len(editor.object_masks)==1
            assert editor.recipe['text'] is None and len(editor.canvas.markers)==1
            first_mask=editor.canvas.mask.copy()
            click(.2,.4,Qt.RightButton)
            assert editor.recipe['groups'][0]['labels']==[1,0]
            editor.canvas.undo()
            assert editor.recipe['groups'][0]['labels']==[1]
            assert editor.canvas.mask==first_mask
            editor.canvas.redo()
            assert editor.recipe['groups'][0]['labels']==[1,0]
            print('PASS: include/exclude dots without text; undo/redo restores masks and prompts',flush=True)
            editor.new_object();click(*args.second_point)
            assert len(editor.object_masks)>=2
            revision=editor.revision
            editor.select_all(False);assert not editor.selected
            editor.tool.setCurrentIndex(editor.tool.findData('pick'))
            click(*args.point)
            assert len(editor.selected)==1
            assert editor.revision==revision
            assert editor.canvas.show_objects
            print('PASS: new object plus colored object picker; toggles need no GPU inference',flush=True)
            editor.tool.setCurrentIndex(editor.tool.findData('box'))
            x,y,w,h=args.box
            QTest.mousePress(editor.canvas,Qt.LeftButton,pos=point(x,y))
            QTest.mouseMove(editor.canvas,point(x+w,y+h))
            QTest.mouseRelease(editor.canvas,Qt.LeftButton,pos=point(x+w,y+h))
            wait();assert editor.recipe['box'] is not None
            assert editor.object_masks
            print('PASS: dragged box generates a selection without text',flush=True)
            editor.prompt.setText(args.prompt);editor.generate_sam();wait()
            assert editor.object_masks and editor.recipe['text']==args.prompt
            from hint_selection import pick_object
            ident=pick_object(editor.object_masks,*args.point)
            assert ident is not None
            editor.active_object=ident
            editor.tool.setCurrentIndex(editor.tool.findData('point_keep'))
            click(*args.point)
            assert editor.recipe['groups'][0]['id']==ident
            print('PASS: refine a text-detected object with an include point',flush=True)
            editor.display.setCurrentIndex(2)
            out=ROOT/'outputs/hint-selection-smoke';out.mkdir(parents=True,exist_ok=True)
            editor.grab().save(str(out/'object-picker.png'))
            editor.save_and_accept()
            assert Path(editor.saved_path).is_file()
            print('PASS: object/point selection saves as a native-size CK hint:',editor.saved_path,flush=True)
        finally:editor.reject()


if __name__=='__main__':main()
