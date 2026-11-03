"""Image preparation and hint masks, independent of Qt and the CUDA models."""
from pathlib import Path
import os
import cv2
import numpy as np
from color_management import acescg_to_linear709


def load_hint_frame(source, *, linear=True, color_space='rec709', max_dimension=1600):
    source = Path(source)
    if source.is_dir():
        paths = sorted(p for p in source.iterdir() if p.suffix.lower() in {'.png','.jpg','.jpeg','.exr'})
        if not paths:
            raise ValueError('The input sequence has no supported frames.')
        image = cv2.imread(str(paths[0]),cv2.IMREAD_UNCHANGED)
    else:
        cap = cv2.VideoCapture(str(source))
        try:
            ok,image = cap.read()
            if not ok:
                image=None
        finally:
            cap.release()
        linear=False
    if image is None:
        raise ValueError('Cannot decode the first source frame.')
    native_hw=image.shape[:2]
    if image.ndim==2:
        image=np.repeat(image[...,None],3,axis=-1)
    image=image[...,:3]
    if image.dtype==np.uint8:
        image=image.astype(np.float32)/255
    elif image.dtype==np.uint16:
        image=image.astype(np.float32)/65535
    else:
        image=image.astype(np.float32)
    if color_space=='acescg' and source.is_dir():
        image=acescg_to_linear709(image[...,::-1])[...,::-1]
        linear=True
    if linear:
        image=np.maximum(image,0)
        image=np.where(image<=.0031308,image*12.92,1.055*np.power(image,1/2.4)-.055)
    h,w=native_hw
    scale=min(1,max_dimension/max(h,w))
    image=cv2.resize(image,(max(1,round(w*scale)),max(1,round(h*scale))),interpolation=cv2.INTER_AREA)
    return (np.clip(image,0,1)*255).astype(np.uint8), native_hw


def screen_mask(bgr):
    """Rough green/blue-screen seed. SAM is the preferred subject generator."""
    rgb=bgr[...,::-1].astype(np.float32)/255
    border=np.concatenate([rgb[0],rgb[-1],rgb[:,0],rgb[:,-1]],axis=0)
    screen=int(np.argmax(np.median(border,axis=0)))
    if screen not in (1,2):
        raise ValueError('No green/blue screen detected. Use SAM 3.1 or start with a blank mask.')
    other=np.max(np.delete(rgb,screen,axis=-1),axis=-1)
    dominance=rgb[...,screen]-other
    alpha=1-np.clip((dominance-.03)/.18,0,1)
    return (alpha*255).astype(np.uint8)


def union_sam_masks(outputs, hw):
    masks=outputs.get('out_binary_masks')
    if hasattr(masks,'detach'):
        masks=masks.detach().cpu().numpy()
    if masks is None or len(masks)==0:
        raise ValueError('SAM found no matching subject. Try a simpler description, such as person.')
    masks=np.asarray(masks,dtype=bool)
    if masks.ndim==4 and masks.shape[1]==1:
        masks=masks[:,0]
    if masks.ndim!=3:
        raise ValueError(f'Unexpected SAM mask dimensions: {masks.shape}')
    mask=np.any(masks,axis=0).astype(np.uint8)*255
    if not mask.any():
        raise ValueError('SAM returned an empty mask. Try another subject description.')
    return cv2.resize(mask,(hw[1],hw[0]),interpolation=cv2.INTER_NEAREST)


def save_hint(mask, native_hw, path):
    """Write an atomic native-size grayscale PNG without altering the source."""
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    if mask.ndim!=2:
        raise ValueError('A hint must be a single grayscale channel.')
    image=cv2.resize(mask,(native_hw[1],native_hw[0]),interpolation=cv2.INTER_LINEAR)
    ok,data=cv2.imencode('.png',image)
    if not ok:
        raise ValueError('Cannot encode the hint.')
    import uuid
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_bytes(data.tobytes())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)
