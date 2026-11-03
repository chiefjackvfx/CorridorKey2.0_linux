"""Portable mask helpers for the pinned SAM source when Triton is unavailable.

Only postprocessing runs on CPU; results return to the input CUDA device.
This module does not replace Triton globally or alter the SAM submodule.
"""


def distance_transform(data):
    import numpy as np
    import torch
    from scipy.ndimage import distance_transform_edt
    if data.ndim != 3:
        raise ValueError('Distance transform expects B,H,W masks.')
    arrays = data.detach().bool().cpu().numpy()
    result = np.empty(arrays.shape, dtype=np.float32)
    for index, mask in enumerate(arrays):
        # The upstream kernel uses a finite infinity for all-foreground masks.
        result[index] = 1e9 if mask.all() else distance_transform_edt(mask)
    return torch.from_numpy(result).to(device=data.device)


def connected_components(data):
    import numpy as np
    import torch
    from scipy.ndimage import label
    shape = tuple(data.shape)
    if data.ndim == 4 and data.shape[1] == 1:
        masks = data[:, 0]
    elif data.ndim == 3:
        masks = data
    else:
        raise ValueError('Connected components expects B,H,W or B,1,H,W masks.')
    arrays = masks.detach().bool().cpu().numpy()
    labels = np.zeros(arrays.shape, dtype=np.int32)
    counts = np.zeros(arrays.shape, dtype=np.int32)
    for index, mask in enumerate(arrays):
        components, _ = label(mask, structure=np.ones((3, 3), dtype=np.uint8))
        sizes = np.bincount(components.ravel())
        sizes[0] = 0
        labels[index] = components
        counts[index] = sizes[components]
    return (torch.from_numpy(labels).reshape(shape).to(data.device),
            torch.from_numpy(counts).reshape(shape).to(data.device))


def generic_nms(ious, scores, iou_threshold):
    import torch
    if scores.ndim != 1 or tuple(ious.shape) != (scores.numel(), scores.numel()):
        raise ValueError('NMS expects N scores and an NxN IoU matrix.')
    # Match SAM's CPU ordering and threshold behavior, including score ties.
    import numpy as np
    values = ious.detach().float().cpu().numpy()
    order = scores.detach().float().cpu().numpy().argsort()[::-1]
    kept = []
    while order.size:
        index = int(order[0]); kept.append(index)
        order = order[1:][values[index, order[1:]] <= iou_threshold]
    return torch.tensor(kept, dtype=torch.int64, device=scores.device)
