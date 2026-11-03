"""Portable SAM helpers and a real import with Triton explicitly unavailable."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import numpy as np
import torch
from sam_portable_ops import distance_transform, connected_components, generic_nms


class PortableSAM(unittest.TestCase):
    def test_distance_transform_batches_and_uniform_masks(self):
        mask = torch.ones((3,5,5), dtype=torch.bool)
        mask[0,2,2] = False; mask[1] = False
        result = distance_transform(mask)
        self.assertEqual(result.dtype, torch.float32)
        self.assertEqual(result.device, mask.device)
        self.assertAlmostEqual(result[0,0,0].item(), np.sqrt(8), places=5)
        self.assertEqual(result[0,2,2].item(), 0)
        self.assertTrue((result[1] == 0).all())
        self.assertTrue((result[2] == 1e9).all())
        self.assertEqual(distance_transform(torch.zeros((0,2,3))).shape, (0,2,3))

    def test_connected_components_eight_neighbors_background_and_batch(self):
        masks = torch.tensor([[[1,0,0],[0,1,0],[0,0,0]], [[1,0,1],[0,0,0],[0,0,0]]])[:,None]
        labels, counts = connected_components(masks)
        self.assertEqual(labels.shape, masks.shape)
        self.assertEqual(labels[0,0,0,0], labels[0,0,1,1])
        self.assertEqual(counts[0,0,0,0], 2)
        self.assertEqual(counts[0,0,0,1], 0)
        self.assertNotEqual(labels[1,0,0,0], labels[1,0,0,2])
        self.assertEqual(counts[1,0,0,0], 1)
        self.assertEqual(connected_components(masks[:,0])[0].shape, (2,3,3))

    def test_nms_threshold_empty_and_order(self):
        ious = torch.tensor([[1.,.8,.5],[.8,1.,0.],[.5,0.,1.]])
        self.assertEqual(generic_nms(ious,torch.tensor([.9,.8,.7]),.5).tolist(),[0,2])
        result=generic_nms(torch.empty((0,0)),torch.empty(0),.5)
        self.assertEqual(result.dtype,torch.int64); self.assertEqual(result.numel(),0)

    def test_setup_verification_prepares_adapter_before_sam_import(self):
        import runtime_setup
        with patch.object(runtime_setup,'run') as run:
            runtime_setup.verify('python',sam=True)
        code=run.call_args_list[0].args[0][2]
        self.assertLess(code.index('prepare_sam_imports()'),code.index('import sam3'))

    @unittest.skipUnless((Path(__file__).resolve().parents[1]/'third_party/sam3/sam3').is_dir(), 'Optional SAM source is not installed')
    def test_real_sam_import_without_triton(self):
        root=Path(__file__).resolve().parents[1]
        code='''import torch, builtins
original = builtins.__import__
def without_triton(name,*args,**kwargs):
    if name == 'triton' or name.startswith('triton.'):
        raise ModuleNotFoundError("Triton intentionally unavailable for Windows regression")
    return original(name,*args,**kwargs)
builtins.__import__ = without_triton
from sam_hint_backend import prepare_sam_imports
assert prepare_sam_imports()
import sam3
from sam3.model.edt import edt_triton
from sam_portable_ops import distance_transform
assert edt_triton is distance_transform
from sam3.perflib.triton.connected_components import connected_components_triton
from sam3.perflib.triton.nms import nms_triton
assert connected_components_triton(torch.ones((1,2,2)))[1].max() == 4
assert nms_triton(torch.eye(1),torch.ones(1),.5).tolist() == [0]
'''
        env=os.environ.copy();env['CK_SAM_PORTABLE_OPS']='1';env['PYTHONPATH']=str(root/'third_party/sam3')
        result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=120)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
