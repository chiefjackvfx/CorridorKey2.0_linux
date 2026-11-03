"""In-app SAM hint generation and non-destructive mask painting."""
import copy
import json
from pathlib import Path
import signal
import os
import sys
import tempfile
import uuid
from worker_process import start_worker, signal_tree
from PySide6.QtCore import Qt,QPointF,QRectF,QProcess,QTimer,Signal
from PySide6.QtGui import QImage,QPainter,QPen,QColor,QKeySequence,QShortcut,QPixmap,QIcon
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QLineEdit,QComboBox,QSpinBox,QScrollArea,QWidget,QDialogButtonBox,QFileDialog,QListWidget,QListWidgetItem)


class HintCanvas(QWidget):
    changed=Signal()
    pointRequested=Signal(float,float,bool)
    boxRequested=Signal(list)
    objectPicked=Signal(float,float,bool)

    def __init__(self):
        super().__init__()
        self.image=QImage()
        self.mask=QImage()
        self.overlay=QImage()
        self.history=[]
        self.future=[]
        self.brush=40
        self.keep=True
        self.matte=False
        self.last=None
        self.mode='brush_keep'
        self.markers=[]
        self.prompt_box=None
        self.drag_start=None
        self.drag_end=None
        self.object_overlay=QImage()
        self.show_objects=False
        self.state_provider=None
        self.state_restorer=None
        self.setMinimumSize(320,200)
        self.setCursor(Qt.CrossCursor)

    def image_rect(self):
        size=self.image.size().scaled(self.size(),Qt.KeepAspectRatio)
        return QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())

    def position(self,point):
        rect=self.image_rect()
        if self.image.isNull() or not rect.contains(point):
            return None
        return QPointF((point.x()-rect.x())*self.image.width()/rect.width(),
                       (point.y()-rect.y())*self.image.height()/rect.height())

    def snapshot(self):
        return self.mask.copy(),self.state_provider() if self.state_provider else None

    def push_snapshot(self,state):
        self.history.append(state)
        self.history=self.history[-16:]
        self.future=[]

    def remember(self): self.push_snapshot(self.snapshot())

    def restore(self,state):
        self.mask=state[0]
        if self.state_restorer and state[1] is not None:self.state_restorer(state[1])
        self.refresh()

    def set_mask(self,image,undo=True):
        if not self.mask.isNull() and undo:
            self.remember()
        self.mask=image.convertToFormat(QImage.Format_RGB32).scaled(self.image.size(),Qt.IgnoreAspectRatio,Qt.SmoothTransformation)
        self.refresh()

    def refresh(self):
        if not self.mask.isNull():
            # QImage copies the array: no dangling numpy data across paint events.
            import numpy as np
            gray=self.mask.convertToFormat(QImage.Format_Grayscale8)
            values=np.frombuffer(gray.constBits(),np.uint8).reshape(gray.height(),gray.bytesPerLine())[:,:gray.width()]
            rgba=np.empty((gray.height(),gray.width(),4),np.uint8)
            rgba[...,:3]=(65,235,110)
            rgba[...,3]=values//2
            self.overlay=QImage(rgba.data,gray.width(),gray.height(),rgba.strides[0],QImage.Format_RGBA8888).copy()
        self.changed.emit();self.update()

    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#151515'))
        if self.image.isNull():
            painter.setPen(Qt.white);painter.drawText(self.rect(),Qt.AlignCenter,'Loading reference frame…');return
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect=self.image_rect()
        if self.matte:
            painter.drawImage(rect,self.mask)
        else:
            painter.drawImage(rect,self.image)
            painter.drawImage(rect,self.object_overlay if self.show_objects and not self.object_overlay.isNull() else self.overlay)
        # Markers stay a readable size when fitting, zooming, or scrolling.
        def screen(x,y): return QPointF(rect.x()+x*rect.width(),rect.y()+y*rect.height())
        for x,y,keep in self.markers:
            center=screen(x,y)
            painter.setPen(QPen(Qt.white,1.5));painter.setBrush(QColor('#36d67a' if keep else '#ef5656'))
            painter.drawEllipse(center,5,5)
        box=self.prompt_box
        if self.drag_start is not None and self.drag_end is not None:
            x0,y0=self.drag_start.x()/self.image.width(),self.drag_start.y()/self.image.height()
            x1,y1=self.drag_end.x()/self.image.width(),self.drag_end.y()/self.image.height()
            box=[min(x0,x1),min(y0,y1),abs(x1-x0),abs(y1-y0)]
        if box:
            x,y,w,h=box
            painter.setPen(QPen(QColor('#ffdf6a'),2,Qt.DashLine));painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(screen(x,y),screen(x+w,y+h)))

    def paint_line(self,point,keep):
        painter=QPainter(self.mask)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(Qt.white if keep else Qt.black,self.brush,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
        if self.last is None:
            painter.setPen(Qt.NoPen)
            painter.setBrush(Qt.white if keep else Qt.black)
            painter.drawEllipse(point,self.brush/2,self.brush/2)
        else:
            painter.drawLine(self.last,point)
        painter.end()
        self.last=point;self.refresh()

    def mousePressEvent(self,event):
        if event.button() not in (Qt.LeftButton,Qt.RightButton) or self.mask.isNull():return
        point=self.position(event.position())
        if point is None:return
        x,y=point.x()/self.image.width(),point.y()/self.image.height()
        if self.mode.startswith('point'):
            self.pointRequested.emit(x,y,self.mode=='point_keep' and event.button()==Qt.LeftButton)
        elif self.mode=='pick':
            self.objectPicked.emit(x,y,event.button()==Qt.RightButton)
        elif self.mode=='box' and event.button()==Qt.LeftButton:
            self.drag_start=self.drag_end=point;self.update()
        else:
            if not self.mode.startswith('brush'):return
            self.remember();self.last=None
            self.paint_line(point,self.keep if event.button()==Qt.LeftButton else False)

    def mouseMoveEvent(self,event):
        point=self.position(event.position())
        if self.drag_start is not None:
            if point is not None:self.drag_end=point;self.update()
        elif self.last is not None and point is not None:
            self.paint_line(point,self.keep if event.buttons() & Qt.LeftButton else False)

    def mouseReleaseEvent(self,event):
        self.last=None
        if self.drag_start is not None:
            point=self.position(event.position()) or self.drag_end
            start=self.drag_start;self.drag_start=self.drag_end=None
            if abs(point.x()-start.x())>=3 and abs(point.y()-start.y())>=3:
                x0,x1=sorted((point.x()/self.image.width(),start.x()/self.image.width()))
                y0,y1=sorted((point.y()/self.image.height(),start.y()/self.image.height()))
                self.boxRequested.emit([x0,y0,x1-x0,y1-y0])
            self.update()

    def undo(self):
        if self.isEnabled() and self.history:
            self.future.append(self.snapshot());self.restore(self.history.pop())

    def redo(self):
        if self.isEnabled() and self.future:
            self.history.append(self.snapshot());self.restore(self.future.pop())


class HintEditor(QDialog):
    def __init__(self,root,source,settings,*,linear=True,color_space='rec709',seed='',parent=None):
        super().__init__(parent)
        self.root=Path(root);self.source=Path(source);self.settings=settings
        self.work=tempfile.TemporaryDirectory(prefix='ck-hint-editor-')
        self.native_hw=None;self.image_path='';self.saved_path='';self.busy=False
        self.revision=0;self.buffer=b'';self.errors='';self.pending=None;self.closing=False
        self.object_masks={};self.selected=set();self.active_object=None;self.force_new=False
        self.recipe={'text':None,'box':None,'groups':[]}
        self.pending_snapshot=None;self.pending_kind=None
        self.setWindowTitle('Create Alpha Hint • '+self.source.name)
        self.resize(1150,820)
        layout=QVBoxLayout(self)
        note=QLabel('Frame 1 • Type a subject, click include/exclude points, or drag a box. Objects view lets you pick individual masks.')
        note.setWordWrap(True);layout.addWidget(note)
        row=QHBoxLayout();layout.addLayout(row)
        self.prompt=QLineEdit('person');self.prompt.setPlaceholderText('Describe the subject, e.g. person or red car')
        row.addWidget(self.prompt,1)
        self.generate=self.button(row,'Generate with SAM 3.1',self.generate_sam)
        self.quick=self.button(row,'Quick screen mask',self.quick_mask)
        row=QHBoxLayout();layout.addLayout(row)
        row.addWidget(QLabel('SAM checkpoint'))
        default=str(self.root/'weights/sam3.1_multiplex.pt')
        self.checkpoint=QLineEdit(str(settings.value('sam_checkpoint',default)))
        row.addWidget(self.checkpoint,1);self.button(row,'Choose…',self.choose_checkpoint)
        row=QHBoxLayout();layout.addLayout(row)
        self.tool=QComboBox()
        for title,key in [('Keep brush','brush_keep'),('Remove brush','brush_remove'),('Include point','point_keep'),
                          ('Exclude point','point_remove'),('Box selection','box'),('Pick object','pick')]:
            self.tool.addItem(title,key)
        row.addWidget(self.tool)
        self.new_object_button=self.button(row,'New object',self.new_object)
        self.diameter=QSpinBox();self.diameter.setRange(1,400);self.diameter.setValue(40);self.diameter.setSuffix(' px')
        row.addWidget(self.diameter)
        self.undo_button=self.button(row,'Undo',lambda:self.canvas.undo())
        self.redo_button=self.button(row,'Redo',lambda:self.canvas.redo())
        self.clear_button=self.button(row,'Clear',self.clear_mask)
        self.invert_button=self.button(row,'Invert',self.invert_mask)
        self.display=QComboBox();self.display.addItems(['Overlay','Matte','Objects']);row.addWidget(self.display)
        self.zoom=QComboBox();self.zoom.addItems(['Fit','100%','200%']);row.addWidget(self.zoom)
        row.addStretch()
        self.canvas=HintCanvas();self.scroll=QScrollArea();self.scroll.setWidget(self.canvas);self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll,1)
        row=QHBoxLayout();layout.addLayout(row)
        row.addWidget(QLabel('Object selections'))
        self.object_list=QListWidget();self.object_list.setMaximumHeight(72)
        self.object_list.setToolTip('Check objects to include them in the hint. Click a row to choose the target for point refinement.')
        row.addWidget(self.object_list,1)
        self.all_objects_button=self.button(row,'All',lambda:self.select_all(True))
        self.no_objects_button=self.button(row,'None',lambda:self.select_all(False))
        self.tool_note=QLabel('Paint directly on the mask. Right-drag removes. Brush size is measured on the editor image.')
        self.tool_note.setWordWrap(True);layout.addWidget(self.tool_note)
        self.status=QLabel('Loading frame 1…');self.status.setWordWrap(True);layout.addWidget(self.status)
        buttons=QDialogButtonBox(QDialogButtonBox.Cancel)
        self.apply=buttons.addButton('Use hint',QDialogButtonBox.AcceptRole)
        self.apply.clicked.connect(self.save_and_accept);buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.tool.currentIndexChanged.connect(self.tool_changed)
        self.canvas.pointRequested.connect(self.add_point)
        self.canvas.boxRequested.connect(self.add_box)
        self.canvas.objectPicked.connect(self.pick_selection)
        self.canvas.state_provider=self.selection_state
        self.canvas.state_restorer=self.restore_selection
        self.object_list.itemChanged.connect(self.object_checked)
        self.object_list.currentItemChanged.connect(self.active_changed)
        self.diameter.valueChanged.connect(lambda v:setattr(self.canvas,'brush',v))
        self.display.currentIndexChanged.connect(self.display_changed)
        self.zoom.currentIndexChanged.connect(self.zoom_changed)
        QShortcut(QKeySequence.Undo,self,activated=self.canvas.undo)
        QShortcut(QKeySequence.Redo,self,activated=self.canvas.redo)
        self.process=QProcess(self)
        self.process.setWorkingDirectory(str(root))
        self.process.readyReadStandardOutput.connect(self.read)
        self.process.readyReadStandardError.connect(self.read_errors)
        self.process.finished.connect(self.exited)
        self.process.errorOccurred.connect(self.failed)
        self.deadline=QTimer(self);self.deadline.setSingleShot(True);self.deadline.setInterval(180000)
        self.deadline.timeout.connect(self.timed_out)
        self.set_busy(True)
        QTimer.singleShot(0,lambda:self.send('load',source=str(source),linear=linear,color_space=color_space,seed=seed))

    @staticmethod
    def button(row,title,callback):
        button=QPushButton(title);button.clicked.connect(callback);row.addWidget(button);return button

    def set_busy(self,busy):
        self.busy=busy
        for widget in (self.generate,self.quick,self.canvas,self.apply,self.tool,self.diameter,self.display,self.zoom,self.undo_button,self.redo_button,self.clear_button,self.invert_button,self.new_object_button,self.object_list,self.all_objects_button,self.no_objects_button):
            widget.setEnabled(not busy and self.native_hw is not None)
        self.diameter.setEnabled(not busy and self.native_hw is not None and self.tool.currentData().startswith('brush'))

    def choose_checkpoint(self):
        path,_=QFileDialog.getOpenFileName(self,'Choose SAM 3.1 checkpoint',self.checkpoint.text(),'SAM checkpoint (*.pt)')
        if path:
            self.checkpoint.setText(path);self.settings.setValue('sam_checkpoint',path)

    def checkpoint_ready(self):
        if not Path(self.checkpoint.text()).expanduser().is_file():
            self.status.setText('Choose the downloaded sam3.1_multiplex.pt checkpoint first.');return False
        self.settings.setValue('sam_checkpoint',self.checkpoint.text());return True

    def generate_sam(self):
        if not self.prompt.text().strip():
            self.status.setText('Type a subject, or choose Include point / Box selection.');return
        if not self.checkpoint_ready():return
        state=self.canvas.snapshot()
        self.recipe={'text':self.prompt.text().strip(),'box':None,'groups':[]}
        self.active_object=None;self.force_new=False
        self.run_selection(state,'replace')

    def run_selection(self,state,kind):
        from hint_selection import prompt_requests
        try:prompt_requests(self.recipe)
        except ValueError as exc:
            self.canvas.restore(state);self.status.setText(str(exc));return
        self.pending_snapshot=state;self.pending_kind=kind
        self.update_markers()
        self.send('sam',image=self.image_path,checkpoint=self.checkpoint.text(),recipe=copy.deepcopy(self.recipe))

    def add_point(self,x,y,keep):
        if self.busy or not self.checkpoint_ready():return
        from hint_selection import pick_object
        state=self.canvas.snapshot()
        ident=self.active_object
        if ident is None and not self.force_new:
            ident=pick_object(self.object_masks,x,y)
        if ident is None:
            if not keep:
                self.status.setText('Start with an include point, or select an existing object row before adding exclude points.');return
            ident=max(list(self.object_masks)+[g['id'] for g in self.recipe['groups']]+[0])+1
        self.active_object=ident;self.force_new=False
        group=next((g for g in self.recipe['groups'] if g['id']==ident),None)
        if group is None:
            group={'id':ident,'points':[],'labels':[]};self.recipe['groups'].append(group)
        group['points'].append([x,y]);group['labels'].append(1 if keep else 0)
        self.run_selection(state,'refine')

    def add_box(self,box):
        if self.busy or not self.checkpoint_ready():return
        state=self.canvas.snapshot()
        self.recipe={'text':None,'box':box,'groups':[]}
        self.active_object=None;self.force_new=False
        self.run_selection(state,'replace')

    def new_object(self):
        if self.busy:return
        self.active_object=None;self.force_new=True
        self.tool.setCurrentIndex(self.tool.findData('point_keep'))
        self.status.setText('Click inside another object to add it. Subsequent include/exclude points refine that object.')

    def quick_mask(self):
        if self.busy:return
        self.pending_snapshot=self.canvas.snapshot();self.pending_kind='replace'
        self.send('screen',image=self.image_path)

    def tool_changed(self,*args):
        key=self.tool.currentData();self.canvas.mode=key;self.canvas.keep=key=='brush_keep'
        notes={'brush_keep':'Paint areas to keep. Right-drag removes.',
               'brush_remove':'Paint areas to remove.',
               'point_keep':'Click inside the subject. Right-click adds an exclude point. Use New object to add another selection.',
               'point_remove':'Click areas to exclude from the active object. Start with an include point or select an object row.',
               'box':'Drag a box around the subject. This starts a fresh SAM selection; you can undo it.',
               'pick':'Click a colored object to toggle it. Right-click excludes it. Choose Objects view to see all detected masks.'}
        self.tool_note.setText(notes[key])
        self.diameter.setEnabled(key.startswith('brush') and not self.busy)
        if key=='pick':self.display.setCurrentIndex(2)

    @staticmethod
    def image_array(image):
        import numpy as np
        gray=image.convertToFormat(QImage.Format_Grayscale8)
        return np.frombuffer(gray.constBits(),np.uint8).reshape(gray.height(),gray.bytesPerLine())[:,:gray.width()].copy()

    @staticmethod
    def mask_image(values):
        return QImage(values.data,values.shape[1],values.shape[0],values.strides[0],QImage.Format_Grayscale8).copy()

    def selection_state(self):
        return dict(recipe=copy.deepcopy(self.recipe),objects=dict(self.object_masks),selected=set(self.selected),
                    active=self.active_object,force_new=self.force_new)

    def restore_selection(self,state):
        self.recipe=copy.deepcopy(state['recipe']);self.object_masks=dict(state['objects'])
        self.selected=set(state['selected']);self.active_object=state['active'];self.force_new=state['force_new']
        self.update_object_list();self.update_markers()

    def reset_selection(self):
        self.recipe={'text':None,'box':None,'groups':[]};self.object_masks={};self.selected=set()
        self.active_object=None;self.force_new=False
        self.update_object_list();self.update_markers()

    def rollback_pending(self):
        if self.pending_snapshot is not None:self.canvas.restore(self.pending_snapshot)
        self.pending_snapshot=None;self.pending_kind=None

    def update_markers(self):
        self.canvas.markers=[(p[0],p[1],bool(label)) for group in self.recipe['groups']
                             for p,label in zip(group['points'],group['labels'])]
        self.canvas.prompt_box=self.recipe.get('box');self.canvas.update()

    def update_object_list(self):
        import numpy as np
        from hint_selection import PALETTE
        self.object_list.blockSignals(True)
        ids=sorted(self.object_masks)
        existing=[self.object_list.item(i).data(Qt.UserRole) for i in range(self.object_list.count())]
        if existing!=ids:
            self.object_list.clear()
            for ident in ids:
                color=PALETTE[(ident-1)%len(PALETTE)]
                swatch=QPixmap(16,16);swatch.fill(QColor(*color))
                item=QListWidgetItem(QIcon(swatch),f'Object {ident}')
                item.setData(Qt.UserRole,ident);item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                self.object_list.addItem(item)
        for index,ident in enumerate(ids):
            item=self.object_list.item(index)
            item.setCheckState(Qt.Checked if ident in self.selected else Qt.Unchecked)
            if ident==self.active_object:self.object_list.setCurrentItem(item)
        self.object_list.blockSignals(False)
        if not self.object_masks:
            self.canvas.object_overlay=QImage();self.canvas.update();return
        h,w=next(iter(self.object_masks.values())).shape
        rgba=np.zeros((h,w,4),np.uint8)
        for ident,mask in sorted(self.object_masks.items(),key=lambda pair:-np.count_nonzero(pair[1])):
            hits=mask>0
            rgba[hits,:3]=PALETTE[(ident-1)%len(PALETTE)]
            rgba[hits,3]=150 if ident in self.selected else 55
        self.canvas.object_overlay=QImage(rgba.data,w,h,rgba.strides[0],QImage.Format_RGBA8888).copy()
        self.canvas.update()

    def receive_objects(self,entries):
        import cv2
        from hint_selection import combine_masks,preserve_brush_changes
        objects={entry['id']:cv2.imread(entry['mask'],cv2.IMREAD_GRAYSCALE) for entry in entries}
        if not objects or any(mask is None for mask in objects.values()):
            raise ValueError('Could not read the generated object masks.')
        hw=(self.canvas.image.height(),self.canvas.image.width())
        if self.pending_kind=='refine' and self.pending_snapshot is not None and self.pending_snapshot[1]['objects']:
            old=self.pending_snapshot[1]
            old_base=combine_masks(old['objects'],old['selected'],hw)
            self.selected=old['selected'] & objects.keys()
            self.selected.update(objects.keys()-old['objects'].keys())
            if self.active_object in objects:self.selected.add(self.active_object)
            new_base=combine_masks(objects,self.selected,hw)
            values=preserve_brush_changes(self.image_array(self.pending_snapshot[0]),old_base,new_base)
        else:
            self.selected=set(objects)
            values=combine_masks(objects,self.selected,hw)
        self.object_masks=objects
        self.canvas.set_mask(self.mask_image(values),undo=False)
        self.update_object_list();self.update_markers()

    def set_selected(self,selected,active=None):
        if self.busy or not self.object_masks:return
        from hint_selection import combine_masks,preserve_brush_changes
        self.canvas.remember()
        hw=(self.canvas.image.height(),self.canvas.image.width())
        old_base=combine_masks(self.object_masks,self.selected,hw)
        new_base=combine_masks(self.object_masks,selected,hw)
        values=preserve_brush_changes(self.image_array(self.canvas.mask),old_base,new_base)
        self.selected=set(selected)
        if active is not None:self.active_object=active
        self.canvas.set_mask(self.mask_image(values),undo=False)
        self.update_object_list();self.update_markers()
        self.status.setText(f'{len(self.selected)} of {len(self.object_masks)} objects selected • Brush edits are retained.')

    def object_checked(self,item):
        ident=item.data(Qt.UserRole);selected=set(self.selected)
        if item.checkState()==Qt.Checked:selected.add(ident)
        else:selected.discard(ident)
        self.set_selected(selected,ident)

    def active_changed(self,item,previous=None):
        if item is not None:self.active_object=item.data(Qt.UserRole)

    def select_all(self,include):
        self.set_selected(set(self.object_masks) if include else set())

    def pick_selection(self,x,y,remove=False):
        from hint_selection import pick_object
        ident=pick_object(self.object_masks,x,y)
        if ident is None:
            self.status.setText('No generated object at this pixel. Use an include point or a box to create a selection.');return
        selected=set(self.selected)
        if remove or ident in selected:selected.discard(ident)
        else:selected.add(ident)
        self.set_selected(selected,ident)

    def send(self,op,**values):
        self.revision+=1
        request=dict(id=self.revision,op=op,work=self.work.name,**values)
        self.set_busy(True)
        self.status.setText('Loading SAM 3.1 / generating subject mask…' if op=='sam' else 'Preparing hint…')
        if self.process.state()==QProcess.NotRunning:
            self.errors='';self.buffer=b''
            start_worker(self.process,[sys.executable,'-u',str(self.root/'scripts/hint_worker.py')])
        self.process.write((json.dumps(request)+'\n').encode())
        self.deadline.start()

    def read_errors(self):
        self.errors=(self.errors+bytes(self.process.readAllStandardError()).decode(errors='replace'))[-6000:]

    def read(self):
        self.buffer+=bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line,self.buffer=self.buffer.split(b'\n',1)
            try: response=json.loads(line)
            except ValueError:continue
            if response.get('id')!=self.revision:continue
            self.deadline.stop()
            if 'error' in response:
                if self.pending_snapshot is not None:self.canvas.restore(self.pending_snapshot)
                self.pending_snapshot=None;self.pending_kind=None
                self.status.setText('Generation failed: '+response['error'][:700])
            else:
                try:
                    if 'image' in response:
                        self.image_path=response['image'];self.native_hw=tuple(response['native_hw'])
                        self.canvas.image=QImage(self.image_path)
                    if 'objects' in response:
                        self.receive_objects(response['objects'])
                    else:
                        if 'image' not in response:
                            self.reset_selection()
                        self.canvas.set_mask(QImage(response['mask']),undo=False)
                    if self.pending_snapshot is not None:
                        self.canvas.push_snapshot(self.pending_snapshot)
                    self.pending_snapshot=None;self.pending_kind=None
                    if 'image' in response:
                        self.status.setText('Loaded '+response.get('seed_kind','mask')+' • Generate with SAM 3.1, then brush corrections. Use hint saves at full source resolution.')
                    else:
                        self.status.setText('Mask ready • Select objects, add points, or brush corrections. Use hint attaches the full-resolution mask.')
                except Exception as exc:
                    self.rollback_pending()
                    self.status.setText('Could not apply selection: '+str(exc))
            self.set_busy(False)

    def display_changed(self,index):
        self.canvas.matte=index==1;self.canvas.show_objects=index==2;self.canvas.update()

    def zoom_changed(self,index):
        self.scroll.setWidgetResizable(index==0)
        if index:
            factor=index
            self.canvas.resize(self.canvas.image.width()*factor,self.canvas.image.height()*factor)

    def clear_mask(self):
        if self.canvas.mask.isNull():return
        self.canvas.remember();self.reset_selection()
        image=self.canvas.mask.copy();image.fill(Qt.black);self.canvas.set_mask(image,undo=False)

    def invert_mask(self):
        if self.canvas.mask.isNull():return
        image=self.canvas.mask.copy();image.invertPixels();self.canvas.set_mask(image)

    def save_and_accept(self):
        if self.busy or self.native_hw is None:return
        try:
            import numpy as np
            from hint_tools import save_hint
            gray=self.canvas.mask.convertToFormat(QImage.Format_Grayscale8)
            mask=np.frombuffer(gray.constBits(),np.uint8).reshape(gray.height(),gray.bytesPerLine())[:,:gray.width()].copy()
            directory=self.root/'hints'
            destination=directory/(self.source.stem+'_'+uuid.uuid4().hex[:12]+'.png')
            save_hint(mask,self.native_hw,destination)
            self.saved_path=str(destination)
            self.accept()
        except Exception as exc:
            self.status.setText('Could not save hint: '+str(exc))

    def failed(self,error):
        if error==QProcess.FailedToStart:
            self.rollback_pending()
            self.deadline.stop();self.set_busy(False);self.status.setText('Could not start hint worker: '+self.process.errorString())

    def exited(self,code,status):
        if self.busy and not self.closing:
            self.rollback_pending()
            self.deadline.stop();self.set_busy(False)
            self.status.setText('Hint worker stopped. '+self.errors[-1200:])

    def timed_out(self):
        self.stop_worker();self.rollback_pending();self.set_busy(False);self.status.setText('Hint generation timed out. Your current mask is preserved; you can retry.')

    def stop_worker(self):
        self.deadline.stop()
        pid=self.process.processId()
        if pid:
            signal_tree(pid,getattr(signal,'SIGKILL',signal.SIGTERM))
            self.process.kill();self.process.waitForFinished(5000)

    def done(self,result):
        self.closing=True;self.stop_worker();self.work.cleanup();super().done(result)
