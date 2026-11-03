import unittest
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
from pathlib import Path

from memory_retry import oom_retry_overrides, retry_arguments


def config(**changes):
    values = dict(hann_chunk=24, hann_stride=12, low_vram=True,
                  low_vram_foundation_chunk=4, low_vram_mlp_chunk_tokens=65536,
                  low_vram_enc_frame_chunk=1, low_vram_swin_window_batch=16,
                  low_vram_full_attn_query_chunk_tokens=2048, stage2_batch=1)
    values.update(changes)
    return SimpleNamespace(**values)


class MemoryRecovery(unittest.TestCase):
    def test_reported_4k_budget_avoids_24_frame_window(self):
        from corridorkey.runtime import select_vram_profile
        chunk, stride, low, estimate = select_vram_profile((2176, 4096), 92, 24.7)
        self.assertEqual((chunk, stride, low), (8, 4, True))
        self.assertLess(estimate*1.3+2, 24.7)

    def test_retries_reduce_monotonically_and_terminate(self):
        cfg = config()
        chunks = []
        for _ in range(12):
            retry = oom_retry_overrides(cfg)
            if retry is None:
                break
            chunks.append(retry['hann_chunk'])
            cfg = config(**{**vars(cfg), **retry, 'low_vram': True})
        else:
            self.fail('Retry never terminates')
        self.assertEqual(chunks, [8, 4, 2, 1])
        self.assertIsNone(oom_retry_overrides(cfg))

    def test_fallback_preserves_user_paths_and_resolution(self):
        original = ['--input', '/clip with spaces', '--output_dir', '/out folder', '--model_scale', '1.0']
        args = retry_arguments(original, oom_retry_overrides(config()))
        self.assertEqual(args[:len(original)], original)
        self.assertEqual(args.count('--model_scale'), 1)
        self.assertIn('--low_vram', args)

    def test_cli_restarts_oom_but_not_other_errors(self):
        import infer
        import torch
        def fail(*args, **kwargs):
            args[3].hann_chunk = 24
            args[3].hann_stride = 12
            raise torch.OutOfMemoryError('injected OOM')
        with patch('sys.argv', ['infer.py', '--input', '/a clip', '--output_dir', '/result']), \
             patch.object(infer.torch.cuda, 'is_available', return_value=True), \
             patch.object(infer, 'require_ffmpeg'), patch.object(infer, 'load_model'), \
             patch.object(infer, 'run_inference', side_effect=fail), \
             patch.object(infer.os, 'execv') as restart:
            infer.main()
            args = restart.call_args.args[1]
            self.assertEqual(args[args.index('--hann_chunk')+1], '8')
            self.assertIn('/a clip', args)
        with patch('sys.argv', ['infer.py', '--input', '/a clip', '--output_dir', '/result']), \
             patch.object(infer.torch.cuda, 'is_available', return_value=True), \
             patch.object(infer, 'require_ffmpeg'), patch.object(infer, 'load_model'), \
             patch.object(infer, 'run_inference', side_effect=ValueError('bad input')), \
             patch.object(infer.os, 'execv') as restart:
            with self.assertRaisesRegex(ValueError, 'bad input'):
                infer.main()
            restart.assert_not_called()

    def test_cleanup_does_not_mask_cuda_error(self):
        import torch
        from corridorkey import runtime
        from unittest.mock import MagicMock
        cfg = runtime.InferenceConfig(auto_vram=False, outputs={'alpha'})
        writer = MagicMock()
        writer.release.side_effect = RuntimeError('empty FFmpeg output')
        with tempfile.TemporaryDirectory() as temp:
            cfg.temp_dir = Path(temp)/'scratch'
            meta = dict(num_frames=24, shape_hw=(32,32), output_hw=(32,32), native_fps=25)
            with patch.object(runtime, 'probe_video_meta', return_value=meta), \
                 patch.object(runtime, 'ThreadedVideoWriter', return_value=writer), \
                 patch.object(runtime, '_phase1_setup', side_effect=torch.OutOfMemoryError('original CUDA failure')), \
                 patch.object(runtime.torch.cuda, 'empty_cache'):
                with self.assertRaisesRegex(torch.OutOfMemoryError, 'original CUDA failure'):
                    runtime.run_inference(MagicMock(), 'clip.mp4', temp, cfg,
                                          runtime.WriterConfig(), initial_hint_path=None, hint_video_path=None)
                writer.release.assert_called_once()


if __name__ == '__main__':
    unittest.main()
