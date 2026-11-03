"""Dependency-free command construction shared by the desktop UI and tests."""
from dataclasses import dataclass
from pathlib import Path
import uuid

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.mxf', '.m4v'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.exr'}


@dataclass(frozen=True)
class Options:
    outputs: tuple[str, ...] = ('alpha', 'fg', 'checker', 'cutout')
    output_format: str = 'video'
    memory: str = 'auto'
    hint_mode: str = 'none'
    hint_path: str = ''
    hint_quality: float = .95
    carry: bool = True
    despill: float = .5
    fps: float = 25
    linear: bool = True
    num_frames: int = -1
    temporal_frames: int = 0
    carry_quality: float = .95
    cutout_linear: bool = False
    model_scale: float = 1.0
    cutout_premultiplied: bool = True
    keep_original: bool = False
    input_color_space: str = "rec709"
    save_sibling: bool = False


def validate_source(source):
    source = Path(source).expanduser().resolve()
    if source.is_file() and source.suffix.lower() in VIDEO_EXTENSIONS:
        return source
    if source.is_dir() and any(p.suffix.lower() in IMAGE_EXTENSIONS for p in source.iterdir() if p.is_file()):
        return source
    raise ValueError(f'Choose a video or a folder containing PNG/JPEG/EXR frames: {source}')


def build_command(root, python, source, destination, options):
    source = validate_source(source)
    if not options.outputs or set(options.outputs) - {'alpha', 'fg', 'checker', 'cutout'}:
        raise ValueError('Choose at least one valid output channel.')
    if options.output_format not in ('video', 'exr') or options.memory not in ('auto', 'low'):
        raise ValueError('Invalid output format or memory profile.')
    if options.hint_mode not in ('none', 'first', 'video'):
        raise ValueError('Invalid hint mode.')
    if not 0 <= options.despill <= 1 or not 0 <= options.hint_quality <= 1:
        raise ValueError('Despill and hint quality must be between zero and one.')
    if options.fps <= 0 or options.num_frames == 0 or options.num_frames < -1:
        raise ValueError('Frame rate and frame limit must be positive (or -1 for all frames).')
    if not 0 <= options.temporal_frames <= 80 or not 0 <= options.carry_quality <= 1:
        raise ValueError('Time awareness must be 0–80 and internal hint strength 0–1.')
    if options.input_color_space not in ('rec709', 'acescg'):
        raise ValueError('Unsupported input color space.')
    if options.input_color_space == 'acescg' and not source.is_dir():
        raise ValueError('ACEScg input requires an image sequence.')
    if options.model_scale not in (1.0, 0.5, 0.25):
        raise ValueError("Internal resolution must be full, half, or quarter.")
    command = [str(python), '-u', str(Path(root) / 'infer.py'), '--input', str(source),
               '--output_dir', str(destination), '--outputs', *options.outputs,
               '--temp_dir', str(Path(destination) / '.scratch'),
               '--output_format', options.output_format, '--despill_strength', str(options.despill),
               '--frame_dir_fps', str(options.fps), '--num_frames', str(options.num_frames)]
    command += ['--carry_hint_quality', str(options.carry_quality), '--input_color_space', options.input_color_space]
    if options.memory == 'low':
        command += ['--low_vram']
    chunk = options.temporal_frames or (16 if options.memory == 'low' else 0)
    if chunk:
        command += ['--hann_chunk', str(chunk), '--hann_stride', str(max(1, chunk // 2))]
    command += ['--model_scale', str(options.model_scale)]
    if options.cutout_premultiplied:
        command += ['--cutout_premultiplied']
    if options.keep_original:
        command += ['--keep_original']
    if options.cutout_linear:
        command += ['--cutout_linear']
    if options.hint_mode != 'none':
        hint = Path(options.hint_path).expanduser()
        if not options.hint_path or not hint.exists():
            raise ValueError('Select an existing hint image, video, or frame folder.')
        command += ['--hint_first_frame' if options.hint_mode == 'first' else '--hint_video',
                    str(hint.resolve()), '--hint_quality', str(options.hint_quality)]
    if not options.carry:
        command += ['--no_carry_hint']
    if options.linear:
        command += ['--frame_dir_linear']
    return command


def new_destination(base, source):
    """A fresh directory per job prevents same-name clips overwriting results."""
    base = Path(base).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    destination = base / f'{Path(source).stem}_{uuid.uuid4().hex[:12]}'
    destination.mkdir()
    return destination
