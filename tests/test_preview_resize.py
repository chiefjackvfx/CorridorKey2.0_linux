import os
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
import hashlib
from pathlib import Path
import tempfile
import unittest
import cv2
import numpy as np
from scripts.preview_worker import prepare_preview_input, prepare_preview_hint


class PreviewResize(unittest.TestCase):
    def test_large_linear_exr_and_hint_resize_without_modifying_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'original.exr'
            cv2.imwrite(str(source), np.full((1080, 2048, 3), 2.5, dtype=np.float32))
            original = hashlib.sha256(source.read_bytes()).hexdigest()
            work = root/'work'
            (work/'input').mkdir(parents=True)
            link = work/'input/frame.exr'
            link.symlink_to(source)
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

    def test_small_frames_use_existing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            frame = Path(directory)/'frame.png'
            cv2.imwrite(str(frame), np.zeros((288, 512, 3), dtype=np.uint8))
            self.assertEqual(prepare_preview_input(frame, Path(directory)), frame.parent)


if __name__ == '__main__':
    unittest.main()
