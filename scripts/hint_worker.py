#!/usr/bin/env python3
"""Isolated hint generation worker. SAM owns the GPU only while the editor is open."""
import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['OPENCV_IO_ENABLE_OPENEXR']='1'
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
if not os.environ.get('PYTORCH_ALLOC_CONF') and not os.environ.get('PYTORCH_CUDA_ALLOC_CONF'):
    os.environ['PYTORCH_ALLOC_CONF']='expandable_segments:True'


def main():
    import cv2
    import numpy as np
    from hint_tools import load_hint_frame,screen_mask,union_sam_masks
    predictor=None
    loaded_checkpoint=None
    output=sys.stdout
    for line in sys.stdin:
        request=json.loads(line)
        response={'id':request['id']}
        exit_after_reply=False
        try:
            with contextlib.redirect_stdout(sys.stderr):
                work=Path(request['work']);work.mkdir(parents=True,exist_ok=True)
                op=request['op']
                if op=='load':
                    image,hw=load_hint_frame(request['source'],linear=request['linear'],color_space=request['color_space'])
                    cv2.imwrite(str(work/'frame.png'),image)
                    mask=None
                    seed_kind='existing matte'
                    if request.get('seed'):
                        seed=Path(request['seed'])
                        if seed.is_dir():
                            paths=sorted(p for p in seed.iterdir() if p.suffix.lower() in {'.png','.jpg','.jpeg','.exr'})
                            seed=paths[0] if paths else seed
                        candidate=cv2.imread(str(seed),cv2.IMREAD_UNCHANGED)
                        if candidate is not None:
                            if candidate.ndim==3:
                                candidate=candidate[...,3] if candidate.shape[2]==4 else candidate[...,0]
                            if candidate.dtype==np.uint16:
                                candidate=(candidate.astype(np.float32)/257).astype(np.uint8)
                            elif candidate.dtype!=np.uint8:
                                candidate=(np.clip(candidate,0,1)*255).astype(np.uint8)
                            mask=cv2.resize(candidate,(image.shape[1],image.shape[0]),interpolation=cv2.INTER_LINEAR)
                    if mask is None:
                        try:
                            mask=screen_mask(image)
                            seed_kind='rough screen mask'
                        except ValueError:
                            mask=np.zeros(image.shape[:2],np.uint8)
                            seed_kind='blank mask'
                    cv2.imwrite(str(work/'mask.png'),mask)
                    response.update(image=str(work/'frame.png'),mask=str(work/'mask.png'),native_hw=hw,seed_kind=seed_kind)
                elif op in ('sam','screen'):
                    image=cv2.imread(request['image'],cv2.IMREAD_COLOR)
                    if image is None:
                        raise ValueError('The editor reference image is missing.')
                    if op=='screen':
                        mask=screen_mask(image)
                    else:
                        checkpoint=Path(request['checkpoint']).expanduser().resolve()
                        if not checkpoint.is_file():
                            raise ValueError('Choose the downloaded sam3.1_multiplex.pt checkpoint first.')
                        if predictor is None or loaded_checkpoint!=str(checkpoint):
                            if predictor is not None:
                                raise ValueError('Close and reopen the editor before changing a loaded SAM checkpoint.')
                            import torch
                            if not torch.cuda.is_available():
                                raise ValueError('SAM 3.1 requires access to the NVIDIA CUDA GPU.')
                            free,total=torch.cuda.mem_get_info()
                            if free < 8*1024**3:
                                raise ValueError(f'Only {free/1024**3:.1f} GiB GPU memory free. Free memory in other GPU apps before loading SAM.')
                            from sam_hint_backend import prepare_sam_imports
                            prepare_sam_imports()
                            from sam3.model_builder import build_sam3_predictor
                            predictor=build_sam3_predictor(checkpoint_path=str(checkpoint),version='sam3.1',
                                compile=False,warm_up=False,use_fa3=False,use_rope_real=False,async_loading_frames=False)
                            from sam_hint_backend import adapt_session_arguments,adapt_interactive_frames
                            adapt_session_arguments(predictor)
                            adapt_interactive_frames(predictor)
                            loaded_checkpoint=str(checkpoint)
                        # SAM 3.1's official predictor accepts numeric JPEG-frame directories.
                        with tempfile.TemporaryDirectory(dir=work,prefix='sam-input-') as tmp:
                            cv2.imwrite(str(Path(tmp)/'00000.jpg'),image,[cv2.IMWRITE_JPEG_QUALITY,98])
                            session=predictor.handle_request({'type':'start_session','resource_path':tmp,
                                'offload_video_to_cpu':True})['session_id']
                            try:
                                from hint_selection import prompt_requests,sam_instances
                                recipe=request.get('recipe') or {'text':request.get('prompt','person'),'groups':[]}
                                for prompt in prompt_requests(recipe):
                                    result=predictor.handle_request({'type':'add_prompt','session_id':session,
                                        'frame_index':0,**prompt})
                                instances=sam_instances(result['outputs'],image.shape[:2])
                                mask=np.maximum.reduce(list(instances.values()))
                                objects=[]
                                for ident,instance in instances.items():
                                    target=work/f'object-{request["id"]}-{ident}.png'
                                    cv2.imwrite(str(target),instance)
                                    objects.append({'id':ident,'mask':str(target)})
                                response['objects']=objects
                            finally:
                                predictor.handle_request({'type':'close_session','session_id':session})
                    target=work/f'mask-{request["id"]}.png'
                    cv2.imwrite(str(target),mask)
                    response['mask']=str(target)
                else:
                    raise ValueError('Unsupported hint operation.')
        except Exception as exc:
            response['error']=str(exc)
            if type(exc).__name__ in ('OutOfMemoryError','AcceleratorError'):
                response['error']='SAM exhausted GPU memory. Unload models in other GPU apps, then generate again.'
                exit_after_reply=True
        output.write(json.dumps(response)+'\n');output.flush()
        if exit_after_reply:
            return


if __name__=='__main__': main()
