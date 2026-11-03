import os
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import unittest
import numpy as np
import cv2
from color_management import acescg_to_linear709
from preview_cache import PreviewCache, signature
from linux_jobs import Options, build_command


class Color(unittest.TestCase):
    def test_neutral_and_hdr_are_not_gamma_corrected_or_clamped(self):
        neutral = np.array([[.18,.18,.18], [4,4,4], [-.2,-.2,-.2]], dtype=np.float32)
        np.testing.assert_allclose(acescg_to_linear709(neutral), neutral, atol=1e-6)
        np.testing.assert_allclose(acescg_to_linear709([[1,0,0]])[0], [1.70505099,-.13025642,-.02400336], atol=1e-6)

    def test_sequence_reader_converts_once_and_does_not_transform_alpha(self):
        from corridorkey.video_io import _read_frame_dir_views
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'frame.exr'
            bgra = np.zeros((4,4,4), np.float32)
            bgra[...,2] = 1
            bgra[...,3] = .25
            cv2.imwrite(str(path), bgra)
            original = path.read_bytes()
            display, linear = _read_frame_dir_views(path, exr_linear=False, input_color_space='acescg')
            np.testing.assert_allclose(linear[0,0], [1.70505099,-.13025642,-.02400336], atol=1e-6)
            self.assertEqual(path.read_bytes(), original)
            np.testing.assert_array_equal(display[0,0], [1,0,0])
            cmd = build_command(tmp, 'python', tmp, Path(tmp)/'out', Options(input_color_space='acescg'))
            self.assertIn('acescg', cmd)


class Cache(unittest.TestCase):
    def test_keys_follow_source_hint_color_and_settings_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'frame.exr'; path.touch()
            values = asdict(Options())
            first = signature(tmp,25,values)
            self.assertNotEqual(first, signature(tmp,25,asdict(replace(Options(),input_color_space='acescg'))))
            self.assertNotEqual(first, signature(tmp,25,asdict(replace(Options(),despill=.9))))
            path.write_bytes(b'changed')
            self.assertNotEqual(first, signature(tmp,25,values))
            hint = Path(tmp)/'hint.png'; hint.touch()
            values.update(hint_mode='first',hint_path=str(hint))
            before = signature(tmp,25,values)
            hint.write_bytes(b'new hint')
            self.assertNotEqual(before, signature(tmp,25,values))

    def test_disk_budget_eviction_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = PreviewCache(limit=10)
            def add(key):
                directory = Path(tmp)/key; directory.mkdir()
                image = directory/'alpha.png'; image.write_bytes(b'123456')
                (directory/'scratch').mkdir()
                cache.put(key, {'alpha':str(image)},directory)
                self.assertFalse((directory/'scratch').exists())
                return directory
            first=add('a'); self.assertIsNotNone(cache.get('a'))
            second=add('b')
            self.assertFalse(first.exists())
            self.assertIsNone(cache.get('a'))
            self.assertLessEqual(cache.size, 10)
            cache.clear(); self.assertFalse(second.exists())


if __name__ == '__main__':
    unittest.main()
