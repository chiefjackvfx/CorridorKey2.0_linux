"""Media cards and a clickable filmstrip backed by real, asynchronous thumbnails."""
from pathlib import Path
from collections import deque
from PySide6.QtCore import QObject, QProcess, QTimer, Qt, Signal, QSize, QRect
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QStyledItemDelegate, QStyle


class Thumbnails(QObject):
    ready = Signal(object, QPixmap)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tasks = deque()
        self.current = None
        self.closed = False
        self.process = QProcess(self)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.failed)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(10000)
        self.timeout.timeout.connect(self.process.kill)

    def add(self, token, source, frame=0, fps=25):
        self.tasks.append((token, Path(source), frame, fps))
        self.next()

    def next(self):
        if self.closed or self.current is not None or not self.tasks:
            return
        self.current = self.tasks.popleft()
        token, source, frame, fps = self.current
        if source.is_dir():
            images = sorted(p for p in source.iterdir() if p.suffix.lower() in {'.exr', '.png', '.jpg', '.jpeg'})
            if not images:
                self.current = None
                QTimer.singleShot(0, self.next)
                return
            source = images[min(frame, len(images)-1)]
            seek = []
        else:
            seek = ['-ss', str(frame/fps)]
        filters = 'scale=160:90:force_original_aspect_ratio=decrease,pad=160:90:(ow-iw)/2:(oh-ih)/2'
        if source.suffix.lower() == '.exr':
            filters += ',eq=gamma=2.2'
        self.process.start('ffmpeg', ['-v', 'error', *seek, '-i', str(source), '-frames:v', '1',
                           '-vf', filters, '-threads', '1', '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1'])
        self.timeout.start()

    def finished(self, code, status):
        self.timeout.stop()
        image = QPixmap()
        content = bytes(self.process.readAllStandardOutput())
        if self.current and code == 0 and image.loadFromData(content, 'PNG'):
            self.ready.emit(self.current[0], image)
        self.current = None
        QTimer.singleShot(0, self.next)

    def failed(self, error):
        if error == QProcess.FailedToStart:
            self.timeout.stop()
            self.current = None
            QTimer.singleShot(0, self.next)

    def close(self):
        self.closed = True
        self.tasks.clear()
        self.timeout.stop()
        self.process.blockSignals(True)
        self.process.kill()
        self.process.waitForFinished(1000)


class MediaCard(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(112, 116)

    def paint(self, painter, option, index):
        data = index.data(Qt.UserRole) or {}
        rect = option.rect.adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.State_Selected)
        painter.save()
        painter.fillRect(rect, QColor('#1b1c16' if selected else '#121311'))
        painter.setPen(QPen(QColor('#c9cb58' if selected else '#282a25'), 1))
        painter.drawRect(rect)
        thumb = QRect(rect.x()+5, rect.y()+5, rect.width()-10, 54)
        painter.fillRect(thumb, QColor('#242923'))
        icon = index.data(Qt.DecorationRole)
        if icon:
            painter.drawPixmap(thumb, icon.pixmap(160, 90))
        state = {'Queued': 'READY', 'Running': 'RENDER', 'Done': 'DONE', 'Failed': 'FAILED', 'Cancelled': 'STOPPED'}.get(data.get('state'), 'READY')
        badge = QRect(thumb.x()+3, thumb.y()+3, min(thumb.width()-6, 65), 16)
        painter.fillRect(badge, QColor('#13251b' if state == 'READY' else '#222622'))
        painter.setPen(QColor('#d4e4d2'))
        font = painter.font(); font.setPixelSize(10); font.setBold(True); painter.setFont(font)
        painter.drawText(badge, Qt.AlignCenter, state)
        painter.setPen(QColor('#efefe7'))
        name = Path(data.get('source', '')).name
        painter.drawText(QRect(rect.x()+5, rect.y()+63, rect.width()-10, 28), Qt.TextWordWrap, name)
        font.setBold(False); font.setPixelSize(9); painter.setFont(font)
        painter.setPen(QColor('#92968b'))
        kind = 'IMAGE SEQUENCE' if Path(data.get('source', '')).is_dir() else 'VIDEO'
        painter.drawText(rect.x()+5, rect.bottom()-6, kind)
        painter.restore()


class Filmstrip(QWidget):
    seek = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(58)
        self.setCursor(Qt.PointingHandCursor)
        self.generation = 0
        self.count = 0
        self.position = 0
        self.thumbs = {}
        self.samples = []
        self.loader = Thumbnails(self)
        self.loader.ready.connect(self.loaded)

    def set_source(self, source, count, fps, frames=None):
        self.generation += 1
        self.count = count
        self.position = 0
        self.thumbs.clear()
        self.loader.tasks.clear()
        self.samples = [round(i*(count-1)/9) for i in range(10)] if count else []
        if source:
            for index, frame in enumerate(self.samples):
                self.loader.add((self.generation, index), frames[frame] if frames else source, 0 if frames else frame, fps)
        self.update()

    def loaded(self, token, pixmap):
        generation, index = token
        if generation == self.generation:
            self.thumbs[index] = pixmap
            self.update()

    def set_position(self, frame):
        self.position = frame
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#151713'))
        if not self.samples:
            painter.setPen(QColor('#7d8175'))
            painter.drawText(self.rect(), Qt.AlignCenter, 'CLIP TIMELINE')
            return
        for index in range(len(self.samples)):
            left = round(index*self.width()/len(self.samples))
            right = round((index+1)*self.width()/len(self.samples))
            rect = QRect(left, 2, right-left-1, self.height()-4)
            if index in self.thumbs:
                image = self.thumbs[index].scaled(rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                crop = QRect((image.width()-rect.width())//2, (image.height()-rect.height())//2,
                             rect.width(), rect.height())
                painter.drawPixmap(rect, image, crop)
            else:
                painter.fillRect(rect, QColor('#242820'))
        x = round(self.position/max(1, self.count-1)*(self.width()-1))
        painter.setPen(QPen(QColor('#e0e351'), 2))
        painter.drawLine(x, 0, x, self.height())

    def mousePressEvent(self, event):
        if self.count:
            self.seek.emit(round(max(0, min(1, event.position().x()/max(1, self.width()-1)))*(self.count-1)))

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.mousePressEvent(event)
