"""Versioned desktop pass folders and transactional publication of finished renders."""
from dataclasses import dataclass
from pathlib import Path
import ctypes
import errno
import json
import os
import re
import shutil
import tempfile
import uuid
from app_cache import cache_directory

PASSES=('fg','cutout','checker','alpha')
IMAGES={'.png','.jpg','.jpeg','.exr'}


def write_json(path,value):
    path=Path(path);temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(value,indent=2)+'\n')
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def source_frames(source):
    return sorted(p for p in Path(source).iterdir() if p.is_file() and p.suffix.lower() in IMAGES)


def source_start(source):
    source=Path(source)
    if source.is_file():return 1001
    frames=source_frames(source)
    if not frames:raise ValueError('The source sequence has no supported frames.')
    stem=frames[0].stem
    number=re.search(r'(?:^|[._])(-?\d+)$',stem) or re.search(r'(\d+)$',stem)
    return int(number[1]) if number else 1001


@dataclass(frozen=True)
class ExportPlan:
    parent: str
    stem: str
    version: int
    width: int
    first_frame: int
    output_format: str
    passes: tuple[str,...]

    @property
    def folders(self):
        return {key:str(Path(self.parent)/f'{self.stem}_{key}_v{self.version:0{self.width}d}') for key in self.passes}

    def filename(self,key,index=0):
        name=Path(self.folders[key]).name
        if self.output_format=='exr':return f'{name}.{self.first_frame+index:04d}.exr'
        return name+('.mov' if key=='cutout' else '.mp4')

    @property
    def preview(self):
        return [str(Path(folder)/self.filename(key)) for key,folder in self.folders.items()]


def plan_export(source,base,passes,*,sibling=False,output_format='exr'):
    source=Path(source).expanduser().resolve()
    if set(passes)-set(PASSES):raise ValueError('Unknown export pass.')
    passes=tuple(key for key in PASSES if key in passes)
    if not passes:raise ValueError('Choose at least one export pass.')
    if output_format not in ('exr','video'):raise ValueError('Choose EXR or video output.')
    if not sibling and not str(base).strip():raise ValueError('Choose an output folder.')
    parent=source.parent if sibling else Path(base).expanduser().resolve()
    if parent.exists() and not parent.is_dir():raise ValueError('Output location is not a folder.')
    name=source.name if source.is_dir() else source.stem
    versioned=re.fullmatch(r'(.+)_v(\d+)',name,re.IGNORECASE)
    stem=versioned[1] if versioned else name
    version=int(versioned[2]) if versioned else 1
    width=max(3,len(versioned[2])) if versioned else 3
    pattern=re.compile(re.escape(stem)+r'_(?:fg|cutout|checker|alpha)_v(\d+)$',re.IGNORECASE)
    lock_pattern=re.compile(r'\.'+re.escape(stem)+r'_ck2_v(\d+)\.lock$',re.IGNORECASE)
    if parent.is_dir():
        for path in parent.iterdir():
            match=pattern.fullmatch(path.name) or lock_pattern.fullmatch(path.name)
            if match:version=max(version,int(match[1])+1)
    return ExportPlan(str(parent),stem,version,width,source_start(source),output_format,passes)


class Reservation:
    def __init__(self,plan,lock,owner):self.plan=plan;self.lock=Path(lock);self.owner=owner

    @classmethod
    def reserve(cls,source,base,passes,*,sibling=False,output_format='exr',owner=None):
        owner=owner or uuid.uuid4().hex
        while True:
            plan=plan_export(source,base,passes,sibling=sibling,output_format=output_format)
            parent=Path(plan.parent);parent.mkdir(parents=True,exist_ok=True)
            lock=parent/f'.{plan.stem}_ck2_v{plan.version:0{plan.width}d}.lock'
            try:lock.mkdir()
            except FileExistsError:continue
            try:
                write_json(lock/'owner.json',{'owner':owner})
                if any(Path(folder).exists() or Path(folder).is_symlink() for folder in plan.folders.values()):
                    shutil.rmtree(lock);continue
                return cls(plan,lock,owner)
            except BaseException:
                shutil.rmtree(lock,ignore_errors=True);raise

    def close(self):release_lock(self.lock,self.owner)


def release_lock(lock,owner):
    if not lock:return
    lock=Path(lock)
    try:
        if json.loads((lock/'owner.json').read_text()).get('owner')==owner:
            shutil.rmtree(lock)
    except FileNotFoundError:pass


