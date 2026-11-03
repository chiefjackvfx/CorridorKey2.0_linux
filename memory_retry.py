"""Bounded, resolution-preserving fallback settings for a fresh CUDA process."""


def oom_retry_overrides(cfg):
    chunk = max(1, int(cfg.hann_chunk))
    smaller = max((n for n in (1, 2, 4, 8, 16, 24, 48) if n <= max(1, chunk // 2)), default=1)
    values = {
        'hann_chunk': smaller,
        'hann_stride': min(max(1, int(cfg.hann_stride)), max(1, smaller // 2)),
        'low_vram_foundation_chunk': 1,
        'low_vram_mlp_chunk_tokens': min(cfg.low_vram_mlp_chunk_tokens, 16384),
        'low_vram_enc_frame_chunk': 1,
        'low_vram_swin_window_batch': min(cfg.low_vram_swin_window_batch, 4),
        'low_vram_full_attn_query_chunk_tokens': min(cfg.low_vram_full_attn_query_chunk_tokens, 512),
        'stage2_batch': 1,
    }
    if cfg.low_vram and all(getattr(cfg, name) == value for name, value in values.items()):
        return None
    return values


def retry_arguments(original, overrides):
    # argparse uses the last supplied value. Preserve every unrelated user flag,
    # including paths containing spaces, and never send arguments through a shell.
    result = list(original) + ['--low_vram']
    for name, value in overrides.items():
        result.extend([f'--{name}', str(value)])
    return result
