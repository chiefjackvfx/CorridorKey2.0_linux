"""Updater safety and runtime migration tests; no network or GPU required."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import app_update as updates
import runtime_setup as runtime


class GitUpdates(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ck update space ');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.remote=self.root/'remote.git';self.writer=self.root/'writer';self.local=self.root/'checkout'
        self.git(self.root,'init','--bare','--initial-branch=master',str(self.remote));self.git(self.root,'clone',str(self.remote),str(self.writer))
        self.git(self.writer,'checkout','-b','master');self.config(self.writer)
        (self.writer/'CHANGELOG.md').write_text('# Changelog\n\n## Unreleased\n\n### Added\n\n- Initial change\n')
        (self.writer/'.gitignore').write_text('.runtime/\n')
        (self.writer/updates.LEGACY_LAUNCHER).write_text('@echo off\nrem original legacy launcher\n')
        self.commit(self.writer,'initial');self.git(self.writer,'push','-u','origin','master')
        self.git(self.root,'clone',str(self.remote),str(self.local));self.config(self.local)

    def git(self,root,*args):
        return subprocess.run(['git',*args],cwd=root,check=True,capture_output=True,text=True).stdout.strip()

    def config(self,root):
        self.git(root,'config','user.name','Test');self.git(root,'config','user.email','test@example.invalid')

    def commit(self,root,message):self.git(root,'add','.');self.git(root,'commit','-m',message)

    def publish(self):
        with (self.writer/'CHANGELOG.md').open('a') as f:f.write('- Incoming SAM improvement\n')
        self.commit(self.writer,'incoming');self.git(self.writer,'push')

    def status(self,fetch=True):return updates.check_updates(self.local,fetch,repository=str(self.remote))

    def test_current_and_incoming_unreleased(self):
        self.assertEqual(self.status().message,'Up to date.')
        self.publish();status=self.status()
        self.assertTrue(status.can_update);self.assertTrue(status.has_update)
        self.assertIn('Incoming SAM improvement',status.notes);self.assertNotIn('Initial change',status.notes)

    def test_dirty_detached_wrong_branch_and_divergence(self):
        self.publish();(self.local/'local.py').write_text('local')
        self.assertFalse(self.status().can_update)
        (self.local/'local.py').unlink();self.git(self.local,'checkout','--detach')
        self.assertIn('detached',self.status().message)
        self.git(self.local,'checkout','-b','work')
        self.assertIn('current branch: work',self.status().message)
        self.git(self.local,'checkout','master');(self.local/'local.py').write_text('local');self.commit(self.local,'local')
        self.assertIn('diverged',self.status().message)

    def test_unused_launcher_edit_survives_real_fast_forward(self):
        launcher=self.local/updates.LEGACY_LAUNCHER
        local_bytes=b'@echo off\r\nrem my unused launcher\r\n'
        launcher.write_bytes(local_bytes)
        self.publish();status=self.status()
        self.assertTrue(status.can_update,status.message)
        real_check=updates.check_updates
        with patch.object(updates,'check_updates',side_effect=lambda root,fetch:real_check(root,fetch,repository=str(self.remote))):
            updates.apply_update(self.local,status.target)
        self.assertEqual(self.git(self.local,'rev-parse','HEAD'),status.target)
        self.assertEqual(launcher.read_bytes(),local_bytes)

    def test_incoming_legacy_launcher_change_still_blocks(self):
        launcher=self.local/updates.LEGACY_LAUNCHER;launcher.write_text('my local edit')
        (self.writer/updates.LEGACY_LAUNCHER).write_text('published edit')
        self.commit(self.writer,'legacy launcher update');self.git(self.writer,'push')
        status=self.status()
        self.assertTrue(status.has_update);self.assertFalse(status.can_update)
        self.assertIn(updates.LEGACY_LAUNCHER,status.message)
        self.assertEqual(launcher.read_text(),'my local edit')

    def test_legacy_exception_does_not_hide_other_or_staged_changes(self):
        launcher=self.local/updates.LEGACY_LAUNCHER;launcher.write_text('my local edit')
        self.publish()
        changelog=self.local/'CHANGELOG.md';original=changelog.read_text();changelog.write_text(original+'local note')
        status=self.status();self.assertFalse(status.can_update);self.assertIn('CHANGELOG.md',status.message)
        changelog.write_text(original)
        self.git(self.local,'add',updates.LEGACY_LAUNCHER)
        status=self.status();self.assertFalse(status.can_update);self.assertIn(updates.LEGACY_LAUNCHER,status.message)

    def test_ahead_unavailable_and_timeout(self):
        (self.local/'local.py').write_text('local');self.commit(self.local,'local')
        self.assertIn('ahead',self.status().message)
        with patch.object(updates,'git',side_effect=subprocess.TimeoutExpired('git',30)):
            self.assertFalse(self.status().can_update)
        self.git(self.local,'remote','set-url','origin',str(self.root/'missing.git'))
        status=updates.check_updates(self.local,repository=str(self.root/'missing.git'))
        self.assertIn('unavailable',status.message)

    def test_apply_rechecks_target_and_never_discards_local_work(self):
        self.publish();status=self.status()
        real=updates.check_updates
        with patch.object(updates,'check_updates',side_effect=lambda root,fetch:real(root,fetch,repository=str(self.remote))):
            with self.assertRaises(RuntimeError):updates.apply_update(self.local,'0'*40)
            (self.local/'keep.txt').write_text('keep')
            with self.assertRaises(RuntimeError):updates.apply_update(self.local,status.target)
            self.assertEqual((self.local/'keep.txt').read_text(),'keep')
            (self.local/'keep.txt').unlink();updates.apply_update(self.local,status.target)
        self.assertEqual(self.git(self.local,'rev-parse','HEAD'),status.target)

    @unittest.skipIf(os.name=='nt','Linux external updater integration; native Windows checks are separate')
    def test_external_update_fast_forward_setup_and_restart(self):
        import shlex,sys,time
        (self.writer/'.gitignore').write_text('.runtime/\nvenv/\nready\nrestarted\n')
        (self.writer/'scripts').mkdir()
        (self.writer/'scripts/launch.py').write_text("from pathlib import Path; Path('restarted').write_text('yes')")
        (self.writer/'setup_runtime.sh').write_text("set -eu\nmkdir -p venv/bin\nln -s "+shlex.quote(sys.executable)+" venv/bin/python\nprintf ready > ready\n")
        self.commit(self.writer,'setup');self.git(self.writer,'push');status=self.status()
        real_check=updates.check_updates;real_start=subprocess.Popen;started=[]
        def start(*args,**kwargs):
            process=real_start(*args,**kwargs);started.append(process);return process
        with patch.object(updates,'wait_for_exit') as wait,patch.object(updates,'check_updates',side_effect=lambda root,fetch:real_check(root,fetch,repository=str(self.remote))):
            # Only intercept restart; Git and setup must execute normally.
            def restart(*args,**kwargs):return start(*args,**kwargs)
            with patch('app_update.subprocess.Popen',side_effect=restart):
                updates.updater(self.local,123,status.target)
            wait.assert_called_once_with(123)
        for process in started:process.wait(timeout=10)
        self.assertEqual((self.local/'ready').read_text(),'ready')
        self.assertEqual((self.local/'restarted').read_text(),'yes')
        self.assertEqual(self.git(self.local,'rev-parse','HEAD'),status.target)

    def test_missing_git_and_archive(self):
        with patch('app_update.shutil.which',return_value=None):self.assertFalse(self.status().can_update)
        self.assertFalse(updates.check_updates(self.root).can_update)

    def test_missing_remote_changelog_does_not_block_update(self):
        (self.writer/'CHANGELOG.md').unlink();self.commit(self.writer,'no notes');self.git(self.writer,'push')
        status=self.status();self.assertTrue(status.can_update);self.assertIn('No changelog notes',status.notes)

    def test_changelog_entries(self):
        entries=updates.changelog_entries('# Changes\n## Unreleased\n- new\n## 1.0.0\n- old\n')
        self.assertEqual([e[0] for e in entries],['All changes','Unreleased','1.0.0'])


class RuntimeSetup(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ck setup space ');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        for name in ('requirements.txt','requirements-linux.txt','constraints-runtime.txt','runtime_setup.py'):(self.root/name).write_text('# requirements')
        (self.root/'.runtime').mkdir();(self.root/'venv').mkdir();(self.root/'venv/marker').write_text('old')
        self.python=self.root/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python');self.python.parent.mkdir(parents=True);self.python.touch()

    def test_exclusive_lock_and_release(self):
        with runtime.setup_lock(self.root):
            with self.assertRaises(RuntimeError):
                with runtime.setup_lock(self.root):pass
        with runtime.setup_lock(self.root):pass

    def test_interrupted_migration_restores_original(self):
        backup='venv-'+'a'*32;saved=self.root/'.runtime/backups'/backup;saved.parent.mkdir();(self.root/'venv').rename(saved)
        (self.root/'venv').mkdir();(self.root/'venv/broken').touch()
        runtime.atomic_json(self.root/'.runtime/migration.json',{'backup':backup,'complete':False})
        runtime.recover(self.root)
        self.assertEqual((self.root/'venv/marker').read_text(),'old');self.assertFalse((self.root/'venv/broken').exists())

    def test_bad_journal_is_rejected(self):
        runtime.atomic_json(self.root/'.runtime/migration.json',{'backup':'../outside','complete':False})
        with self.assertRaises(RuntimeError):runtime.recover(self.root)
        self.assertTrue((self.root/'venv/marker').exists())

    def test_failed_rebuild_restores_environment(self):
        with patch.object(runtime,'ensure_ffmpeg'),patch.object(runtime,'run',side_effect=RuntimeError('install failed')):
            with self.assertRaises(RuntimeError):runtime.prepare(self.root,'uv','python')
        self.assertEqual((self.root/'venv/marker').read_text(),'old')

    def test_reuse_and_remembered_sam(self):
        runtime.atomic_json(self.root/'.runtime/state.json',{'sam':True,'fingerprint':runtime.fingerprint(self.root,True),'base_python':'managed'})
        with patch.object(runtime,'ensure_ffmpeg'),patch.object(runtime,'verify') as verify,patch.object(runtime,'run') as run:
            runtime.prepare(self.root,'uv','managed');run.assert_not_called();verify.assert_called_once_with(self.python,self.root,True)

    def test_checksum_failure_and_network_failure_leave_no_partial_file(self):
        target=self.root/'download.zip'
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'wrong')):
            with self.assertRaises(RuntimeError):runtime.fetch_verified('https://example.invalid',target,'0'*64)
        self.assertFalse(target.exists());self.assertFalse(target.with_suffix('.download').exists())
        with patch('urllib.request.urlopen',side_effect=OSError('offline')):
            with self.assertRaises(OSError):runtime.fetch_verified('https://example.invalid',target,'0'*64)
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'valid')):
            runtime.fetch_verified('https://example.invalid',target,hashlib.sha256(b'valid').hexdigest())
        self.assertEqual(target.read_bytes(),b'valid')

    def test_application_lock_blocks_install(self):
        with runtime.setup_lock(self.root,'application.lock'),patch.object(runtime,'ensure_ffmpeg') as ffmpeg:
            with self.assertRaises(RuntimeError):runtime.prepare(self.root,'uv','managed')
            ffmpeg.assert_not_called()


class WindowsCompatibility(unittest.TestCase):
    def test_exclusive_publication_does_not_use_linux_api(self):
        import linux_export
        with patch.object(linux_export.os,'name','nt'),patch.object(linux_export.os,'rename') as rename:
            linux_export.rename_exclusive('source','destination');rename.assert_called_once_with('source','destination')

    def test_launchers_are_local_and_do_not_install_on_run(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('windows_install.bat','windows_run.bat','windows_check.bat','windows_update.bat','windows_install_sam.bat'):
            self.assertIn('%~dp0',(root/name).read_text())
        run=(root/'windows_run.bat').read_text();self.assertIn('venv\\Scripts\\python.exe',run);self.assertNotIn('pip install',run)


if __name__=='__main__':unittest.main()


class UpdateInterface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from PySide6.QtCore import QSettings,QProcess
        from PySide6.QtWidgets import QMainWindow
        import updates_ui
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'CHANGELOG.md').write_text('## Unreleased\n- Added stuff\n## 1.0\n- Old stuff\n')
        self.window=QMainWindow();self.window.jobs=[];self.window.active=None;self.window.process=QProcess()
        self.window.settings=QSettings(str(self.root/'settings.ini'),QSettings.IniFormat);self.window.settings.setValue('updates/startup',False)
        self.patcher=patch.object(updates_ui,'ROOT',self.root);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.controller=updates_ui.Updates(self.window);self.addCleanup(self.cleanup)

    def cleanup(self):
        self.controller.close();self.window.close()
        if self.controller.dialog:self.controller.dialog.close()

    def test_dialog_changelog_and_startup_preference(self):
        self.controller.show();c=self.controller
        self.assertEqual(c.selector.currentText(),'Unreleased')
        c.startup.setChecked(True);self.assertTrue(self.window.settings.value('updates/startup'))
        c.status=updates.UpdateStatus(current='a'*40,target='b'*40,has_update=True,can_update=True,notes='- new')
        c.refresh();self.assertTrue(c.update_button.isEnabled())
        self.window.jobs=['queued'];c.refresh();self.assertFalse(c.update_button.isEnabled())

    def test_notification_waits_for_queue(self):
        self.window.show();self.window.jobs=['queued'];self.controller.startup_pending=True
        with patch.object(self.controller,'prompt') as prompt:
            self.controller.refresh();prompt.assert_not_called()
            self.window.jobs=[];self.controller.refresh();prompt.assert_called_once()
            self.controller.refresh();prompt.assert_called_once()

    def test_check_does_not_block_and_timeout_has_message(self):
        with patch('updates_ui.start_worker') as start:
            self.controller.check();start.assert_called_once()
        self.controller.timeout();self.assertIn('timed out',self.controller.status.message)
        self.controller.checked(1);self.assertIn('timed out',self.controller.status.message)

    def test_incoming_changes_visible_when_dialog_opens_later(self):
        self.controller.status=updates.UpdateStatus(has_update=True,notes='- Incoming')
        self.controller.show();self.assertEqual(self.controller.selector.currentText(),'Incoming changes')
        self.assertIn('Incoming',self.controller.browser.toPlainText())


@unittest.skipUnless(os.name=='nt','Requires native Windows process and filesystem semantics')
class NativeWindows(unittest.TestCase):
    def test_exclusive_folder_publication_preserves_existing_folder(self):
        from linux_export import rename_exclusive
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';target=root/'target';source.mkdir();target.mkdir();(target/'keep').write_text('keep')
            with self.assertRaises(OSError):rename_exclusive(source,target)
            self.assertEqual((target/'keep').read_text(),'keep')

    def test_memory_map_can_be_removed_after_close(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as temp:
            from corridorkey.runtime import _open_memmap, _close_runtime_memmaps
            path=Path(temp)/'map';mapped=_open_memmap(path,dtype='float32',mode='w+',shape=(4,));_close_runtime_memmaps();path.unlink()
            self.assertFalse(path.exists())

    def test_job_object_kills_descendant(self):
        import ctypes,sys,time
        from worker_process import signal_tree
        host=Path(__file__).resolve().parents[1]/'scripts/worker_host.py'
        child="import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(p.pid,flush=True); time.sleep(60)"
        process=subprocess.Popen([sys.executable,str(host),sys.executable,'-u','-c',child],stdout=subprocess.PIPE,text=True)
        try:
            pid=int(process.stdout.readline());signal_tree(process.pid,0);process.wait(timeout=10);time.sleep(.2)
            kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];kernel.OpenProcess.restype=ctypes.c_void_p
            handle=kernel.OpenProcess(0x100000,False,pid)
            if handle:
                kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
                try:self.assertEqual(kernel.WaitForSingleObject(handle,5000),0)
                finally:kernel.CloseHandle(handle)
        finally:
            if process.poll() is None:signal_tree(process.pid,0);process.wait(timeout=10)
            process.stdout.close()


class RecoveryMetadata(unittest.TestCase):
    def test_interrupted_commit_restores_prior_state_and_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'.runtime/backups').mkdir(parents=True);backup='venv-'+'b'*32
            old=root/'.runtime/backups'/backup;old.mkdir();(old/'old').touch();(root/'venv').mkdir()
            runtime.atomic_json(root/'.runtime/state.json',{'sam':False,'fingerprint':'new'})
            previous={'sam':True,'fingerprint':'old'}
            runtime.atomic_json(root/'.runtime/migration.json',{'backup':backup,'complete':False,'previous_state':previous})
            runtime.recover(root)
            self.assertTrue((root/'venv/old').exists());self.assertEqual(json.loads((root/'.runtime/state.json').read_text()),previous)

    def test_kept_array_reference_is_closed_before_scratch_unlink(self):
        from corridorkey.runtime import _open_memmap,_close_runtime_memmaps
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'scratch';mapped=_open_memmap(path,dtype='float32',mode='w+',shape=(8,))
            _close_runtime_memmaps();self.assertTrue(mapped._mmap.closed);path.unlink()

    def test_external_updater_does_not_restart_after_setup_failure(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(updates,'wait_for_exit'),patch.object(updates,'apply_update'),patch('app_update.subprocess.run',side_effect=subprocess.CalledProcessError(1,'setup')),patch('app_update.subprocess.Popen') as start:
            with self.assertRaises(subprocess.CalledProcessError):updates.updater(Path(tmp),123,'a'*40)
            start.assert_not_called()
