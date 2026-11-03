#!/usr/bin/env python3
"""Linux desktop front end for the CorridorKey 2.0 inference CLI."""
from __future__ import annotations

import os
import json
import uuid
from pathlib import Path
from dataclasses import replace, asdict
import shlex
import shutil
import signal
import sys

from PySide6.QtCore import QProcess, QSettings, QTimer, QUrl, Qt, QSignalBlocker
from PySide6.QtGui import QDesktopServices, QPixmap, QIcon
from PySide6.QtWidgets import (
    QApplication, QDoubleSpinBox, QFileDialog, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton,
)

from worker_process import start_worker, signal_tree
from runtime_support import configure

from linux_jobs import Options, build_command, new_destination, validate_source

ROOT = Path(__file__).resolve().parent


class Window(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.setWindowTitle('CorridorKey 2.0 • ' + ('Windows' if os.name == 'nt' else 'Linux'))
        self.resize(1200, 850)
        self.setAcceptDrops(True)
        self.settings = settings if settings is not None else QSettings('CorridorKeyLocal', 'LinuxDesktop')
        self.jobs = []
        self.active = None
        self.stopping = False
        self._queue_busy = False
        self.checking = False
        self.log_file = None
        self._closing = False
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.setWorkingDirectory(str(ROOT))
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        from linux_ui import build_ui
        build_ui(self, ROOT)
        from linux_media import Thumbnails
        self.media_thumbnails = Thumbnails(self)
        self.media_thumbnails.ready.connect(self.media_thumbnail_ready)
        from linux_preview import AutoPreview
        self.preview_engine = AutoPreview(ROOT, self)
        self.preview_images = {}
        self.preview_engine.result.connect(self.preview_ready)
        self.preview_engine.status.connect(self.preview_status)
        self.preview_engine.cacheStatus.connect(self.cache_state.setText)
        self.save_sibling.toggled.connect(self.sibling_changed)
        self.destination.textChanged.connect(self.update_output_preview)
        self.format.currentIndexChanged.connect(self.update_output_preview)
        for checkbox in self.channels.values():checkbox.toggled.connect(self.update_output_preview)
        self.sibling_changed()
        self.input_space.currentIndexChanged.connect(self.input_color_changed)
        self.viewer.frameRequested.connect(self.schedule_preview)
        self.auto_preview.toggled.connect(self.toggle_auto_preview)
        for widget in (self.despill, self.quality, self.carry_quality, self.fps):
            widget.valueChanged.connect(self.schedule_preview)
        for widget in (self.hint_mode, self.memory, self.resolution, self.alpha_mode):
            widget.currentIndexChanged.connect(self.schedule_preview)
        self.keep_original.toggled.connect(self.schedule_preview)
        self.hint.textChanged.connect(self.store_hint_settings)
        self.hint_mode.currentIndexChanged.connect(self.store_hint_settings)
        self.quality.valueChanged.connect(self.store_hint_settings)
        self.hint.textChanged.connect(self.schedule_preview)
        self.linear.toggled.connect(self.input_color_changed)
        self.view_mode.setCurrentIndex(self.view_mode.findData('checker'))
        from updates_ui import Updates
        self.updates = Updates(self)
        self.gpu_probe = QProcess(self)
        self.gpu_probe.finished.connect(self.gpu_updated)
        self.gpu_probe.errorOccurred.connect(lambda _: self.gpu_memory.setText('Unavailable'))
        self.gpu_timer = QTimer(self)
        self.gpu_timer.setInterval(5000)
        self.gpu_timer.timeout.connect(self.poll_gpu)
        self.gpu_timer.start()
        self.gpu_timeout = QTimer(self)
        self.gpu_timeout.setSingleShot(True)
        self.gpu_timeout.setInterval(3000)
        self.gpu_timeout.timeout.connect(self.gpu_probe.kill)
        QTimer.singleShot(0, self.poll_gpu)

    @staticmethod
    def button(layout, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    @staticmethod
    def decimal(value, minimum, maximum, step):
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setValue(value)
        return spin

    def open_updates(self):
        self.updates.show()

    def add_paths(self, paths):
        for path in paths:
            try:
                path = validate_source(path)
            except ValueError as exc:
                self.log.appendPlainText(str(exc))
                continue
            item = QListWidgetItem(f'Queued • {path.name}')
            item.setData(Qt.UserRole, {'source': str(path), 'state': 'Queued', 'output': ''})
            item.setToolTip(str(path))
            self.queue.addItem(item)
            self.media_thumbnails.add(str(path), path)
            if self.queue.count() == 1:
                self.queue.setCurrentItem(item)
        self.sync_render_queue()

    def media_thumbnail_ready(self, source, image):
        for index in range(self.queue.count()):
            item = self.queue.item(index)
            if item.data(Qt.UserRole)['source'] == source:
                item.setIcon(QIcon(image))
        self.sync_render_queue()

    def sync_render_queue(self):
        self.render_queue.clear()
        for index in range(self.queue.count()):
            item = self.queue.item(index)
            data = item.data(Qt.UserRole)
            entry = QListWidgetItem(item.icon(), f'{Path(data["source"]).name}\n{data["state"]}')
            entry.setData(Qt.UserRole, index)
            entry.setToolTip(data['output'] or data['source'])
            self.render_queue.addItem(entry)
        self.queue_heading.setText(f'Q U E U E  {self.queue.count()}')
        self.update_requeue_action()

    def select_queue_entry(self, entry):
        self.queue.setCurrentRow(entry.data(Qt.UserRole))

    def add_clips(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Add clips', '', 'Videos (*.mp4 *.mov *.mkv *.avi *.webm *.mxf *.m4v);;All files (*)')
        self.add_paths(paths)

    def add_folder(self):
        path = QFileDialog.getExistingDirectory(self, 'Choose image sequence folder')
        if path:
            self.add_paths([path])

    def remove_selected(self):
        if self.process.state() != QProcess.NotRunning or self.jobs:
            return
        for item in self.queue.selectedItems():
            self.queue.takeItem(self.queue.row(item))
        self.sync_render_queue()

    def requeue_candidates(self):
        if self._queue_busy or self.process.state() != QProcess.NotRunning or self.jobs:
            return []
        return [item for item in self.queue.selectedItems()
                if item.data(Qt.UserRole)['state'] in ('Done', 'Failed', 'Cancelled')]

    def update_requeue_action(self):
        self.requeue_button.setEnabled(bool(self.requeue_candidates()))

    def requeue_selected(self):
        items = self.requeue_candidates()
        if not items:
            return
        for item in items:
            data = item.data(Qt.UserRole)
            data['state'] = 'Queued'
            item.setData(Qt.UserRole, data)
            item.setText(f'Queued • {Path(data["source"]).name}')
        self.sync_render_queue()
        self.update_output_preview()
        self.status.setText(f'Requeued {len(items)} clip(s). Click Render queue to use current settings and a new output version.')

    def queue_context_menu(self, view, position):
        item = view.itemAt(position)
        if item is None:
            return
        if view is self.render_queue:
            self.select_queue_entry(item)
        elif not item.isSelected():
            self.queue.setCurrentItem(item)
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        action = menu.addAction('Requeue selected')
        action.setEnabled(bool(self.requeue_candidates()))
        action.triggered.connect(self.requeue_selected)
        menu.exec(view.viewport().mapToGlobal(position))
        menu.deleteLater()

    def sibling_changed(self, *args):
        enabled = not self.save_sibling.isChecked()
        self.destination.setEnabled(enabled)
        self.destination_button.setEnabled(enabled)
        self.settings.setValue('save_sibling', self.save_sibling.isChecked())
        self.update_output_preview()

    def update_output_preview(self, *args):
        from linux_export import plan_export
        item = self.queue.currentItem()
        if item is None:
            self.output_preview.clear();return
        try:
            plan = plan_export(item.data(Qt.UserRole)['source'], self.destination.text(),
                               [key for key,check in self.channels.items() if check.isChecked()],
                               sibling=self.save_sibling.isChecked(),output_format=self.format.currentData())
            self.output_preview.setPlainText('\n'.join(plan.preview))
            self.output_preview.setToolTip('Version is reserved when this clip starts rendering.\n'+'\n'.join(plan.preview))
        except (OSError,ValueError) as exc:
            self.output_preview.setPlainText(str(exc))

    def choose_destination(self):
        path = QFileDialog.getExistingDirectory(self, 'Output folder', self.destination.text())
        if path:
            self.destination.setText(path)

    def choose_hint(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose hint matte or video')
        if path:
            self.hint.setText(path)

    def choose_hint_folder(self):
        path = QFileDialog.getExistingDirectory(self, 'Choose hint frame sequence')
        if path:
            self.hint.setText(path)

    def store_hint_settings(self, *args):
        item = self.queue.currentItem()
        if item is not None:
            data = item.data(Qt.UserRole)
            data['hint_settings'] = dict(hint_path=self.hint.text(), hint_mode=self.hint_mode.currentData(),
                                         hint_quality=self.quality.value())
            item.setData(Qt.UserRole, data)

    def create_hint(self):
        item = self.queue.currentItem()
        if item is None:
            self.status.setText('Select a clip before creating a hint.')
            return
        if not self.start_button.isEnabled():
            self.status.setText('Finish or stop the render before editing a hint.')
            return
        from dataclasses import asdict
        from preview_cache import signature
        from linux_hint_editor import HintEditor
        source = item.data(Qt.UserRole)['source']
        seed = self.hint.text() if self.hint_mode.currentData() == 'first' else ''
        if not seed:
            stamp = signature(source, self.viewer.fps, asdict(self.options()))
            cached = self.preview_engine.frames.get((stamp, 0))
            if cached:
                seed = cached.get('alpha', '')
        self.viewer.play.setChecked(False)
        self.preview_engine.stop()
        self.preview_engine.suspended = True
        editor = HintEditor(ROOT, source, self.settings, linear=self.linear.isChecked(),
                            color_space=self.input_space.currentData(), seed=seed, parent=self)
        try:
            if editor.exec() and editor.saved_path:
                # Set both hint fields together before saving clip settings.
                blockers = [QSignalBlocker(self.hint), QSignalBlocker(self.hint_mode)]
                self.hint.setText(editor.saved_path)
                self.hint_mode.setCurrentIndex(self.hint_mode.findData('first'))
                del blockers
                self.store_hint_settings()
                self.viewer.slider.setValue(0)
                self.status.setText('Frame-one hint saved and attached to '+Path(source).name)
        finally:
            editor.stop_worker()
            editor.deleteLater()
            self.preview_engine.suspended = False
            self.preview_images = {}
            self.schedule_preview()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_paths([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()

    def selection_changed(self, item, previous=None):
        values = item.data(Qt.UserRole).get('hint_settings', {}) if item else {}
        blockers = [QSignalBlocker(self.hint), QSignalBlocker(self.hint_mode), QSignalBlocker(self.quality)]
        self.hint.setText(values.get('hint_path', ''))
        self.hint_mode.setCurrentIndex(self.hint_mode.findData(values.get('hint_mode', 'none')))
        self.quality.setValue(values.get('hint_quality', .75))
        del blockers
        self.clip_title.setText(Path(item.data(Qt.UserRole)['source']).name if item else 'No clip selected')
        self.update_output_preview()
        self.preview_images = {}
        self.preview_engine.cancel_prefetch()
        self.preview_engine.invalidate()
        self.refresh_viewer()

    def refresh_viewer(self):
        item = self.queue.currentItem()
        key = self.view_mode.currentData()
        source = None
        render_settings = ''
        self.viewer.input_premultiplied = False
        self.viewer.numbered_frames = False
        if self.auto_preview.isChecked() and key != 'original' and item:
            source = Path(item.data(Qt.UserRole)['source'])
            if not self.viewer.external_preview or self.viewer.source != source:
                self.viewer.external_preview = True
                self.viewer.set_source(source, self.fps.value(), 'Live key')
            elif self.preview_images:
                self.preview_ready(self.preview_images)
            else:
                self.schedule_preview()
            return
        self.preview_engine.invalidate()
        self.viewer.external_preview = False
        if item:
            data = item.data(Qt.UserRole)
            if key == 'original':
                source = data['source']
            elif data['state'] == 'Done' and data['output']:
                folder = Path(data['output'])
                pass_path = data.get('passes', {}).get(key)
                suffix = 'checker_comp_despill[0-9][0-9][0-9]' if key == 'checker' else key
                if pass_path:
                    self.viewer.numbered_frames = True
                    path = Path(pass_path)
                    candidates = [path] if any(path.glob('*.exr')) else sorted(list(path.glob('*.mp4'))+list(path.glob('*.mov')))
                elif data.get('job_dir'):
                    candidates = []
                else:
                    candidates = sorted(p for ending in ('.mp4', '.mov', '_exr')
                                        for p in folder.glob(f'*_{suffix}{ending}'))
                if candidates:
                    source = candidates[0]
                    settings_files = list((Path(data['job_dir'])/'render').glob('*_settings.txt')) if data.get('job_dir') else list(folder.glob('*_settings.txt'))
                    if settings_files:
                        render_settings = settings_files[0].read_text()
                    self.viewer.input_premultiplied = key == 'cutout' and 'Cutout Alpha: premultiplied' in render_settings
        self.viewer.input_color_space = self.input_space.currentData() if key == 'original' else 'rec709'
        self.viewer.input_linear = self.linear.isChecked() if key == 'original' else key != 'alpha'
        if source and Path(source).is_file():
            self.viewer.input_linear = key == 'cutout' and 'Cutout Linear: True' in render_settings
        self.viewer.set_source(source, self.fps.value(), self.view_mode.currentText())
        self.view_note.setText('Input' if key == 'original' else 'Last completed render • changes require rendering')

    def input_color_changed(self):
        aces = self.input_space.currentData() == 'acescg'
        if aces:
            self.linear.setChecked(True)
        self.linear.setEnabled(not aces)
        if self.view_mode.currentData() == 'original':
            self.refresh_viewer()
        else:
            self.schedule_preview()

    def cache_selected_clip(self):
        if self.preview_engine.background:
            self.preview_engine.cancel_prefetch()
            return
        item = self.queue.currentItem()
        if not item or not self.start_button.isEnabled():
            return
        if not self.viewer.external_preview or not self.viewer.slider.isEnabled():
            self.cache_state.setText('Enable Auto key and select Composite, then cache the clip.')
            return
        self.preview_engine.cache_clip(item.data(Qt.UserRole)['source'], self.viewer.slider.maximum()+1,
                                       self.viewer.fps, self.options())

    def clear_preview_cache(self):
        self.preview_engine.clear_cache()
        self.preview_engine.suspended = not self.start_button.isEnabled()
        self.preview_images = {}
        self.schedule_preview()

    def toggle_auto_preview(self, enabled):
        if not enabled:
            self.preview_engine.stop()
        else:
            self.preview_engine.suspended = not self.start_button.isEnabled()
        self.preview_images = {}
        self.refresh_viewer()

    def schedule_preview(self, *args):
        if self._closing or not self.auto_preview.isChecked() or self.view_mode.currentData() == 'original':
            return
        item = self.queue.currentItem()
        if not item or not self.start_button.isEnabled():
            return
        self.preview_images = {}
        self.viewer.external_pending = True
        self.viewer.canvas.clear('Keying preview…')
        self.preview_engine.request(item.data(Qt.UserRole)['source'], self.viewer.slider.value(),
                                    self.viewer.fps, self.options())

    def preview_ready(self, images):
        self.viewer.external_pending = False
        self.preview_images = images
        path = images.get(self.view_mode.currentData())
        if path and self.auto_preview.isChecked() and self.viewer.external_preview:
            if not Path(path).is_file():
                self.preview_images = {}
                self.schedule_preview()
                return
            self.viewer.canvas.pixmap = QPixmap(path)
            self.viewer.canvas.update()

    def preview_status(self, message):
        if message.startswith('Live key') and self.hint_mode.currentData() == 'first' and self.viewer.slider.value() > 0:
            message += ' • first-frame hint propagation requires rendering'
        self.view_note.setText(message)
        if 'failed' in message.lower() or 'stopped' in message.lower():
            self.viewer.external_pending = False
            self.viewer.play.setChecked(False)
            self.viewer.canvas.clear('Preview unavailable — see processing log')
            self.log.appendPlainText(message)

    def open_manual(self):
        QDesktopServices.openUrl(QUrl('https://help.corridorkey.com/docs/manual/'))

    def poll_gpu(self):
        if self._closing:
            return
        if self.gpu_probe.state() == QProcess.NotRunning:
            self.gpu_probe.start('nvidia-smi', ['--query-gpu=name,memory.free,memory.total', '--format=csv,noheader,nounits'])
            self.gpu_timeout.start()

    def gpu_updated(self, code, status):
        self.gpu_timeout.stop()
        try:
            line = bytes(self.gpu_probe.readAllStandardOutput()).decode().splitlines()[0]
            name, free, total = line.rsplit(',', 2)
            self.gpu_name.setText(name.strip())
            self.gpu_memory.setText(f'{float(free)/1024:.1f} / {float(total)/1024:.1f} GB')
        except (ValueError, IndexError):
            self.gpu_memory.setText('Unavailable — check driver')

    def open_input(self):
        item = self.queue.currentItem()
        if item:
            QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.UserRole)['source']))

    def open_results(self):
        item = self.queue.currentItem()
        data = item.data(Qt.UserRole) if item else {}
        path = data.get('passes', {}).get(self.view_mode.currentData()) or data.get('output', '')
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def options(self):
        return Options(outputs=tuple(key for key, check in self.channels.items() if check.isChecked()),
                       output_format=self.format.currentData(), memory=self.memory.currentData(),
                       hint_mode=self.hint_mode.currentData(), hint_path=self.hint.text(),
                       hint_quality=self.quality.value(), carry=self.carry.isChecked(), despill=self.despill.value(),
                       fps=self.fps.value(), linear=self.linear.isChecked(), num_frames=self.frames.value() or -1,
                       temporal_frames=self.temporal.currentData(), carry_quality=self.carry_quality.value(),
                       model_scale=self.resolution.currentData(),
                       cutout_premultiplied=self.alpha_mode.currentData(), keep_original=self.keep_original.isChecked(),
                       cutout_linear=self.cutout_linear.isChecked(), save_sibling=self.save_sibling.isChecked(), input_color_space=self.input_space.currentData())

    def set_busy(self, busy):
        self._queue_busy = busy
        self.update_requeue_action()
        if busy:
            self.preview_engine.stop()
            self.preview_images = {}
            self.viewer.play.setChecked(False)
        else:
            self.preview_engine.suspended = False
        self.start_button.setEnabled(not busy)
        self.check_button.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        self.cache_button.setEnabled(not busy)
        self.create_hint_button.setEnabled(not busy)
        if not busy:
            self.schedule_preview()

    def start_queue(self):
        if self.process.state() != QProcess.NotRunning:
            return
        options = self.options()
        jobs = []
        try:
            if not options.save_sibling and not self.destination.text().strip():
                raise ValueError('Choose an output folder.')
            for index in range(self.queue.count()):
                item = self.queue.item(index)
                if item.data(Qt.UserRole)['state'] != 'Queued':
                    continue
                source = item.data(Qt.UserRole)['source']
                clip_options = options if item == self.queue.currentItem() else replace(options, **item.data(Qt.UserRole).get(
                    'hint_settings', dict(hint_mode='none', hint_path='', hint_quality=.75)))
                from linux_export import plan_export
                plan_export(source, self.destination.text(), clip_options.outputs, sibling=clip_options.save_sibling, output_format=clip_options.output_format)
                build_command(ROOT, sys.executable, source, self.destination.text(), clip_options)
                jobs.append((item, clip_options, str(Path(self.destination.text()).expanduser().resolve()) if self.destination.text().strip() else ''))
        except ValueError as exc:
            QMessageBox.warning(self, 'Check settings', str(exc))
            return
        if not jobs:
            self.status.setText('No queued clips. Select a completed, failed, or cancelled clip and click Requeue selected.')
            return
        self.jobs = jobs
        self.settings.setValue('output', self.destination.text())
        self.check_installation()

    def check_installation(self):
        self.stopping = False
        self.checking = True
        self.set_busy(True)
        self.status.setText('Checking CUDA, dependencies and model files…')
        self.process.start(sys.executable, ['-u', str(ROOT / 'scripts/check_linux.py')])

    def run_next(self):
        if self.stopping or not self.jobs:
            self.jobs.clear()
            self.active = None
            self.set_busy(False)
            self.status.setText('Queue stopped' if self.stopping else 'Queue finished — see each job status')
            return
        item, options, base = self.jobs.pop(0)
        self.active = item
        try:
            data = item.data(Qt.UserRole)
            from linux_export import plan_export, write_json
            job_dir = new_destination(ROOT/'logs/jobs', data['source'])
            plan = plan_export(data['source'], base, options.outputs, sibling=options.save_sibling, output_format=options.output_format)
            data.update(output=plan.parent, job_dir=str(job_dir), passes={})
            item.setData(Qt.UserRole, data)
            manifest = job_dir/'export.json'
            write_json(manifest, dict(id=uuid.uuid4().hex,source=data['source'],base=base,
                                     options=asdict(options),status='queued',passes={}))
            command = [sys.executable, '-u', str(ROOT/'scripts/render_job.py'), str(manifest)]
            self.log_file = (job_dir/'inference.log').open('w')
            self.log_file.write(shlex.join(command) + '\n')
            self.log_file.flush()
            self.mark_active('Running')
            self.status.setText(f'Processing {Path(data["source"]).name}')
            # Each inference job has its own session, including FFmpeg children.
            start_worker(self.process, command)
        except (OSError, ValueError) as exc:
            self.log.appendPlainText(str(exc))
            self.mark_active('Failed')
            self.close_log()
            QTimer.singleShot(0, self.run_next)

    def mark_active(self, state):
        if self.active:
            data = self.active.data(Qt.UserRole)
            data['state'] = state
            self.active.setData(Qt.UserRole, data)
            self.active.setText(f'{state} • {Path(data["source"]).name}')
            self.sync_render_queue()

    def read_output(self):
        if not self.process.isOpen():
            return
        text = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        self.log.appendPlainText(text.rstrip())
        if self.log_file:
            self.log_file.write(text)
            self.log_file.flush()

    def close_log(self):
        if self.log_file:
            self.log_file.close()
            self.log_file = None

    def finished(self, code, status):
        self.read_output()
        if self.checking:
            self.checking = False
            if code != 0 or self.stopping:
                self.jobs.clear()
                self.set_busy(False)
                self.status.setText('Check stopped' if self.stopping else 'Setup needs attention — see log')
                return
            if not self.jobs:
                self.set_busy(False)
                self.status.setText('Installation ready')
                return
        else:
            if self.active is not None:
                data = self.active.data(Qt.UserRole)
                if data.get('job_dir'):
                    from linux_export import release_lock
                    try:
                        manifest = json.loads((Path(data['job_dir'])/'export.json').read_text())
                        release_lock(manifest.get('reservation'),manifest['id'])
                        if code == 0 and manifest.get('status') == 'complete':
                            data['passes'] = manifest['passes']
                            self.active.setData(Qt.UserRole,data)
                        elif code == 0:
                            code = 1
                    except (OSError,ValueError,KeyError) as exc:
                        self.log.appendPlainText('Export receipt error: '+str(exc));code = 1
            self.update_output_preview()
            self.mark_active('Cancelled' if self.stopping else ('Done' if code == 0 else 'Failed'))
            self.close_log()
            if self.active == self.queue.currentItem():
                self.refresh_viewer()
        QTimer.singleShot(0, self.run_next)

    def process_error(self, error):
        if error == QProcess.FailedToStart:
            self.log.appendPlainText(self.process.errorString())
            self.finished(1, QProcess.CrashExit)

    def stop_queue(self):
        self.stopping = True
        self.jobs.clear()
        pid = self.process.processId()
        if pid:
            if self.checking:
                self.process.terminate()
            else:
                self.signal_group(pid, signal.SIGTERM)
            QTimer.singleShot(3000, lambda: self.force_stop(pid))

    @staticmethod
    def signal_group(pid, sig):
        signal_tree(pid, sig)

    def force_stop(self, pid):
        if self.process.processId() == pid and self.process.state() != QProcess.NotRunning:
            if not self.checking:
                self.signal_group(pid, getattr(signal, 'SIGKILL', signal.SIGTERM))
            self.process.kill()

    def closeEvent(self, event):
        if self.process.state() != QProcess.NotRunning:
            QMessageBox.information(self, 'Job running', 'Stop the queue before closing the application.')
            event.ignore()
            return
        self.updates.close()
        self._closing = True
        self.media_thumbnails.close()
        self.preview_engine.close()
        self.viewer.shutdown()
        self.gpu_timer.stop()
        self.gpu_timeout.stop()
        self.gpu_probe.kill()
        self.gpu_probe.waitForFinished(1000)
        event.accept()


def main():
    configure()
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    from contextlib import ExitStack
    from runtime_setup import setup_lock
    resources = ExitStack()
    try:
        resources.enter_context(setup_lock(ROOT, 'application.lock'))
    except RuntimeError as exc:
        QMessageBox.warning(None, 'CK2 is already running or being repaired', str(exc))
        return 1
    with resources:
        window = Window()
        window.add_paths(sys.argv[1:])
        window.show()
        return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
