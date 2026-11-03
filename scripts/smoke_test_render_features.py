#!/usr/bin/env python3
"""Actual GUI/CUDA integration for internal scale, restoration and alpha modes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ['OPENCV_IO_ENABLE_OPENEXR']='1'
from pathlib import Path
import json
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
    base=ROOT/'outputs/render-features-smoke'
    source=base/'source';source.mkdir(parents=True,exist_ok=True)
    for i in range(2):
        image=np.full((288,512,3),(.03,.6,.03),np.float32)
        cv2.rectangle(image,(180+i*5,35),(320+i*5,255),(.1,.15,1.5),-1)
        cv2.imwrite(str(source/f'{i:04d}.exr'),image)
    video=base/'input.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',
        'color=c=green:s=512x288:r=25:d=0.08','-vf',
        'drawbox=x=180:y=35:w=140:h=220:color=red:t=fill',
        '-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True)
    os.environ.pop('QT_QPA_PLATFORM_PLUGIN_PATH',None)
    app=QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        w=Window(QSettings(str(Path(tmp)/'settings.ini'),QSettings.IniFormat))
        def wait(condition):
            deadline=time.monotonic()+180
            while not condition():
                app.processEvents();time.sleep(.02)
                if time.monotonic()>deadline:
                    raise AssertionError(w.view_note.text()+'\n'+w.log.toPlainText())
        try:
            w.resolution.setCurrentIndex(w.resolution.findData(.25))
            w.keep_original.setChecked(True)
            w.add_paths([source])
            wait(lambda:bool(w.preview_images))
            image=cv2.imread(w.preview_images['cutout'],cv2.IMREAD_UNCHANGED)
            assert image.shape==(288,512,4),image.shape
            print('PASS: quarter-resolution automatic preview remains full viewer size',flush=True)
            w.resolution.setCurrentIndex(w.resolution.findData(.5))
            wait(lambda:bool(w.preview_images))
            assert len(w.preview_engine.frames.entries)==2
            print('PASS: resolution changes invalidate the preview cache',flush=True)
            w.auto_preview.setChecked(False)
            w.destination.setText(str(base/'results'))
            for scale,fmt,clip in [(.5,'exr',source),(.25,'video',video)]:
                w.resolution.setCurrentIndex(w.resolution.findData(scale))
                w.format.setCurrentIndex(w.format.findData(fmt))
                if clip==video:
                    w.add_paths([video]);w.queue.setCurrentRow(w.queue.count()-1)
                    w.alpha_mode.setCurrentIndex(w.alpha_mode.findData(False))
                    w.cutout_linear.setChecked(True)
                w.start_queue();wait(lambda:w.start_button.isEnabled())
                data=w.queue.currentItem().data(Qt.UserRole)
                assert data['state']=='Done',w.log.toPlainText()
                out=Path(data['job_dir'])/'render'
                settings=next(out.glob('*settings.txt')).read_text()
                assert f'Model Scale: {scale}' in settings
                assert 'Keep Original in Solid Areas: True' in settings
                if fmt=='exr':
                    images=[p for folder in data['passes'].values() for p in Path(folder).glob('*.exr')];assert len(images)==8
                    for path in images:
                        pixels=cv2.imread(str(path),cv2.IMREAD_UNCHANGED)
                        assert pixels.shape[:2]==(288,512) and np.isfinite(pixels).all()
                    cutouts=sorted(Path(data['passes']['cutout']).glob('*.exr'))
                    fg=sorted(Path(data['passes']['fg']).glob('*.exr'))
                    for a,b in zip(cutouts,fg):
                        rgba=cv2.imread(str(a),cv2.IMREAD_UNCHANGED)
                        rgb=cv2.imread(str(b),cv2.IMREAD_UNCHANGED)
                        np.testing.assert_allclose(rgba[...,:3],rgb*rgba[...,3:4],atol=.002,rtol=.002)
                    assert 'Cutout Alpha: premultiplied' in settings
                else:
                    outputs=[p for folder in data['passes'].values() for p in Path(folder).iterdir()];assert len(outputs)==4
                    for path in outputs:
                        stream=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(path)]))['streams'][0]
                        assert (stream['width'],stream['height'],int(stream['nb_frames']))==(512,288,2)
                    assert 'Cutout Alpha: straight' in settings
                w.view_mode.setCurrentIndex(w.view_mode.findData('cutout'))
                wait(lambda:not w.viewer.canvas.pixmap.isNull())
                assert w.viewer.input_premultiplied == (fmt=='exr')
                print(f'PASS: {scale} internal scale, {fmt} export, restoration, alpha and rendered viewer',flush=True)
        finally:
            if w.process.state()!=QProcess.NotRunning:
                w.stop_queue();w.force_stop(w.process.processId());w.process.waitForFinished(5000)
            w.close()
    print('PASS: render-feature GPU integration',flush=True)


if __name__=='__main__':main()
