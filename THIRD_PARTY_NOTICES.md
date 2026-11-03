# Third-Party Notices

CorridorKey v2 is licensed under the Corridor Key Licence (see `LICENSE`).
It depends on the third-party components below, which are not owned by
Corridor Digital LLC and remain under their own licenses.

The three foundation models are not redistributed in this repository or in the
CorridorKey Hugging Face repository. `scripts/download_weights.py` fetches them
from their original publishers.

## C-RADIOv4-SO400M

- Publisher: NVIDIA Corporation
- Source: https://huggingface.co/nvidia/C-RADIOv4-SO400M
- License: [NVIDIA Open Model License](https://developer.download.nvidia.com/licenses/nvidia-open-model-license-agreement-june-2024.pdf)
- Use: frozen visual feature extractor, downloaded to `vfms/cradio/`

Licensed by NVIDIA Corporation under the NVIDIA Open Model License.

## MoGe-2 ViT-B

- Publisher: Microsoft Corporation
- Source: https://github.com/microsoft/MoGe, weights at https://huggingface.co/Ruicheng/moge-2-vitb-normal
- License: MIT (code and weights)
- Use: frozen geometry feature extractor. The model code is vendored in
  `third_party/MoGe/` with its license at `third_party/MoGe/LICENSE`; weights
  are downloaded to `vfms/moge/`.

The vendored MoGe code includes DINOv2 (Meta Platforms, Inc.), licensed under
the Apache License 2.0, also reproduced in `third_party/MoGe/LICENSE`.

## RVM (Recurrent Video MAE), small

- Publisher: Google DeepMind
- Source: https://github.com/google-deepmind/representations4d
- License: Apache License 2.0 (code), Creative Commons Attribution 4.0 (weights)
- Use: frozen recurrent video feature extractor. `corridorkey/rvm.py` is a
  PyTorch port of the reference architecture; weights are downloaded to
  `vfms/rvm/`.

## Optional Meta SAM 3.1 hint generation

The local hint editor can use Meta's official SAM 3.1 model and SAM source code.
Source: https://github.com/facebookresearch/sam3, pinned commit
`f1647e8d0c1d280991f4d1b7d974c2704537fe66`, stored under `third_party/sam3/`.
The upstream `LICENSE` (SAM License) and other source notices are retained there.
Checkpoint source: https://huggingface.co/facebook/sam3.1.
The user supplies `sam3.1_multiplex.pt` after obtaining access from Meta.
Neither SAM code nor SAM weights are covered by the CorridorKey license.


## Managed runtime tools

Setup downloads uv 0.12.21 from https://github.com/astral-sh/uv (MIT/Apache-2.0)
and managed CPython via uv's python-build-standalone distributions. These tools
are installed locally, not committed or redistributed as repository assets.

Managed FFmpeg/ffprobe builds come from https://github.com/BtbN/FFmpeg-Builds,
release `autobuild-2026-11-03-12-50`, FFmpeg `n8.1.3-32-g760d10603e`, GPL builds
for Windows/Linux x86-64. Download URLs and SHA-256 digests are pinned in
`runtime_setup.py`. The extracted build's license and other accompanying notices
remain under `.runtime/ffmpeg/`; consult those files for the build's license
and source information. CK2 invokes FFmpeg as a separate executable.
