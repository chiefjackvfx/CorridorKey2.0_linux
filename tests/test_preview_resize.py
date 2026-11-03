import os
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
import hashlib
import errno
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest
import cv2
import numpy as np
from scripts.preview_worker import extract, prepare_preview_input, prepare_preview_hint


class PreviewResize(unittest.TestCase):
    def test_large_linear_exr_and_hint_resize_without_modifying_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'original.exr'
            cv2.imwrite(str(source), np.full((1080, 2048, 3), 2.5, dtype=np.float32))
            original = hashlib.sha256(source.read_bytes()).hexdigest()
            work = root/'work'
            plate = root/'plate'; plate.mkdir()
            source.rename(plate/source.name); source = plate/source.name
            link = extract(plate, 0, 25, work/'input')
            preview = prepare_preview_input(link, work)
            pixels = cv2.imread(str(preview/'frame.exr'), cv2.IMREAD_UNCHANGED)
            self.assertEqual(pixels.shape, (675, 1280, 3))
            self.assertGreater(float(pixels.min()), 2.4)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original)
            hint = root/'hint.png'
            cv2.imwrite(str(hint), np.full((1080, 2048), 255, dtype=np.uint8))
            original_hint = hint.read_bytes()
            resized_hint = prepare_preview_hint(hint, preview, work)
            self.assertEqual(cv2.imread(str(resized_hint), cv2.IMREAD_UNCHANGED).shape, (675, 1280))
            self.assertEqual(hint.read_bytes(), original_hint)

    def test_windows_sequence_preview_copies_without_symlink_privileges(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'NAS plate'; source.mkdir()
            frame = source/'plate.1001.exr'
            cv2.imwrite(str(frame), np.full((16, 24, 3), 2.5, dtype=np.float32))
            original = frame.read_bytes()
            with patch('scripts.preview_worker.sys.platform', 'win32'), patch.object(Path, 'symlink_to') as link:
                target = extract(source, 0, 25, root/'.cache/input')
            link.assert_not_called()
            self.assertFalse(target.is_symlink())
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(frame.read_bytes(), original)

    def test_privilege_error_falls_back_to_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'plate'; source.mkdir()
            (source/'1001.png').write_bytes(b'frame bytes')
            error = PermissionError('A required privilege is not held'); error.winerror = 1314
            with patch('scripts.preview_worker.sys.platform', 'linux'), patch.object(Path, 'symlink_to', side_effect=error):
                target = extract(source, 0, 25, root/'input')
            self.assertEqual(target.read_bytes(), b'frame bytes')
            self.assertFalse(target.is_symlink())

    def test_unrelated_link_errors_are_not_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/'plate'; source.mkdir()
            (source/'1001.png').touch()
            with patch('scripts.preview_worker.sys.platform', 'linux'), patch.object(Path, 'symlink_to', side_effect=OSError(errno.EIO, 'read failure')):
                with self.assertRaises(OSError) as caught: extract(source, 0, 25, root/'input')
            self.assertEqual(caught.exception.errno, errno.EIO)

    def test_small_frames_use_existing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            frame = Path(directory)/'frame.png'
            cv2.imwrite(str(frame), np.zeros((288, 512, 3), dtype=np.uint8))
            self.assertEqual(prepare_preview_input(frame, Path(directory)), frame.parent)


if __name__ == '__main__':
    unittest.main()
