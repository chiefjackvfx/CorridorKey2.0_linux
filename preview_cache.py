"""Session-local bounded disk cache; keys include source/hint revisions and settings."""
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import shutil


def fingerprint(value):
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    try:
        paths = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in {'.png','.jpg','.jpeg','.exr'}) if path.is_dir() else [path]
        return [str(path), [(str(p.name), p.stat().st_size, p.stat().st_mtime_ns) for p in paths]]
    except OSError:
        return [str(path), 'missing']


def signature(source, fps, options):
    relevant = {key: options.get(key) for key in ('hint_mode','hint_path','hint_quality','despill','linear','input_color_space','model_scale','cutout_premultiplied','keep_original')}
    if relevant['hint_mode'] == 'none':
        relevant['hint_path'] = ''
        relevant['hint_quality'] = None
    hint = fingerprint(relevant['hint_path'])
    data = [1, fingerprint(source), fps, relevant, hint]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class PreviewCache:
    def __init__(self, limit=2*1024**3):
        self.limit = limit
        self.entries = OrderedDict()
        self.size = 0

    def get(self, key):
        entry = self.entries.get(key)
        if entry and all(Path(p).is_file() for p in entry[0].values()):
            self.entries.move_to_end(key)
            return entry[0]
        if entry:
            self.remove(key)
        return None

    def remove(self, key):
        images, directory, size = self.entries.pop(key)
        self.size -= size
        shutil.rmtree(directory, ignore_errors=True)

    def put(self, key, images, directory):
        if not all(Path(p).is_file() for p in images.values()):
            return False
        # Keep only finished display images, not decoded sources or EXR scratch.
        keep = {Path(p).name for p in images.values()}
        for path in Path(directory).iterdir():
            if path.name not in keep:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        size = sum(Path(p).stat().st_size for p in images.values())
        if size > self.limit:
            return False
        if key in self.entries:
            self.remove(key)
        while self.entries and self.size+size > self.limit:
            self.remove(next(iter(self.entries)))
        self.entries[key] = (images, Path(directory), size)
        self.size += size
        return True

    def clear(self):
        for key in list(self.entries):
            self.remove(key)
