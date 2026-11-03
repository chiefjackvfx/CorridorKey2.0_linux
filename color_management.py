"""Scene-linear ACEScg (AP1/D60) to linear Rec.709/sRGB (D65).

AP1 chromaticities: https://docs.acescentral.com/encodings/acescg/
Bradford white adaptation; no view transform, tone map, clipping, or alpha change.
"""
import numpy as np


def _xyz(xy):
    x, y = xy
    return np.array([x/y, 1., (1-x-y)/y], dtype=np.float64)


def _npm(primaries, white):
    basis = np.column_stack([_xyz(p) for p in primaries])
    return basis @ np.diag(np.linalg.solve(basis, _xyz(white)))


AP1 = ((.713, .293), (.165, .830), (.128, .044))
REC709 = ((.64, .33), (.30, .60), (.15, .06))
D60, D65 = (.32168, .33767), (.3127, .3290)
BRADFORD = np.array([[.8951, .2664, -.1614], [-.7502, 1.7135, .0367], [.0389, -.0685, 1.0296]])
ADAPTATION = np.linalg.inv(BRADFORD) @ np.diag((BRADFORD @ _xyz(D65))/(BRADFORD @ _xyz(D60))) @ BRADFORD
ACESCG_TO_LINEAR709 = (np.linalg.inv(_npm(REC709, D65)) @ ADAPTATION @ _npm(AP1, D60)).astype(np.float32)


def acescg_to_linear709(rgb):
    return np.asarray(rgb, dtype=np.float32) @ ACESCG_TO_LINEAR709.T
