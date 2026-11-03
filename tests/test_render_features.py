import os
os.environ['OPENCV_IO_ENABLE_OPENEXR'] = '1'
from dataclasses import asdict, replace
from pathlib import Path
import subprocess
import tempfile
import unittest
import cv2
import numpy as np
import torch
from corridorkey import color_utils as cu
from corridorkey.runtime import _render_predictions_exr_torch, _render_predictions_torch
from corridorkey.video_io import NativeSourceReader, probe_frame_dir_meta, make_checker
from linux_jobs import Options, build_command
from preview_cache import signature


class RenderFeatures(unittest.TestCase):
    def predictions(self):
        # Non-square, padded low-resolution prediction; full-size output is odd.
        meta = dict(model_native_hw=(2,3), output_hw=(5,7), pad=(1,0,1,0),
                    despill_strength=0, cutout_premultiplied=True)
        logits = torch.zeros(1,4,3,4)
        logits[:,0] = .5
        logits[:,1:] = cu.linear_to_asinh(torch.full((1,3,3,4), 2.0))
        checker = torch.from_numpy(make_checker(5,7))
        return meta, logits, checker

    def test_lanczos_output_is_full_size_hdr_and_premultiplied(self):
        meta, logits, checker = self.predictions()
        out = _render_predictions_exr_torch(meta, {'alpha','fg','checker','cutout'}, checker, logits)
        self.assertEqual(out['cutout'].shape, (1,5,7,4))
        np.testing.assert_allclose(out['fg'], 2, atol=1e-5)
        np.testing.assert_allclose(out['cutout'][...,:3], out['fg']*out['cutout'][...,3:4], atol=1e-6)
        self.assertTrue(all(np.isfinite(image).all() for image in out.values()))
        meta['cutout_premultiplied'] = False
        straight = _render_predictions_exr_torch(meta, {'cutout'}, checker, logits)['cutout']
        np.testing.assert_allclose(straight[...,:3], 2, atol=1e-5)
        np.testing.assert_allclose(straight[...,3], .5, atol=1e-6)

    def test_solid_restoration_uses_full_size_original_after_despill(self):
        meta, logits, checker = self.predictions()
        meta['despill_strength'] = 1
        original = torch.arange(105).reshape(1,3,5,7).float()/20-.5
        # Direct threshold checks at native scale isolate restoration from interpolation.
        meta.update(model_native_hw=(5,7), pad=(0,0,0,0))
        logits = torch.zeros(1,4,5,7)
        logits[:,0] = .95
        logits[:,0,:,3:] = .97
        out = _render_predictions_exr_torch(meta, {'fg','cutout'}, checker, logits, original)
        rgb = original[:,[2,1,0]].permute(0,2,3,1).numpy()
        np.testing.assert_array_equal(out['fg'][:,:,3:], rgb[:,:,3:])
        np.testing.assert_allclose(out['fg'][:,:,:3], 0, atol=1e-6)
        np.testing.assert_allclose(out['cutout'][:,:,3:,:3], rgb[:,:,3:]*.97, atol=1e-6)

    def test_video_association_applies_in_selected_encoding(self):
        meta, logits, checker = self.predictions()
        for linear in (False, True):
            meta['cutout_linear'] = linear
            a = _render_predictions_torch(meta, {'cutout'}, checker, logits)['cutout']
            meta['cutout_premultiplied'] = False
            b = _render_predictions_torch(meta, {'cutout'}, checker, logits)['cutout']
            np.testing.assert_allclose(a[...,:3], b[...,:3]*.5, atol=1)
            np.testing.assert_array_equal(a[...,3], b[...,3])
            meta['cutout_premultiplied'] = True

    def test_native_reader_preserves_hdr_detail_and_color(self):
        from color_management import acescg_to_linear709
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'frame.exr'
            rng = np.random.default_rng(5)
            bgr = rng.uniform(-.1,3,(5,7,3)).astype(np.float32)
            cv2.imwrite(str(path), bgr)
            before = path.read_bytes()
            meta = probe_frame_dir_meta(tmp, num_frames=-1, shape_quantum=128, fps=25,
                exr_linear=True, model_scale=.25, input_color_space='acescg')
            reader = NativeSourceReader(tmp,meta)
            try:
                rgb = reader.read([0])[0].transpose(1,2,0)
                np.testing.assert_allclose(rgb, acescg_to_linear709(bgr[...,::-1]), atol=3e-7)
            finally:
                reader.close()
            self.assertEqual(before,path.read_bytes())

    def test_cli_cache_and_display_follow_render_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'source';source.mkdir()
            frame = np.full((5,7,4),(.1,.2,.3,.5),np.float32)
            cv2.imwrite(str(source/'frame.exr'),frame)
            base = Options()
            for changes in (dict(model_scale=.5),dict(model_scale=.25),dict(keep_original=True),dict(cutout_premultiplied=False)):
                options = replace(base,**changes)
                self.assertNotEqual(signature(source,25,asdict(base)),signature(source,25,asdict(options)))
            cmd = build_command(tmp,'python',source,Path(tmp)/'out',replace(base,model_scale=.25,keep_original=True))
            self.assertEqual(cmd[cmd.index('--model_scale')+1], '0.25')
            self.assertIn('--keep_original',cmd)
            self.assertIn('--cutout_premultiplied',cmd)
            import sys
            result = subprocess.run([sys.executable,'scripts/display_frame.py',str(source/'frame.exr'),'rec709','1','1'],check=True,stdout=subprocess.PIPE)
            image = cv2.imdecode(np.frombuffer(result.stdout,np.uint8),cv2.IMREAD_UNCHANGED)
            np.testing.assert_allclose(image[0,0,:3], cu.linear_to_srgb(np.array([.2,.4,.6]))*255, atol=1)
            self.assertEqual(image[0,0,3],127)


if __name__ == '__main__': unittest.main()
