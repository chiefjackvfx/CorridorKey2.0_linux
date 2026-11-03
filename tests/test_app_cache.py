"""Project-local temporary paths, worker environments, and cache cleanup."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from app_cache import cache_path,cache_directory,cache_environment
from runtime_support import environment,configure


class CachePaths(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ck cache paths ');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_paths_are_relative_to_installation_not_working_directory(self):
        path=cache_directory('hints',self.root)
        self.assertEqual(path,self.root/'.cache/hints');self.assertTrue(path.is_dir())
        self.assertEqual(cache_path('inference',self.root),self.root/'.cache/inference')
        for category in ('../outside',str(self.root/'absolute')):
            with self.assertRaises(ValueError):cache_directory(category,self.root)

    def test_environment_overrides_system_and_user_cache_paths(self):
        with patch.dict(os.environ,{'TEMP':'C:/Users/user/AppData/Local/Temp','HF_HOME':'/old/cache','UV_CACHE_DIR':'/old/uv'}):
            env=environment(self.root)
        for key,path in cache_environment(self.root).items():
            self.assertEqual(env[key],path);self.assertTrue(Path(path).is_relative_to(self.root/'.cache'))
        self.assertEqual(env['TEMP'],env['TMPDIR'])

    def test_configure_resets_previously_cached_tempfile_directory(self):
        previous=tempfile.tempdir;previous_prefix=sys.pycache_prefix
        try:
            with patch.dict(os.environ):
                tempfile.tempdir='/old/system/temp'
                configure(self.root)
                with tempfile.TemporaryDirectory() as path:
                    self.assertTrue(Path(path).is_relative_to(self.root/'.cache/temp'))
                result=subprocess.run([sys.executable,'-c','import tempfile; print(tempfile.gettempdir())'],env=environment(self.root),capture_output=True,text=True,check=True)
                self.assertEqual(result.stdout.strip(),str(self.root/'.cache/temp'))
        finally:
            tempfile.tempdir=previous;sys.pycache_prefix=previous_prefix

    def test_preview_and_hint_workspaces_stay_in_local_cache_and_clean_up(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QSettings
        from linux_preview import AutoPreview
        from linux_hint_editor import HintEditor
        app=QApplication.instance() or QApplication([])
        preview=AutoPreview(self.root)
        path=Path(preview.cache.name)
        self.assertTrue(path.is_relative_to(self.root/'.cache/previews'))
        preview.close();self.assertFalse(path.exists())
        source=self.root/'source.mp4';source.touch()
        editor=HintEditor(self.root,source,QSettings(str(self.root/'prefs.ini'),QSettings.IniFormat))
        path=Path(editor.work.name)
        self.assertTrue(path.is_relative_to(self.root/'.cache/hints'))
        editor.reject();app.processEvents()
        self.assertFalse(path.exists())
        from PySide6.QtCore import QProcess
        self.assertEqual(editor.process.state(),QProcess.NotRunning)

    def test_bootstrap_redirects_temp_before_provisioning_python(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('setup_runtime.sh','setup_runtime.ps1'):
            text=(root/name).read_text()
            self.assertNotIn('.runtime/downloads',text);self.assertNotIn('.runtime\\downloads',text)
            self.assertIn('TEMP',text);self.assertIn('UV_CACHE_DIR',text);self.assertIn('.cache',text)


if __name__=='__main__':unittest.main()
