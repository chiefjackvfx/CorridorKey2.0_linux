"""SAM prompt validation and object-mask selection, independent of Qt/CUDA."""
import numpy as np
import cv2

PALETTE=((71,190,255),(255,126,82),(169,123,255),(77,222,140),
         (255,213,78),(244,116,188),(74,222,222),(188,212,102),
         (115,142,255),(234,184,91),(223,100,245),(95,211,180),
         (237,126,137),(110,181,129),(159,217,238),(212,209,164))


def sam_instances(outputs, hw):
    if not outputs:
        raise ValueError('SAM returned no matching selection. Add a positive point or try another prompt.')
    masks=outputs.get('out_binary_masks')
    if hasattr(masks,'detach'):masks=masks.detach().cpu().numpy()
    if masks is None or len(masks)==0:
        raise ValueError('SAM found no matching selection. Add a positive point or try another prompt.')
    masks=np.asarray(masks,dtype=bool)
    if masks.ndim==4 and masks.shape[1]==1:masks=masks[:,0]
    if masks.ndim!=3:raise ValueError(f'Unexpected SAM mask dimensions: {masks.shape}')
    ids=outputs.get('out_obj_ids',np.arange(1,len(masks)+1))
    if hasattr(ids,'detach'):ids=ids.detach().cpu().numpy()
    if len(ids)!=len(masks):raise ValueError('SAM object IDs do not match its masks.')
    result={}
    for ident,mask in zip(ids,masks):
        if mask.any():
            result[int(ident)]=cv2.resize(mask.astype(np.uint8)*255,(hw[1],hw[0]),interpolation=cv2.INTER_NEAREST)
    if not result:raise ValueError('SAM returned an empty selection. Try another point or prompt.')
    return result


def combine_masks(objects, selected, hw):
    result=np.zeros(hw,np.uint8)
    for ident in selected:
        if ident in objects:np.maximum(result,objects[ident],out=result)
    return result


def preserve_brush_changes(current, old_base, new_base):
    return np.clip(new_base.astype(np.int16)+current.astype(np.int16)-old_base.astype(np.int16),0,255).astype(np.uint8)


def pick_object(objects,x,y):
    # Smaller objects win overlapping pixels, making nested detections accessible.
    hits=[ident for ident,mask in objects.items() if mask[min(mask.shape[0]-1,max(0,int(y*mask.shape[0]))),
                                                      min(mask.shape[1]-1,max(0,int(x*mask.shape[1])))]>0]
    return min(hits,key=lambda ident:np.count_nonzero(objects[ident])) if hits else None


def prompt_requests(recipe):
    """Validated request sequence: optional concept/box, then per-object points.

    Replay in a fresh one-frame SAM session for deterministic undo and recovery.
    Point labels are 1=include, 0=exclude; box is normalized xywh.
    """
    result=[]
    text=recipe.get('text')
    box=recipe.get('box')
    if text and box:raise ValueError('Choose text or a box as the starting selection.')
    if text:result.append(dict(text=str(text)))
    if box is not None:
        if len(box)!=4:raise ValueError('A selection box needs four coordinates.')
        x,y,w,h=map(float,box)
        if not all(np.isfinite([x,y,w,h])) or min(x,y)<0 or min(w,h)<=0 or x+w>1.000001 or y+h>1.000001:
            raise ValueError('Selection box must lie inside the image.')
        result.append(dict(bounding_boxes=[[x,y,w,h]],bounding_box_labels=[1]))
    seen=set()
    for group in recipe.get('groups',[]):
        ident=int(group['id'])
        if ident in seen:raise ValueError('Each object must have one point group.')
        seen.add(ident)
        points=group.get('points',[]);labels=group.get('labels',[])
        if len(points)!=len(labels) or not points:raise ValueError('Each point needs an include/exclude label.')
        array=np.asarray(points,dtype=np.float32)
        if array.shape!=(len(points),2) or not np.isfinite(array).all() or array.min()<0 or array.max()>1:
            raise ValueError('Selection points must lie inside the image.')
        if any(label not in (0,1) for label in labels):raise ValueError('Point labels must be include or exclude.')
        if not text and box is None and not any(labels):raise ValueError('Start a new object with a positive point.')
        result.append(dict(points=array.tolist(),point_labels=list(labels),obj_id=ident,clear_old_points=True))
    if not result:raise ValueError('Type a subject, add an include point, or drag a box first.')
    return result
