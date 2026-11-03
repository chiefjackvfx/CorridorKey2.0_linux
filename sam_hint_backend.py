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
