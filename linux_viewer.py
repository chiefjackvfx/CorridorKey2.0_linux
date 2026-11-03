"""Asynchronous frame viewer. Decoding stays outside the Qt event loop."""
import json
import re
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QProcess, QTimer, QRect, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox


class Canvas(QWidget):
    def __init__(self):
        super().__init__()
        self.pixmap = QPixmap()
        self.message = 'Open a clip to begin'
        self.setMinimumSize(320, 200)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#10100f'))
        if self.pixmap.isNull():
            painter.setPen(QColor('#97968d'))
            painter.drawText(self.rect(), Qt.AlignCenter, self.message)
            return
        size = self.pixmap.size().scaled(self.size(), Qt.KeepAspectRatio)
        rect = QRect((self.width()-size.width())//2, (self.height()-size.height())//2, size.width(), size.height())
        painter.save()
        painter.setClipRect(rect)
        for y in range(rect.top(), rect.bottom()+1, 20):
            for x in range(rect.left(), rect.right()+1, 20):
                alternate = ((x-rect.left())//20 + (y-rect.top())//20) % 2
                painter.fillRect(x, y, 20, 20, QColor('#555550' if alternate else '#383834'))
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(rect, self.pixmap)
        painter.restore()

    def clear(self, message):
        self.pixmap = QPixmap()
        self.message = message
        self.update()


class MediaViewer(QWidget):
    frameRequested = Signal(int)

    def __init__(self):
        super().__init__()
        self.source = None
        self.images = []
        self.fps = 25.0
        self.generation = 0
        self.request = None
        self.pending = False
        self.numbered_frames = False
        self.input_color_space = "rec709"
        self.input_linear = True
        self.input_premultiplied = False
        self.external_preview = False
        self.external_pending = False
        self.canvas = Canvas()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas, 1)
        self.info = QLabel('Original • No media loaded')
        layout.addWidget(self.info)
        controls = QHBoxLayout()
        self.transport = []
        for title, tooltip, callback in (
            ('|◀', 'First frame', lambda: self.slider.setValue(0)),
            ('‹', 'Previous frame', lambda: self.slider.setValue(self.slider.value()-1)),
        ):
            button = QPushButton(title)
            button.setFixedWidth(30)
            button.setToolTip(tooltip)
            button.clicked.connect(callback)
            controls.addWidget(button)
            self.transport.append(button)
        self.play = QPushButton('▶')
        self.play.setFixedWidth(38)
        self.play.setCheckable(True)
        self.play.toggled.connect(self.toggle_play)
        controls.addWidget(self.play)
        for title, tooltip, callback in (
            ('›', 'Next frame', lambda: self.slider.setValue(self.slider.value()+1)),
            ('▶|', 'Last frame', lambda: self.slider.setValue(self.slider.maximum())),
        ):
            button = QPushButton(title)
            button.setFixedWidth(30)
            button.setToolTip(tooltip)
            button.clicked.connect(callback)
            controls.addWidget(button)
            self.transport.append(button)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self.seek)
        controls.addWidget(self.slider, 1)
        self.frame = QSpinBox()
        self.frame.setPrefix('Frame ')
        self.frame.setRange(1, 1)
        self.frame.valueChanged.connect(lambda value: self.slider.setValue(value-1))
        controls.addWidget(self.frame)
        layout.addLayout(controls)
        from linux_media import Filmstrip
        self.filmstrip = Filmstrip(self)
        self.filmstrip.seek.connect(self.slider.setValue)
        self.slider.valueChanged.connect(self.filmstrip.set_position)
        layout.addWidget(self.filmstrip)
        self.probe = QProcess(self)
        self.probe.finished.connect(self.probed)
        self.probe.errorOccurred.connect(lambda _: self.info.setText('Unable to inspect media; check FFprobe.'))
        self.decoder = QProcess(self)
        self.decoder.finished.connect(self.decoded)
        self.decoder.errorOccurred.connect(self.decode_error)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(70)
        self.debounce.timeout.connect(self.decode)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.setInterval(15000)
        self.deadline.timeout.connect(self.decoder.kill)
        self.probe_deadline = QTimer(self)
        self.probe_deadline.setSingleShot(True)
        self.probe_deadline.setInterval(10000)
        self.probe_deadline.timeout.connect(self.probe.kill)
        self.playback = QTimer(self)
        self.playback.timeout.connect(self.advance)
        self.set_controls(False)

    def set_controls(self, enabled):
        for widget in (self.play, self.slider, self.frame, *self.transport):
            widget.setEnabled(enabled)

    def set_source(self, source, fps=25, label='Original'):
        self.play.setChecked(False)
        self.generation += 1
        self.probe.blockSignals(True)
        self.probe.kill()
        self.probe.waitForFinished(1000)
        self.probe.blockSignals(False)
        self.probe_deadline.stop()
        self.source = Path(source) if source else None
        self.images = []
        self.fps = fps
        self.label = label
        self.canvas.clear('Loading…' if source else 'Render this channel to inspect it here')
        self.slider.setRange(0, 0)
        self.frame.setRange(1, 1)
        self.set_controls(False)
        self.filmstrip.set_source(None, 0, fps)
        self.info.setText(f'{label} • {self.source.name if source else "No rendered media"}')
        if not source:
            return
        if self.source.is_dir():
            self.images = sorted(p for p in self.source.iterdir() if p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.exr'})
            if self.numbered_frames:
                self.images.sort(key=lambda path:int(re.search(r'\.(-?\d+)$',path.stem)[1]) if re.search(r'\.(-?\d+)$',path.stem) else 0)
            if self.images:
                self.configure(len(self.images))
            else:
                self.canvas.clear('No frames in this folder')
        else:
            self.probe.start('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-show_entries',
                'stream=width,height,nb_frames,avg_frame_rate,duration:format=duration', '-of', 'json', str(self.source)])
            self.probe_deadline.start()

    def probed(self, code, status):
        self.probe_deadline.stop()
        try:
            data = json.loads(bytes(self.probe.readAllStandardOutput()))
            stream = data['streams'][0]
            numerator, denominator = stream.get('avg_frame_rate', '25/1').split('/')
            self.fps = float(numerator) / float(denominator)
            if self.fps <= 0:
                raise ValueError('Invalid frame rate')
            duration = stream.get('duration', data.get('format', {}).get('duration', 0))
            count = stream.get('nb_frames', 'N/A')
            count = int(count) if count != 'N/A' else round(float(duration)*self.fps)
            self.configure(max(1, count))
        except (ValueError, KeyError, IndexError, ZeroDivisionError):
            self.canvas.clear('Cannot read this media. Check FFmpeg / FFprobe.')

    def configure(self, count):
        self.filmstrip.set_source(self.source, count, self.fps, self.images if self.numbered_frames else None)
        self.slider.setRange(0, count-1)
        self.frame.setRange(1, count)
        self.set_controls(True)
        self.info.setText(f'{self.label} • {self.source.name} • {count} frames • {self.fps:g} fps')
        self.seek(0)

    def seek(self, index):
        self.frame.blockSignals(True)
        self.frame.setValue(index+1)
        self.frame.blockSignals(False)
        if self.external_preview:
            self.external_pending = True
            self.frameRequested.emit(index)
            return
        self.pending = True
        self.debounce.start()

    def decode(self):
        if self.external_preview or not self.source or self.decoder.state() != QProcess.NotRunning:
            return
        self.pending = False
        index = self.slider.value()
        self.request = (self.generation, index)
        path = self.images[index] if self.images else self.source
        if (self.images and self.input_color_space == 'acescg') or self.input_linear or self.input_premultiplied:
            args = [str(Path(__file__).resolve().parent/'scripts/display_frame.py'),
                    str(path), self.input_color_space, '1' if self.input_linear else '0',
                    '1' if self.input_premultiplied else '0']
            if not self.images:
                args.append(str(index/self.fps))
            self.decoder.start(sys.executable, args)
            self.deadline.start()
            return
        args = ['-v', 'error']
        if not self.images:
            args += ['-ss', str(index/self.fps)]
        filters = 'scale=1280:720:force_original_aspect_ratio=decrease'
        args += ['-i', str(path), '-frames:v', '1', '-vf', filters,
                 '-f', 'image2pipe', '-vcodec', 'png', '-threads', '1', 'pipe:1']
        self.decoder.start('ffmpeg', args)
        self.deadline.start()

    def decoded(self, code, status):
        self.deadline.stop()
        content = bytes(self.decoder.readAllStandardOutput())
        if not self.external_preview and self.request == (self.generation, self.slider.value()):
            pixmap = QPixmap()
            if code == 0 and pixmap.loadFromData(content, 'PNG'):
                self.canvas.pixmap = pixmap
                self.canvas.update()
            else:
                self.canvas.clear('Frame preview unavailable')
                self.play.setChecked(False)
        if self.pending:
            self.debounce.start()

    def decode_error(self, error):
        if error == QProcess.FailedToStart:
            self.deadline.stop()
            self.canvas.clear('FFmpeg could not start')
            self.play.setChecked(False)

    def toggle_play(self, playing):
        self.play.setText('Ⅱ' if playing else '▶')
        if playing:
            self.playback.start(max(16, round(1000/self.fps)))
        else:
            self.playback.stop()

    def advance(self):
        if self.external_preview and self.external_pending:
            return
        if self.decoder.state() != QProcess.NotRunning or self.debounce.isActive():
            return
        if self.slider.value() == self.slider.maximum():
            self.play.setChecked(False)
        else:
            self.slider.setValue(self.slider.value()+1)

    def shutdown(self):
        self.filmstrip.loader.close()
        for timer in (self.debounce, self.deadline, self.probe_deadline, self.playback):
            timer.stop()
        for process in (self.decoder, self.probe):
            process.blockSignals(True)
            process.kill()
            process.waitForFinished(1000)
