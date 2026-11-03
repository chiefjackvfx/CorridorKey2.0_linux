import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import tempfile
import unittest
import time

from linux_jobs import Options, build_command, new_destination, validate_source


class Commands(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ck2 tests ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clip = self.root / 'clip with spaces;$(echo unsafe).mp4'
        self.clip.touch()

    def command(self, options=Options()):
        return build_command(self.root, '/usr/bin/python3', self.clip, self.root / 'out', options)

    def test_paths_are_single_arguments_and_scratch_is_isolated(self):
        cmd = self.command()
        self.assertEqual(cmd[cmd.index('--input') + 1], str(self.clip))
        self.assertEqual(cmd[cmd.index('--temp_dir') + 1], str(self.root / 'out/.scratch'))
        self.assertNotIn('--hann_chunk', cmd)

    def test_hints_and_low_memory(self):
        hint = self.root / 'hint image.png'
        hint.touch()
        cmd = self.command(Options(memory='low', hint_mode='first', hint_path=str(hint), carry=False))
        self.assertIn('--hint_first_frame', cmd)
        self.assertIn('--no_carry_hint', cmd)
        self.assertEqual(cmd[cmd.index('--hann_chunk') + 1], '16')
        cmd = self.command(Options(hint_mode='video', hint_path=str(hint), output_format='exr'))
        self.assertIn('--hint_video', cmd)
        self.assertIn('exr', cmd)

    def test_reject_invalid_inputs(self):
        for options in (Options(outputs=()), Options(hint_mode='first'), Options(fps=0),
                        Options(despill=2), Options(num_frames=0), Options(memory='invalid')):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.command(options)
        with self.assertRaises(ValueError):
            validate_source(self.root / 'missing.mp4')

    def test_sequence_and_unique_outputs(self):
        (self.root / 'frame.png').touch()
        self.assertEqual(validate_source(self.root), self.root)
        first = new_destination(self.root / 'results', self.clip)
        second = new_destination(self.root / 'results', self.clip)
        self.assertNotEqual(first, second)

    def test_manual_controls_reach_runtime(self):
        cmd = self.command(Options(temporal_frames=4, carry_quality=.65, cutout_linear=True))
        self.assertEqual(cmd[cmd.index('--hann_chunk')+1], '4')
        self.assertEqual(cmd[cmd.index('--hann_stride')+1], '2')
        self.assertEqual(cmd[cmd.index('--carry_hint_quality')+1], '0.65')
        self.assertIn('--cutout_linear', cmd)
        cmd = self.command(Options(temporal_frames=1, memory='low'))
        self.assertEqual(cmd[cmd.index('--hann_chunk')+1], '1')
        self.assertEqual(cmd[cmd.index('--hann_stride')+1], '1')


class Desktop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QSettings
        cls.app = QApplication.instance() or QApplication([])
        cls.settings_dir = tempfile.TemporaryDirectory(prefix='ck2-test-settings-')
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cls.settings_dir.name)
        QSettings.setDefaultFormat(QSettings.IniFormat)

    @classmethod
    def tearDownClass(cls):
        cls.settings_dir.cleanup()

    def setUp(self):
        from linux_app import Window
        from PySide6.QtCore import QSettings
        self.window = Window(QSettings(str(Path(self.settings_dir.name)/'settings.ini'), QSettings.IniFormat))
        self.window.auto_preview.setChecked(False)
        self.addCleanup(self.window.close)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clip = Path(self.temp.name) / 'test.mp4'
        self.clip.touch()
        self.window.add_paths([str(self.clip)])

    def test_requeue_terminal_clips_preserves_hints_and_completed_results(self):
        from PySide6.QtCore import Qt
        w = self.window
        w.add_paths([self.clip, self.clip])
        snapshots = []
        for index, state in enumerate(('Done', 'Failed', 'Cancelled')):
            item = w.queue.item(index)
            data = item.data(Qt.UserRole)
            data.update(state=state, output='/previous/output', job_dir='/previous/job',
                        passes={'alpha': '/previous/alpha'},
                        hint_settings={'hint_path': '/saved/hint.png', 'hint_mode': 'first', 'hint_quality': .6})
            item.setData(Qt.UserRole, data)
            snapshots.append(dict(data, state='Queued'))
            item.setSelected(True)
        w.sync_render_queue()
        self.assertTrue(w.requeue_button.isEnabled())
        w.requeue_button.click()
        self.assertEqual(w.queue.count(), 3)
        for index, expected in enumerate(snapshots):
            self.assertEqual(w.queue.item(index).data(Qt.UserRole), expected)
            self.assertIn('Queued', w.render_queue.item(index).text())
        self.assertFalse(w.requeue_button.isEnabled())
        w.requeue_selected()
        self.assertEqual(w.queue.count(), 3)

    def test_requeue_only_selected_terminal_items_and_blocks_active_queue(self):
        from PySide6.QtCore import Qt
        w = self.window
        w.add_paths([self.clip])
        first, second = w.queue.item(0), w.queue.item(1)
        for item in (first, second):
            data = item.data(Qt.UserRole); data['state'] = 'Failed'; item.setData(Qt.UserRole, data)
        w.select_queue_entry(w.render_queue.item(0))
        w.set_busy(True)
        w.requeue_selected()
        self.assertEqual(first.data(Qt.UserRole)['state'], 'Failed')
        self.assertFalse(w.requeue_button.isEnabled())
        w.set_busy(False)
        w.jobs = [('pending',)]
        w.requeue_selected()
        self.assertEqual(first.data(Qt.UserRole)['state'], 'Failed')
        w.jobs.clear(); w.update_requeue_action()
        w.requeue_selected()
        self.assertEqual(first.data(Qt.UserRole)['state'], 'Queued')
        self.assertEqual(second.data(Qt.UserRole)['state'], 'Failed')

    def test_requeued_clip_uses_current_options_and_preserves_prior_version(self):
        from PySide6.QtCore import Qt
        from unittest.mock import patch
        from linux_export import plan_export
        w = self.window
        base = Path(self.temp.name) / 'renders'; previous = base / 'test_fg_v001'
        previous.mkdir(parents=True); (previous/'keep.mp4').write_bytes(b'old result')
        item = w.queue.currentItem(); data = item.data(Qt.UserRole)
        data.update(state='Done', output=str(base), passes={'fg':str(previous)})
        item.setData(Qt.UserRole, data)
        hint = Path(self.temp.name)/'hint.png'; hint.touch()
        w.hint.setText(str(hint)); w.hint_mode.setCurrentIndex(w.hint_mode.findData('first'))
        w.save_sibling.setChecked(False); w.destination.setText(str(base)); w.fps.setValue(30)
        for key, checkbox in w.channels.items():checkbox.setChecked(key == 'alpha')
        w.requeue_selected()
        with patch.object(w, 'check_installation') as check:
            w.start_queue(); check.assert_called_once()
        self.assertEqual(len(w.jobs), 1)
        queued_item, options, destination = w.jobs[0]
        self.assertIs(queued_item, item)
        self.assertEqual(options.outputs, ('alpha',)); self.assertEqual(options.fps, 30)
        self.assertEqual(options.hint_path, str(hint)); self.assertEqual(options.hint_mode, 'first')
        self.assertEqual(plan_export(self.clip, destination, options.outputs).version, 2)
        self.assertEqual((previous/'keep.mp4').read_bytes(), b'old result')

    def test_preflight_failure_preserves_pending_items(self):
        from PySide6.QtCore import Qt, QProcess
        self.window.jobs = [('placeholder',)]
        self.window.checking = True
        self.window.finished(1, QProcess.NormalExit)
        self.assertEqual(self.window.jobs, [])
        self.assertEqual(self.window.queue.item(0).data(Qt.UserRole)['state'], 'Queued')
        self.assertTrue(self.window.start_button.isEnabled())

    def test_failure_and_cancel_statuses(self):
        from PySide6.QtCore import Qt, QProcess
        self.window.active = self.window.queue.item(0)
        self.window.finished(1, QProcess.NormalExit)
        self.assertEqual(self.window.active.data(Qt.UserRole)['state'], 'Failed')
        self.window.stopping = True
        self.window.finished(0, QProcess.NormalExit)
        self.assertEqual(self.window.active.data(Qt.UserRole)['state'], 'Cancelled')
        self.app.processEvents()

    def wait_for(self, condition):
        deadline = time.monotonic()+8
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.02)
        self.assertTrue(condition())

    def test_scrubbing_and_source_switch_discard_stale_frames(self):
        from PySide6.QtGui import QImage, QColor
        directory = Path(self.temp.name) / 'sequence'
        directory.mkdir()
        for index, color in enumerate(('red', 'blue')):
            image = QImage(64, 32, QImage.Format_RGB32)
            image.fill(QColor(color))
            image.save(str(directory / f'{index:04d}.png'))
        viewer = self.window.viewer
        viewer.set_source(directory)
        self.wait_for(lambda: not viewer.canvas.pixmap.isNull())
        self.assertEqual(viewer.slider.maximum(), 1)
        viewer.slider.setValue(1)
        self.wait_for(lambda: viewer.canvas.pixmap.toImage().pixelColor(10, 10).blue() > 240)
        viewer.slider.setValue(0)
        viewer.set_source(None)
        self.app.processEvents()
        self.assertTrue(viewer.canvas.pixmap.isNull())
        self.assertFalse(viewer.slider.isEnabled())

    def test_channel_selection_uses_completed_outputs(self):
        from PySide6.QtCore import Qt
        from unittest.mock import patch
        output = Path(self.temp.name) / 'render'
        output.mkdir()
        # A source name containing alpha must not confuse foreground selection.
        (output / 'shot_alpha_fg.mp4').touch()
        expected = output / 'shot_alpha_alpha.mp4'
        expected.touch()
        item = self.window.queue.item(0)
        data = item.data(Qt.UserRole)
        data.update(state='Done', output=str(output))
        item.setData(Qt.UserRole, data)
        with patch.object(self.window.viewer, 'set_source') as load:
            self.window.view_mode.setCurrentIndex(self.window.view_mode.findData('alpha'))
            self.assertEqual(load.call_args.args[0], expected)

    def test_preview_discards_stale_results_and_runs_latest_request(self):
        import json
        from unittest.mock import patch
        from PySide6.QtCore import QProcess
        from linux_preview import AutoPreview
        engine = AutoPreview(Path(self.temp.name))
        self.addCleanup(engine.close)
        published = []
        engine.result.connect(published.append)
        engine.ready = True
        with patch.object(engine.process, 'state', return_value=QProcess.Running), \
             patch.object(engine.process, 'write') as write:
            engine.request(self.clip, 0, 24, Options())
            engine.timer.stop()
            engine.dispatch()
            old = json.loads(write.call_args.args[0])
            engine.request(self.clip, 1, 24, Options())
            engine.request(self.clip, 2, 24, Options(despill=.8))
            engine.timer.stop()
            with patch.object(engine.process, 'readAllStandardOutput', return_value=(json.dumps({'id': old['id'], 'images': {'alpha': 'old'}})+'\n').encode()):
                engine.read()
            self.assertEqual(published, [])
            engine.timer.stop()
            engine.dispatch()
            latest = json.loads(write.call_args.args[0])
            self.assertEqual(latest['frame'], 2)
            self.assertEqual(latest['options']['despill'], .8)
            with patch.object(engine.process, 'readAllStandardOutput', return_value=(json.dumps({'id': latest['id'], 'images': {'alpha': 'new'}})+'\n').encode()):
                engine.read()
            self.assertEqual(published, [{'alpha': 'new'}])

    def test_media_thumbnails_filmstrip_and_queue_navigation(self):
        from PySide6.QtGui import QImage, QColor
        from PySide6.QtCore import Qt, QPoint
        from PySide6.QtTest import QTest
        directory = Path(self.temp.name) / 'frames'
        directory.mkdir()
        for index, color in enumerate(('red', 'blue')):
            image = QImage(64, 32, QImage.Format_RGB32)
            image.fill(QColor(color))
            image.save(str(directory / f'{index:04d}.png'))
        self.window.view_mode.setCurrentIndex(0)
        self.window.add_paths([directory])
        self.window.queue.setCurrentRow(1)
        self.wait_for(lambda: not self.window.queue.item(1).icon().isNull())
        strip = self.window.viewer.filmstrip
        self.wait_for(lambda: len(strip.thumbs) == 10)
        QTest.mouseClick(strip, Qt.LeftButton, pos=QPoint(strip.width()-1, 20))
        self.assertEqual(self.window.viewer.slider.value(), 1)
        self.assertEqual(self.window.render_queue.count(), 2)
        self.window.select_queue_entry(self.window.render_queue.item(0))
        self.assertEqual(self.window.queue.currentRow(), 0)
        self.window.remove_selected()
        self.assertEqual(self.window.render_queue.count(), 1)


if __name__ == '__main__':
    unittest.main()
