import os
os.environ['OPENCV_IO_ENABLE_OPENEXR']='1'
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
import errno
import json
import tempfile
import time
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from linux_export import (plan_export,Reservation,publish_passes,runtime_passes,validate_passes,
                         write_json,source_start,reservation_cache_path)
from linux_jobs import Options


class ExportFiles(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'shot_DN_v001';self.source.mkdir()
        for index in (1001,1002):
            cv2.imwrite(str(self.source/f'shot.{index}.exr'),np.full((16,32,3),.2,np.float32))

    def reserve(self,passes=('fg','alpha'),sibling=True):
        reservation=Reservation.reserve(self.source,self.root/'custom',passes,sibling=sibling)
        self.addCleanup(reservation.close);return reservation

    def outputs(self,passes=('fg','alpha')):
        directory=self.root/'work';directory.mkdir(exist_ok=True)
        for key in passes:
            target=directory/f'shot_{key}_exr';target.mkdir()
            shape=(16,32) if key=='alpha' else (16,32,4 if key=='cutout' else 3)
            for index in range(2):cv2.imwrite(str(target/f'{key}_{index:06d}.exr'),np.full(shape,.5,np.float32))
        return runtime_passes(directory,passes,'exr')

    def test_plan_is_readonly_and_numbering_and_locations_follow_source(self):
        plan=plan_export(self.source,self.root/'absent',('fg','alpha'),sibling=False)
        self.assertFalse((self.root/'absent').exists())
        self.assertEqual(plan.first_frame,1001)
        self.assertEqual(Path(plan.folders['fg']).name,'shot_DN_fg_v001')
        self.assertEqual(plan.filename('fg'),'shot_DN_fg_v001.1001.exr')
        sibling=plan_export(self.source,'',('alpha',),sibling=True)
        self.assertEqual(sibling.parent,str(self.root))
        movie=self.root/'movie_v003.mov';movie.touch()
        self.assertEqual(source_start(movie),1001)
        video=plan_export(movie,'',('cutout',),sibling=True,output_format='video')
        self.assertEqual(video.filename('cutout'),'movie_cutout_v003.mov')
        with self.assertRaises(ValueError):plan_export(self.source,'',(),sibling=True)

    def test_versions_are_shared_across_passes_and_concurrent_jobs(self):
        (self.root/'shot_DN_checker_v004').mkdir()
        with ThreadPoolExecutor(max_workers=4) as pool:
            reservations=list(pool.map(lambda _:self.reserve(('alpha',)),range(4)))
        self.assertEqual(sorted(r.plan.version for r in reservations),[5,6,7,8])
        self.assertEqual(plan_export(self.source,'',('fg',),sibling=True).version,9)

    def test_reservations_only_write_to_local_cache(self):
        original={p.name for p in self.root.iterdir()}
        cache=reservation_cache_path(self.root,'shot_DN')
        self.assertFalse(cache.exists())
        plan_export(self.source,'',('alpha',),sibling=True)
        self.assertFalse(cache.exists())
        reservation=self.reserve(('alpha',))
        self.assertEqual(reservation.lock.parent,cache)
        self.assertTrue(reservation.lock.is_relative_to(Path.cwd()/'.cache/export-locks'))
        self.assertEqual({p.name for p in self.root.iterdir()},original)
        reservation.close();self.assertFalse(reservation.lock.exists())
        custom=self.reserve(('alpha',),sibling=False)
        self.assertFalse((self.root/'custom').exists())
        self.assertNotEqual(custom.lock.parent,cache)
        self.assertEqual(custom.plan.version,1)

    def test_destination_namespaces_and_legacy_locks_remain_safe(self):
        first=self.reserve(('alpha',))
        custom=self.reserve(('fg',),sibling=False)
        self.assertEqual(first.plan.version,1);self.assertEqual(custom.plan.version,1)
        self.assertNotEqual(first.lock.parent,custom.lock.parent)
        legacy=self.root/'.shot_DN_ck2_v006.lock';legacy.mkdir()
        self.assertEqual(plan_export(self.source,'',('alpha',),sibling=True).version,7)
        self.assertTrue(legacy.exists())

    def test_publish_keeps_bytes_and_only_selected_passes(self):
        files=self.outputs();reservation=self.reserve()
        originals={key:[p.read_bytes() for p in paths] for key,paths in files.items()}
        self.assertEqual(validate_passes(files,'exr',2),(2,(16,32)))
        result=publish_passes(reservation,files)
        for key,folder in result.items():
            paths=sorted(Path(folder).iterdir())
            self.assertEqual([p.name for p in paths],[reservation.plan.filename(key,i) for i in range(2)])
            self.assertEqual([p.read_bytes() for p in paths],originals[key])
        self.assertFalse((self.root/'shot_DN_cutout_v001').exists())
        self.assertFalse(list(self.root.glob('.ck2-publish-*')))

    def test_collision_rolls_back_own_pass_and_preserves_foreign_folder(self):
        files=self.outputs();reservation=self.reserve()
        foreign=Path(reservation.plan.folders['alpha']);foreign.mkdir()
        (foreign/'artist.txt').write_text('preserve')
        with self.assertRaises(FileExistsError):publish_passes(reservation,files)
        self.assertFalse(Path(reservation.plan.folders['fg']).exists())
        self.assertEqual((foreign/'artist.txt').read_text(),'preserve')
        self.assertTrue(all(p.exists() for paths in files.values() for p in paths))
        self.assertFalse(list(self.root.glob('.ck2-publish-*')))

    def test_cross_filesystem_copy_and_incomplete_output_failure(self):
        files=self.outputs();reservation=self.reserve()
        with patch('linux_export.os.link',side_effect=OSError(errno.EXDEV,'cross device')):
            result=publish_passes(reservation,files)
        self.assertEqual(next(Path(result['fg']).glob('*.exr')).read_bytes(),files['fg'][0].read_bytes())
        with self.assertRaises(ValueError):validate_passes(files,'exr',3)
        files['alpha'].pop()
        with self.assertRaises(ValueError):validate_passes(files,'exr')

    def test_cross_device_publication_never_creates_destination_cache(self):
        files=self.outputs();reservation=self.reserve()
        before={p.name for p in self.root.iterdir()}
        import linux_export
        real_cache=linux_export.cache_directory
        def local_cache(category,*args,**kwargs):
            self.assertEqual(category,'publish')
            self.assertFalse(args);self.assertFalse(kwargs)
            return real_cache(category)
        with patch('linux_export.rename_exclusive',side_effect=OSError(errno.EXDEV,'different filesystem')),patch('linux_export.cache_directory',side_effect=local_cache):
            result=publish_passes(reservation,files)
        after={p.name for p in self.root.iterdir()}
        self.assertEqual(after-before,{Path(folder).name for folder in result.values()})
        self.assertFalse((self.root/'.cache').exists())
        for key,folder in result.items():
            for index,source in enumerate(files[key]):
                self.assertEqual((Path(folder)/reservation.plan.filename(key,index)).read_bytes(),source.read_bytes())

    def test_windows_cross_volume_error_copies_without_destination_cache(self):
        files=self.outputs();reservation=self.reserve()
        error=OSError('The system cannot move the file to a different disk drive')
        error.winerror=17
        with patch('linux_export.rename_exclusive',side_effect=error):
            result=publish_passes(reservation,files)
        self.assertFalse((self.root/'.cache').exists())
        self.assertEqual((Path(result['alpha'])/reservation.plan.filename('alpha')).read_bytes(),files['alpha'][0].read_bytes())

    def test_cross_device_partial_copy_failure_rolls_back_owned_folders(self):
        files=self.outputs();reservation=self.reserve()
        before={p.name for p in self.root.iterdir()}
        def broken_copy(src,dst,*args):
            self.assertIn(str(Path(dst.name).parent),reservation.plan.folders.values())
            dst.write(b'partial');raise OSError('Network copy interrupted')
        with patch('linux_export.rename_exclusive',side_effect=OSError(errno.EXDEV,'different filesystem')),patch('linux_export.shutil.copyfileobj',side_effect=broken_copy):
            with self.assertRaises(OSError):publish_passes(reservation,files)
        self.assertEqual({p.name for p in self.root.iterdir()},before)
        self.assertTrue(all(p.exists() for paths in files.values() for p in paths))

    def test_cross_device_collision_and_receipt_failure_preserve_foreign_data(self):
        files=self.outputs();reservation=self.reserve()
        foreign=Path(reservation.plan.folders['alpha']);foreign.mkdir()
        (foreign/'keep.txt').write_text('keep')
        with patch('linux_export.rename_exclusive',side_effect=OSError(errno.EXDEV,'different filesystem')):
            with self.assertRaises(FileExistsError):publish_passes(reservation,files)
        self.assertFalse(Path(reservation.plan.folders['fg']).exists())
        self.assertEqual((foreign/'keep.txt').read_text(),'keep')
        (foreign/'keep.txt').unlink();foreign.rmdir()
        def failed_receipt(passes):raise OSError('Receipt write failed')
        with patch('linux_export.rename_exclusive',side_effect=OSError(errno.EXDEV,'different filesystem')):
            with self.assertRaises(OSError):publish_passes(reservation,files,failed_receipt)
        self.assertTrue(all(not Path(folder).exists() for folder in reservation.plan.folders.values()))
        self.assertFalse((self.root/'.cache').exists())

    def test_wrapper_completion_and_failure_release_reservation(self):
        from scripts.render_job import execute_job
        source=self.source
        class Inference:
            def __init__(self,command):
                directory=Path(command[command.index('--output_dir')+1]);directory.mkdir()
                for key in ('fg','alpha'):
                    target=directory/f'shot_{key}_exr';target.mkdir()
                    shape=(16,32) if key=='alpha' else (16,32,3)
                    for index in range(2):cv2.imwrite(str(target/f'{key}_{index:06d}.exr'),np.full(shape,.4,np.float32))
                (directory/'shot_settings.txt').write_text('Cutout Alpha: premultiplied\n')
            def wait(self):return 0
            def poll(self):return 0
        job=self.root/'private';job.mkdir();path=job/'export.json'
        payload=dict(id='test',source=str(source),base='',options=asdict(Options(outputs=('fg','alpha'),output_format='exr',save_sibling=True)),status='queued')
        write_json(path,payload)
        with patch('scripts.render_job.subprocess.Popen',Inference):self.assertEqual(execute_job(path),0)
        receipt=json.loads(path.read_text())
        self.assertEqual(receipt['status'],'complete');self.assertEqual(receipt['first_frame'],1001)
        self.assertEqual(set(receipt['passes']),{'fg','alpha'})
        self.assertFalse(list(self.root.glob('.*.lock')))
        self.assertFalse(list((job/'render').glob('*_exr')))
        self.assertTrue(Path(receipt['settings']).is_file())
        self.assertTrue(Path(receipt['work_dir']).is_relative_to(Path.cwd()/'.cache/renders'))
        self.assertFalse(Path(receipt['work_dir']).exists())
        self.assertFalse(Path(receipt['scratch_dir']).exists())
        failure=self.root/'failed';failure.mkdir();path=failure/'export.json';write_json(path,payload)
        with patch('scripts.render_job.subprocess.Popen',side_effect=OSError('failed to start')):
            self.assertEqual(execute_job(path),1)
        self.assertEqual(json.loads(path.read_text())['status'],'failed')
        self.assertFalse(list(self.root.glob('.*.lock')))
        self.assertFalse((self.root/'shot_DN_fg_v002').exists())

    def test_receipt_failure_rolls_back_every_published_pass(self):
        files=self.outputs();reservation=self.reserve()
        def failure(passes):raise OSError('receipt could not be saved')
        with self.assertRaises(OSError):publish_passes(reservation,files,failure)
        self.assertTrue(all(not Path(p).exists() for p in reservation.plan.folders.values()))
        self.assertTrue(all(path.exists() for paths in files.values() for path in paths))
        self.assertFalse(list(self.root.glob('.ck2-publish-*')))


class ExportUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_published_frames_and_filmstrip_use_numeric_frame_order(self):
        from PySide6.QtGui import QImage
        from PySide6.QtCore import Qt
        from linux_viewer import MediaViewer
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            image=QImage(32,16,QImage.Format_RGB32);image.fill(Qt.red)
            image.save(str(root/'shot_fg_v001.9999.png'))
            image.save(str(root/'shot_fg_v001.10000.png'))
            viewer=MediaViewer();viewer.numbered_frames=True
            try:
                viewer.set_source(root)
                self.assertEqual([p.name for p in viewer.images],['shot_fg_v001.9999.png','shot_fg_v001.10000.png'])
                if viewer.filmstrip.loader.current:
                    self.assertEqual(viewer.filmstrip.loader.current[1],viewer.images[0])
            finally:viewer.shutdown()

    def test_sibling_toggle_preview_persistence_and_rendered_pass_lookup(self):
        from PySide6.QtCore import QSettings,Qt
        from linux_app import Window
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'plate_v003';source.mkdir()
            cv2.imwrite(str(source/'plate.1050.exr'),np.zeros((16,32,3),np.float32))
            settings=QSettings(str(root/'settings.ini'),QSettings.IniFormat)
            window=Window(settings);window.auto_preview.setChecked(False)
            try:
                window.add_paths([source]);window.save_sibling.setChecked(True)
                for key,box in window.channels.items():box.setChecked(key=='cutout')
                self.assertFalse(window.destination.isEnabled())
                self.assertFalse(window.destination_button.isEnabled())
                self.assertEqual(window.options().outputs,('cutout',))
                window.format.setCurrentIndex(window.format.findData('exr'))
                self.assertEqual(window.output_preview.toPlainText(),str(root/'plate_cutout_v003/plate_cutout_v003.1050.exr'))
                self.assertTrue(settings.value('save_sibling'))
                folder=root/'plate_cutout_v003';folder.mkdir()
                (folder/'plate_cutout_v003.1050.exr').touch()
                work=root/'private/render';work.mkdir(parents=True)
                (work/'settings_settings.txt').write_text('Cutout Alpha: premultiplied\n')
                item=window.queue.currentItem();data=item.data(Qt.UserRole)
                data.update(state='Done',output=str(root),job_dir=str(work.parent),passes={'cutout':str(folder)})
                item.setData(Qt.UserRole,data)
                with patch.object(window.viewer,'set_source') as load:
                    window.view_mode.setCurrentIndex(window.view_mode.findData('cutout'))
                    self.assertEqual(load.call_args.args[0],folder)
                    self.assertTrue(window.viewer.input_premultiplied)
                    window.view_mode.setCurrentIndex(window.view_mode.findData('fg'))
                    self.assertIsNone(load.call_args.args[0])
            finally:window.close()
            reopened=Window(settings);reopened.auto_preview.setChecked(False)
            try:self.assertTrue(reopened.save_sibling.isChecked())
            finally:reopened.close()


if __name__=='__main__':unittest.main()
