"""One persistent GPU worker, one running request, and one latest pending request."""
from app_cache import cache_directory
from worker_process import start_worker, signal_tree
from dataclasses import asdict
from collections import deque
import uuid
from preview_cache import PreviewCache, signature
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile
from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class AutoPreview(QObject):
    result = Signal(dict)
    status = Signal(str)
    cacheStatus = Signal(str)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.cache = tempfile.TemporaryDirectory(prefix='ck2-preview-', dir=cache_directory('previews', root))
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(root))
        self.process.readyReadStandardOutput.connect(self.read)
        self.process.readyReadStandardError.connect(self.drain_errors)
        self.process.finished.connect(self.exited)
        self.process.errorOccurred.connect(self.failed)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.dispatch)
        self.ready = False
        self.busy = False
        self.pending = None
        self.revision = 0
        self.buffer = b''
        self.errors = ''
        self.suspended = False
        self.running_dir = None
        self.display_dir = None
        self.frames = PreviewCache()
        self.background = deque()
        self.background_signature = None
        self.background_total = 0
        self.background_done = 0
        self.running_request = None

    def request(self, source, frame, fps, options):
        self.revision += 1
        values = asdict(options)
        stamp = signature(source, fps, values)
        if self.background_signature and self.background_signature != stamp:
            self.cancel_prefetch()
        self.pending = dict(id=self.revision, source=str(source), frame=frame, fps=fps,
                            options=values, cache_key=(stamp, frame))
        cached = self.frames.get((stamp, frame))
        if cached:
            self.pending = None
            self.result.emit(cached)
            self.status.emit('Cached key • single-frame preview')
            return
        self.status.emit('Keying preview…')
        self.timer.start(350)

    def cache_clip(self, source, count, fps, options):
        self.cancel_prefetch()
        values = asdict(options)
        stamp = signature(source, fps, values)
        self.background_signature = stamp
        self.background_total = count
        self.background_done = 0
        for frame in range(count):
            if self.frames.get((stamp, frame)):
                self.background_done += 1
            else:
                self.background.append(dict(id=-(frame+1), source=str(source), frame=frame,
                    fps=fps, options=values, cache_key=(stamp, frame)))
        self.update_cache_status()
        self.timer.start()

    def cancel_prefetch(self):
        self.background.clear()
        self.background_signature = None
        self.cacheStatus.emit(f'Preview cache: {len(self.frames.entries)} frames • {self.frames.size/1024**2:.0f} MB / 2 GB')

    def update_cache_status(self):
        retained = sum(key[0] == self.background_signature for key in self.frames.entries)
        self.cacheStatus.emit(f'Cache {self.background_done}/{self.background_total} • {retained} retained')

    def clear_cache(self):
        self.stop()
        self.frames.clear()
        self.cacheStatus.emit('Cache cleared')

    def invalidate(self):
        self.revision += 1
        self.pending = None
        self.timer.stop()

    def dispatch(self):
        if self.suspended or not (self.pending or self.background):
            return
        if self.process.state() == QProcess.NotRunning:
            self.ready = False
            self.errors = ''
            self.buffer = b''
            self.status.emit('Loading preview model…')
            start_worker(self.process, [sys.executable, '-u', str(self.root/'scripts/preview_worker.py')])
            return
        if self.busy or not self.ready:
            return
        request = self.pending if self.pending else self.background.popleft()
        self.pending = None
        self.running_request = request
        self.running_dir = Path(self.cache.name) / uuid.uuid4().hex
        self.running_dir.mkdir()
        request['work'] = str(self.running_dir)
        self.busy = True
        if request['id'] > 0:
            self.status.emit('Keying preview…')
        self.process.write((json.dumps(request)+'\n').encode())

    def read(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                response = json.loads(line)
            except ValueError:
                continue
            if response.get('ready'):
                self.ready = True
                self.dispatch()
                continue
            self.busy = False
            saved = False
            if 'images' in response and self.running_request:
                saved = self.frames.put(tuple(self.running_request['cache_key']), response['images'], self.running_dir)
                if not self.background_signature:
                    self.cacheStatus.emit(f'Preview cache: {len(self.frames.entries)} frames • {self.frames.size/1024**2:.0f} MB / 2 GB')
            if response.get('id') == self.revision:
                if 'error' in response:
                    self.status.emit('Preview failed: ' + response['error'])
                else:
                    self.display_dir = self.running_dir
                    self.result.emit(response['images'])
                    self.status.emit('Live key • single-frame preview')
            if self.running_request and self.running_request['id'] < 0:
                if 'error' in response:
                    self.status.emit('Preview failed while caching: ' + response['error'])
                    self.cancel_prefetch()
                elif self.background_signature == self.running_request['cache_key'][0]:
                    self.background_done += 1
                    self.update_cache_status()
            if not saved and self.running_dir != self.display_dir and self.running_dir:
                shutil.rmtree(self.running_dir, ignore_errors=True)
            self.running_dir = None
            self.running_request = None
            if self.pending or self.background:
                self.timer.start(0 if not self.pending else 350)

    def drain_errors(self):
        self.errors = (self.errors + bytes(self.process.readAllStandardError()).decode(errors='replace'))[-6000:]

    def exited(self, code, status):
        self.drain_errors()
        self.ready = self.busy = False
        if not self.suspended:
            self.status.emit('Preview worker stopped. ' + (self.errors.strip().splitlines()[-1] if self.errors.strip() else 'Check installation.'))
        self.pending = None

    def failed(self, error):
        if error == QProcess.FailedToStart:
            self.status.emit('Preview could not start: ' + self.process.errorString())

    def stop(self):
        self.suspended = True
        self.cancel_prefetch()
        self.invalidate()
        pid = self.process.processId()
        if pid:
            signal_tree(pid, getattr(signal, 'SIGKILL', signal.SIGTERM))
            self.process.waitForFinished(5000)
        self.ready = self.busy = False
        self.buffer = b''
        if self.running_dir:
            shutil.rmtree(self.running_dir, ignore_errors=True)
        self.running_dir = None
        self.running_request = None
        self.display_dir = None

    def close(self):
        self.stop()
        self.frames.clear()
        self.cache.cleanup()
