"""Nonblocking update checks, changelog viewing, and explicit restart handoff."""
import json
import os
from pathlib import Path
import subprocess
import sys
from PySide6.QtCore import QObject,QProcess,QTimer
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QCheckBox,QComboBox,QTextBrowser,QMessageBox
from app_update import UpdateStatus,changelog_entries,REPOSITORY,BRANCH
from runtime_support import ROOT,environment
from worker_process import start_worker, signal_tree
import signal


class Updates(QObject):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.status=UpdateStatus();self.dialog=None;self.startup_pending=False
        self.process=QProcess(self);self.process.setWorkingDirectory(str(ROOT))
        self.process.finished.connect(self.checked);self.process.errorOccurred.connect(self.failed)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(45000);self.timer.timeout.connect(self.timeout)
        self.busy_timer=QTimer(self);self.busy_timer.setInterval(1000);self.busy_timer.timeout.connect(self.refresh);self.busy_timer.start()
        enabled=str(window.settings.value('updates/startup','true')).lower()=='true'
        failed=ROOT/'.runtime/update-failed.txt'
        if failed.exists():
            self.status.message='Previous update failed: '+failed.read_text(encoding='utf-8')+'\nSee logs/updates and run Install / Repair.'
            QTimer.singleShot(500,self.show)
        elif enabled: QTimer.singleShot(500,lambda:self.check(True))
        else: QTimer.singleShot(500,lambda:self.check(False,fetch=False))

    def busy(self):
        return bool(self.window.active or self.window.jobs or self.window.process.state()!=QProcess.NotRunning or
                    any(getattr(d,'busy',False) or (hasattr(d,'stop_worker') and d.isVisible()) for d in self.window.findChildren(QDialog)))

    def show(self):
        if self.dialog:
            self.dialog.show();self.dialog.raise_();self.refresh();return
        d=QDialog(self.window);d.setWindowTitle('Updates & Changelog');d.resize(750,600);self.dialog=d
        box=QVBoxLayout(d)
        box.addWidget(QLabel(f'Update source: chiefjackvfx/CorridorKey2.0 • {BRANCH}'))
        self.label=QLabel();self.label.setWordWrap(True);box.addWidget(self.label)
        self.startup=QCheckBox('Check at startup');self.startup.setChecked(str(self.window.settings.value('updates/startup','true')).lower()=='true')
        self.startup.toggled.connect(lambda v:self.window.settings.setValue('updates/startup',v));box.addWidget(self.startup)
        row=QHBoxLayout();box.addLayout(row)
        self.check_button=QPushButton('Check for updates');self.check_button.clicked.connect(lambda:self.check(False));row.addWidget(self.check_button)
        self.update_button=QPushButton('Update and restart');self.update_button.clicked.connect(self.install);row.addWidget(self.update_button)
        self.selector=QComboBox();box.addWidget(self.selector);self.browser=QTextBrowser();self.browser.setOpenExternalLinks(True);box.addWidget(self.browser)
        text=(ROOT/'CHANGELOG.md').read_text(encoding='utf-8') if (ROOT/'CHANGELOG.md').exists() else 'No changelog found.'
        for title,content in changelog_entries(text):self.selector.addItem(title,content)
        if self.status.has_update:self.selector.insertItem(0,'Incoming changes',self.status.notes)
        self.selector.currentIndexChanged.connect(lambda _:self.browser.setMarkdown(self.selector.currentData() or ''))
        self.selector.setCurrentIndex(0 if self.status.has_update else (1 if self.selector.count()>1 else 0))
        self.browser.setMarkdown(self.selector.currentData() or '')
        self.refresh();d.show()

    def refresh(self):
        if self.dialog:
            checking=self.process.state()!=QProcess.NotRunning
            self.label.setText(f'Installed: {self.status.current[:12]}\n'+('Checking…' if checking else self.status.message)+
                               ('\nFinish queued work and hint generation before updating.' if self.busy() else ''))
            self.check_button.setEnabled(not checking)
            self.update_button.setEnabled(self.status.can_update and not checking and not self.busy())
        if self.startup_pending and not self.busy() and self.window.isVisible():
            self.startup_pending=False;self.prompt()

    def check(self,startup=False,fetch=True):
        if self.process.state()!=QProcess.NotRunning:return
        self.automatic=startup
        self.timed_out=False
        start_worker(self.process,[sys.executable,'-u',str(ROOT/'app_update.py'),'--check' if fetch else '--inspect']);self.timer.start();self.refresh()

    def checked(self,code,*args):
        self.timer.stop()
        if getattr(self,'timed_out',False):
            self.refresh();return
        try:
            if code:raise ValueError('Update check process failed.')
            self.status=UpdateStatus(**json.loads(bytes(self.process.readAllStandardOutput())))
        except (ValueError,TypeError):self.status=UpdateStatus(message='Update check failed. You can retry when online.')
        if self.dialog:
            # Replace the previous incoming preview without disturbing installed notes.
            if self.selector.count() and self.selector.itemText(0)=='Incoming changes':self.selector.removeItem(0)
            if self.status.has_update:self.selector.insertItem(0,'Incoming changes',self.status.notes);self.selector.setCurrentIndex(0)
        if getattr(self,'automatic',False) and self.status.has_update:self.startup_pending=True
        self.refresh()

    def failed(self,*args):
        self.timer.stop();self.status=UpdateStatus(message='Could not start update check.');self.refresh()

    def timeout(self):
        self.timed_out=True
        signal_tree(self.process.processId(),getattr(signal,'SIGKILL',signal.SIGTERM))
        self.process.kill();self.status=UpdateStatus(message='Update check timed out. Continue offline or retry.');self.refresh()

    def prompt(self):
        message=QMessageBox(self.window);message.setWindowTitle('CK2 update available');message.setText(self.status.message)
        message.setInformativeText(self.status.notes[:2000]);update=message.addButton('Update and restart',QMessageBox.AcceptRole)
        update.setEnabled(self.status.can_update);view=message.addButton('View changes',QMessageBox.ActionRole);message.addButton('Later',QMessageBox.RejectRole)
        message.exec()
        if message.clickedButton()==update:self.install()
        elif message.clickedButton()==view:self.show()

    def install(self):
        if not self.status.can_update or self.busy():return
        state=ROOT/'.runtime/state.json'
        data=json.loads(state.read_text()) if state.exists() else {}
        python=data.get('base_python')
        if not python or not Path(python).is_file():
            QMessageBox.information(self.window,'Managed setup needed','Run Install / Repair once to enable safe update and restart.');return
        if QMessageBox.question(self.window,'Update and restart','Close CK2, install the checked update, and restart?')!=QMessageBox.Yes:return
        self.window.preview_engine.stop()
        logdir=ROOT/'logs/updates';logdir.mkdir(parents=True,exist_ok=True)
        from datetime import datetime
        log=logdir/(datetime.now().strftime('%Y%m%d-%H%M%S')+'.log')
        try:
            with log.open('wb') as handle:
                subprocess.Popen([python,'-u',str(ROOT/'app_update.py'),'--apply',str(os.getpid()),self.status.target],cwd=ROOT,env=environment(),
                    stdout=handle,stderr=subprocess.STDOUT,start_new_session=os.name!='nt',
                    creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.DETACHED_PROCESS) if os.name=='nt' else 0)
        except OSError as exc:QMessageBox.warning(self.window,'Update could not start',str(exc));return
        self.window.close()

    def close(self):
        self.busy_timer.stop();self.timer.stop()
        signal_tree(self.process.processId(),getattr(signal,'SIGKILL',signal.SIGTERM))
        self.process.kill();self.process.waitForFinished(2000)