def rename_exclusive(source,destination):
    """Linux atomic directory publication: never replace an existing directory."""
    if os.name == 'nt':
        # Windows rename fails when any destination already exists.
        os.rename(source, destination)
        return
    function=getattr(ctypes.CDLL(None,use_errno=True),'renameat2',None)
    if function is None:raise RuntimeError('This Linux system does not support atomic exclusive folder publication.')
    function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    function.restype=ctypes.c_int
    if function(-100,os.fsencode(source),-100,os.fsencode(destination),1):
        code=ctypes.get_errno()
        raise OSError(code,os.strerror(code),str(destination))


def copy_exclusive(source,destination):
    try:os.link(source,destination)
    except OSError as exc:
        if exc.errno not in (errno.EXDEV,errno.EPERM,errno.EACCES,errno.ENOTSUP,errno.EMLINK):raise
        with open(source,'rb') as src,open(destination,'xb') as dst:
            shutil.copyfileobj(src,dst,1024*1024)


def runtime_passes(directory,outputs,output_format):
    directory=Path(directory);result={}
    for key in outputs:
        suffix='checker_comp_despill[0-9][0-9][0-9]' if key=='checker' else key
        ending='_exr' if output_format=='exr' else ('.mov' if key=='cutout' else '.mp4')
        found=list(directory.glob(f'*_{suffix}{ending}'))
        if len(found)!=1:raise ValueError(f'Missing or ambiguous completed {key} output.')
        files=sorted(found[0].glob('*.exr')) if output_format=='exr' else found
        if not files or any(not p.is_file() or p.is_symlink() or p.stat().st_size==0 for p in files):
            raise ValueError(f'The {key} output is empty or invalid.')
        result[key]=files
    return result


def validate_passes(files,output_format,expected_frames=None):
    """Decode generated EXRs before publishing; preserve their original bytes."""
    import cv2
    import numpy as np
    count=None;geometry=None
    for key,paths in files.items():
        if output_format=='exr':
            if count is not None and count!=len(paths):raise ValueError('Export pass frame counts differ.')
            count=len(paths)
            if expected_frames and count!=expected_frames:raise ValueError('Export frame count does not match the source range.')
            for path in paths:
                pixels=cv2.imread(str(path),cv2.IMREAD_UNCHANGED)
                if pixels is None or not np.isfinite(pixels).all():raise ValueError(f'Invalid EXR frame: {path}')
                channels=1 if pixels.ndim==2 else pixels.shape[-1]
                if channels!={'alpha':1,'fg':3,'checker':3,'cutout':4}[key]:raise ValueError(f'Wrong channel count in {key} EXR.')
                if geometry is None:geometry=pixels.shape[:2]
                if pixels.shape[:2]!=geometry:raise ValueError('Export pass dimensions differ.')
        else:
            cap=cv2.VideoCapture(str(paths[0]))
            try:
                if not cap.isOpened():raise ValueError(f'Cannot open {key} video.')
                frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                hw=(int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)))
                if frames<=0 or min(hw)<=0:raise ValueError(f'Invalid {key} video metadata.')
                if expected_frames and frames!=expected_frames:raise ValueError('Video frame count does not match the source range.')
                if count is not None and count!=frames:raise ValueError('Video pass frame counts differ.')
                if geometry is not None and geometry!=hw:raise ValueError('Video pass dimensions differ.')
                count=frames;geometry=hw
            finally:cap.release()
    return count,geometry


def publish_passes(reservation,files,record=None):
    """Prepare every pass, then publish each complete directory; roll back on failure."""
    plan=reservation.plan;temporary=[];published=[]
    stage_parent=cache_directory('publish')
    # Exclusive rename must stay on the destination filesystem. For a different
    # filesystem, keep only the short-lived publication stage in its local .cache.
    if stage_parent.stat().st_dev != Path(plan.parent).stat().st_dev:
        stage_parent=cache_directory('ck2-publish',plan.parent)
    try:
        for key in plan.passes:
            stage=Path(tempfile.mkdtemp(prefix='ck2-publish-',dir=stage_parent));temporary.append(stage)
            for index,source in enumerate(files[key]):
                copy_exclusive(source,stage/plan.filename(key,index))
        for key,stage in zip(plan.passes,temporary):
            target=Path(plan.folders[key]);inode=stage.stat().st_ino
            rename_exclusive(stage,target);published.append((target,inode))
        if record:record(plan.folders)
        return plan.folders
    except BaseException:
        for target,inode in reversed(published):
            # Only remove directories created by this attempt, with no foreign files.
            expected={plan.filename(key,i) for key in plan.passes if Path(plan.folders[key])==target for i in range(len(files[key]))}
            if target.exists() and target.stat().st_ino==inode and {p.name for p in target.iterdir()}==expected:
                shutil.rmtree(target)
        raise
    finally:
        for stage in temporary:
            if stage.exists():shutil.rmtree(stage,ignore_errors=True)
