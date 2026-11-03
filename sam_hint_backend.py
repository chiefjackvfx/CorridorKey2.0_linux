"""Narrow compatibility adapter for the pinned official SAM 3.1 predictor."""
import functools
import inspect


def adapt_session_arguments(predictor):
    # The shared base predictor forwards this SAM 3 option unconditionally;
    # the multiplex model at our pinned commit has no such parameter.
    original=predictor.model.init_state
    if 'offload_state_to_cpu' not in inspect.signature(original).parameters:
        @functools.wraps(original)
        def init_state(*args,offload_state_to_cpu=False,**kwargs):
            if offload_state_to_cpu:
                raise ValueError('SAM 3.1 state offloading is not supported by this model.')
            return original(*args,**kwargs)
        predictor.model.init_state=init_state
    return predictor


def adapt_interactive_frames(predictor):
    """Keep newly clicked objects on a frame with no prior text detection.

    The pinned multiplex helper returns early when no cached frame exists,
    dropping the first point mask even though the tracker computed it.
    """
    original=predictor.model._build_sam2_output
    @functools.wraps(original)
    def build_output(inference_state,frame_idx,refined_obj_id_to_mask=None):
        if refined_obj_id_to_mask is not None:
            inference_state['cached_frame_outputs'].setdefault(frame_idx,{})
        return original(inference_state,frame_idx,refined_obj_id_to_mask)
    predictor.model._build_sam2_output=build_output
    return predictor


def prepare_sam_imports():
    """Install narrow portable SAM helpers before importing its eager package.

    Windows wheels do not supply Triton with this Torch stack. Linux keeps its
    native kernels unless Triton is missing or CK_SAM_PORTABLE_OPS=1 is set.
    """
    import importlib.util
    import os
    import sys
    from types import ModuleType
    portable = (os.name == 'nt' or os.environ.get('CK_SAM_PORTABLE_OPS') == '1'
                or importlib.util.find_spec('triton') is None)
    if not portable:
        return False
    from sam_portable_ops import distance_transform, connected_components, generic_nms
    helpers = {
        'sam3.model.edt': ('edt_triton', distance_transform),
        'sam3.perflib.triton.connected_components': ('connected_components_triton', connected_components),
        'sam3.perflib.triton.nms': ('nms_triton', generic_nms),
    }
    for name, (symbol, function) in helpers.items():
        module = ModuleType(name)
        module.__doc__ = 'CK2 portable SAM mask helper; source submodule remains unchanged.'
        setattr(module, symbol, function)
        sys.modules.setdefault(name, module)
    return True
