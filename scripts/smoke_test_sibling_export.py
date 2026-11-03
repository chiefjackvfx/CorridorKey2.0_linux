#!/usr/bin/env python3
"""Actual GUI/GPU publication: sibling EXRs, pass selection, versions and custom video."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ['OPENCV_IO_ENABLE_OPENEXR']='1'
from pathlib import Path
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import cv2
import numpy as np
from PySide6.QtCore import QSettings,Qt,QProcess
from PySide6.QtWidgets import QApplication
from linux_app import Window


def main():
    base=ROOT/'outputs/sibling-export-smoke'
    source=base/'plate_DN_v001';source.mkdir(parents=True,exist_ok=True)
    for index in (1001,1002):
        image=np.full((288,512,3),(.03,.6,.03),np.float32)
        cv2.rectangle(image,(190,40),(310,245),(.1,.12,.8),-1)
        cv2.imwrite(str(source/f'plate.{index}.exr'),image)
    original={p.name:p.read_bytes() for p in source.iterdir()}
    movie=base/'movie_v003.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=green:s=512x288:r=25:d=0.08',
                    '-vf','drawbox=x=190:y=40:w=120:h=205:color=red:t=fill',
                    '-c:v','libx264','-pix_fmt','yuv420p',str(movie)],check=True)
    os.environ.pop('QT_QPA_PLATFORM_PLUGIN_PATH',None)
    app=QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        window=Window(QSettings(str(Path(tmp)/'settings.ini'),QSettings.IniFormat))
        window.auto_preview.setChecked(False);window.show()
        def wait(condition):
            end=time.monotonic()+180
            while not condition():
                app.processEvents();time.sleep(.02)
                if time.monotonic()>end:raise AssertionError(window.log.toPlainText())
        def render(clip,passes,sibling,fmt):
            window.save_sibling.setChecked(sibling)
            window.format.setCurrentIndex(window.format.findData(fmt))
            for key,checkbox in window.channels.items():checkbox.setChecked(key in passes)
            window.add_paths([clip]);window.queue.setCurrentRow(window.queue.count()-1)
            preview=window.output_preview.toPlainText()
            window.start_queue();wait(lambda:window.start_button.isEnabled())
            data=window.queue.currentItem().data(Qt.UserRole)
            assert data['state']=='Done',window.log.toPlainText()
            assert set(data['passes'])==set(passes)
            assert (Path(data['job_dir'])/'export.json').is_file()
            for key,folder in data['passes'].items():
                folder=Path(folder)
                assert str(folder) in preview,(folder,preview)
                files=list(folder.iterdir())
                assert files and all(p.suffix==('.exr' if fmt=='exr' else '.mov' if key=='cutout' else '.mp4') for p in files)
                if fmt=='exr':
                    assert len(files)==2
                    assert sorted(p.name for p in files)==[f'{folder.name}.{n}.exr' for n in (1001,1002)]
                    for path in files:
                        image=cv2.imread(str(path),cv2.IMREAD_UNCHANGED)
                        assert image.shape[:2]==(288,512) and np.isfinite(image).all()
                window.view_mode.setCurrentIndex(window.view_mode.findData(key))
                wait(lambda:not window.viewer.canvas.pixmap.isNull())
                assert window.viewer.slider.maximum()==1
            return data
        try:
            window.destination.clear()
            first=render(source,('alpha',),True,'exr')
            alpha=Path(first['passes']['alpha'])
            before={p.name:p.read_bytes() for p in alpha.iterdir()}
            print('PASS: alpha-only sibling EXRs; source-based 1001 numbering; private logs; rendered viewer',flush=True)
            second=render(source,('fg','cutout','checker'),True,'exr')
            for folder in second['passes'].values():assert Path(folder).parent==base
            versions={Path(folder).name.rsplit('_v',1)[1] for folder in second['passes'].values()}
            assert len(versions)==1
            assert int(next(iter(versions)))>int(alpha.name.rsplit('_v',1)[1])
            assert {p.name:p.read_bytes() for p in alpha.iterdir()}==before
            assert {p.name:p.read_bytes() for p in source.iterdir()}==original
            print('PASS: remaining selected passes share next version; previous version and inputs preserved',flush=True)
            window.destination.setText(str(base/'custom'))
            third=render(movie,('fg','cutout'),False,'video')
            assert window.destination.isEnabled()
            assert all(Path(p).parent==base/'custom' for p in third['passes'].values())
            print('PASS: custom destination, movie-name versioning, selected video passes and rendered viewer',flush=True)
            window.grab().save(str(base/'deliver.png'))
        finally:
            if window.process.state()!=QProcess.NotRunning:
                window.stop_queue();window.force_stop(window.process.processId());window.process.waitForFinished(5000)
            window.close()
    print('PASS: sibling export GPU integration',flush=True)


if __name__=='__main__':main()
