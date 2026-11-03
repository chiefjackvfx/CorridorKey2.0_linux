# CorridorKey 2.0 — local Linux desktop edition

This fork contains the official CK2.0 inference code and a
new PySide6 desktop front end. EZ-CorridorKey was reviewed as a workflow reference
for installation, input selection, queued jobs, and export controls. Its existing
GUI targets the earlier CorridorKey model; this implementation calls CK2.0's own
`infer.py`. No EZ-CorridorKey source or branding assets were copied.

For managed Python, Windows launchers, repair, updates, and the changelog viewer,
see [SETUP.md](SETUP.md).

## Install from the fork

```bash
git clone https://github.com/chiefjackvfx/CorridorKey2.0.git
cd CorridorKey2.0
./1-install.sh
./2-start.sh
```

Model weights, generated hints, renders, logs, and the virtual environment are
local files, excluded from Git. The installer creates a desktop shortcut for
your checkout location. Optional SAM source is pinned as a submodule;
`./4-install-sam.sh` also fetches it when not initialized. Supply the SAM
checkpoint separately as described below.

## Start on this machine

```bash
cd /home/gambit/Nextcloud/01_projects/CorridorKey2.0
./2-start.sh
```

You can also open `CorridorKey2-Linux.desktop` in a file manager that supports
desktop launchers; GNOME may require “Allow Launching”. The terminal command
works independently of file-manager launcher support. Pass clip paths to
`./2-start.sh` to queue them immediately.

1. Add clips, drop video files into the window, or add an image-sequence folder.
2. Choose an output folder, channels, video/EXR format, and optional subject hint.
3. Start the queue. An installation check runs before the first job.
4. Select a finished job and choose **Open selected results**.

The app processes one clip at a time. Each run writes versioned pass folders;
logs and settings stay in a private job directory. Input files are preserved.
Settings are captured at queue start. Clips added during processing wait for the
next start. Select finished, failed, or cancelled clips and click **Requeue selected**
(or right-click → **Requeue selected**) to run them again, then click **Render queue**.
You can select multiple media cards. Requeuing keeps per-clip hints and previous
results; the next render uses current settings and a new output version.
Requeuing is disabled while the queue is running. Stopping
cancels the active process group (including FFmpeg) and leaves unstarted clips
queued. Intermediate files from cancelled or failed jobs remain under `.cache/`
for inspection; their locations are recorded in the private job receipt.

### Export folders and passes

In **Deliver**, select **FG**, **Cutout**, **Checker**, and/or **Alpha**. Only
selected passes are exported. **Save sibling** places their folders beside the
source sequence folder or movie. It defaults off and remembers your choice.
When off, the folders go inside your chosen output folder; when on, that folder
control is disabled. The path preview shows the proposed destinations.

For example, an EXR sequence in `/shots/etv090_DN_v001/` starting at frame 1001
can produce these sibling files:

```text
/shots/etv090_DN_fg_v001/etv090_DN_fg_v001.1001.exr
/shots/etv090_DN_cutout_v001/etv090_DN_cutout_v001.1001.exr
/shots/etv090_DN_checker_v001/etv090_DN_checker_v001.1001.exr
/shots/etv090_DN_alpha_v001/etv090_DN_alpha_v001.1001.exr
```

All selected passes share a version. Existing versions across all four passes
are respected, including unselected passes, and subsequent renders use the next
available version. The version is reserved when the job starts, so the preview
can change if another job claims it first. Existing folders are never overwritten.
EXRs count consecutively from the source's first frame number, with at least
four digits. Movies and unnumbered sources start at 1001. Video exports use the
same folder/version scheme, with MOV for Cutout and MP4 for other passes.

Final pass folders contain media only. The job receipt (`export.json`),
`inference.log`, and settings live under this installation's `logs/jobs/`
directory. Disposable working media and inference scratch live under `.cache/`. Outputs are validated before publication; handled
publication failures roll back newly created pass folders. Successful jobs remove
their bulky intermediate media. **Open selected results** and rendered-channel
viewing use the published pass paths. Direct `infer.py` commands retain the
upstream output layout.

## Workbench interface

The interface follows the dark control-panel organization shown in the
[official manual](https://help.corridorkey.com/docs/manual/): Status, Controls,
Time Awareness, Alpha Hint, Despill, and Output. Click a section header to
collapse it. The layout follows the supplied standalone-app screenshot: media cards and a
queue on the left, the viewer in the center, and Inspector plus a fixed Deliver
panel on the right. Import footage from the Media header; select a thumbnail or
queue entry to inspect that clip. Cards show real first-frame thumbnails and job
status. Deliver holds the destination, sibling toggle, passes, format, frame limit, and render
controls. Despill and Output start collapsed.

The viewer has first/previous/next/last-frame controls and a clickable, draggable
filmstrip made from sampled source frames. The highlighted line tracks the
current frame. Use the left rail to hide/show Media, open the processing log, or
check installation. The webcam and video-player overlays are not part of this UI.

**Auto key preview** is enabled by default. Opening a clip automatically keys
its current frame and displays the checkerboard composite, without starting an
export. The first preview loads the model; later frame and setting changes reuse
that model in a separate GPU worker. Scrubbing, hint changes, and despill changes
update after a short debounce. Only the latest requested result is displayed.

Choose **Original**, **Matte**, **Straight FG**, **Composite** (checkerboard), or **RGBA
cutout** above the viewer. With automatic preview enabled, keyed channels use the
current preview. Original shows the source for comparison. Turn automatic preview
off to inspect channels from the selected job's last successful render instead.
Changing preview settings never overwrites exported files.

Previews key one frame at a time, at up to 1280 pixels on the longest side.
Time Awareness and carried hints apply during full renders, not previews.
Single-frame alpha hints apply at frame one in preview; render the sequence to
see their propagation. All-frames hints are sampled at the current frame.
Uncached preview playback waits for inference. Cached frames play at the clip
frame rate when decoding and filesystem access can keep up. The loaded preview model occupies
GPU memory until previews are disabled, a full render starts, or the app closes.
Full renders stop the preview worker before taking the GPU; automatic preview
resumes afterward. Preview files use a temporary directory cleaned on shutdown. Completed previews
remain cached when the preview worker stops for a full render or is disabled.

### Create hints inside CK

Open **Inspector → Alpha Hint → Create / Edit hint…** for the selected clip.
The editor always uses frame one, the reference supported by the current CK
runtime. You can work entirely in the app:

1. Choose a selection method: type **person**, **red car**, or **television**
   and click **Generate with SAM 3.1**; select **Include point** and click the
   subject; or select **Box selection** and drag a rectangle around it.
   To remove a selected subject instead, click **Invert**.
2. Paint with **Keep brush** or **Remove brush**. Right-drag always removes.
   Adjust the brush diameter, switch between Overlay and Matte, and use Fit,
   100%, or 200% zoom. Scrolling pans a zoomed image. Undo/Redo support Ctrl+Z
   and Ctrl+Shift+Z; up to 16 edit states are retained.
3. Click **Use hint**. CK saves a unique, native-size grayscale PNG under this
   project's `hints/` folder, attaches it to the selected clip as a first-frame
   hint, and updates automatic keying at frame one. Use Alpha Hint Strength to
   control its influence; render with Time Awareness to see propagation.

**Points without typing:** choose Include point and click inside an object.
SAM generates its mask automatically. Subsequent include/exclude dots refine
that active object; right-click is an exclude dot. Use **New object** before
clicking a second subject to keep both as separate selections. The object list
lets you choose the target of further dots. Exclude-only input needs an existing
selected object or an initial include dot. Green/red markers show the prompts.

**Box selection:** drag a rectangle as a visual prompt. This starts a fresh SAM
selection, independent of the text field. The box steers SAM rather than acting
as a hard crop. You can refine a box result with points or brushes afterward.
Text generation also starts a fresh selection; Undo restores the previous one.

**Cryptomatte-style picking:** choose **Objects** in the display menu to see
individual SAM masks in different colors. Use **Pick object** to click masks on
or off (right-click excludes), or use their checkboxes and **All / None**.
These toggles run locally without another inference call. Smaller detections win
when masks overlap; the object list provides direct access to every returned ID.
A checked union becomes the hint; brush corrections are retained when toggling
objects or refining them with points. Undo/Redo restores the masks, point/box
prompts, and object selections together. Clear resets the mask and selections.

This is an object-selection view for hint creation, not a Cryptomatte EXR export.
IDs belong to the frame-one SAM detections and may change after fresh text/box
generation. Saved hints remain native-size grayscale PNGs. Reopening a saved
hint loads its combined matte; it does not restore its individual SAM selections.
SAM requests replay the current prompts in a fresh one-frame session, reusing
the loaded model, so undo/retry does not depend on stale GPU session state.

The editor opens an attached first-frame hint or an available cached frame-one
CK matte as a starting point. Otherwise it tries a rough green/blue-screen seed
or starts blank. **Quick screen mask** is a basic screen-color method, separate
from SAM. Generating a new mask replaces the current mask with an undo step;
failed generation preserves your existing mask. Cancel leaves the attached hint
unchanged. Source footage is never rewritten.

SAM runs locally in a separate process. Opening the editor stops the CK preview
worker to free its GPU memory; closing the editor unloads SAM and resumes CK
previewing. Rendering is disabled while the modal editor is open. Other GPU
applications can still occupy memory; the worker checks available memory before
loading SAM and reports failures in the editor. The reference display and
segmentation input are capped at 1600 pixels on the longest side, then the saved
mask is resized to the native frame dimensions. This is a rough alpha hint;
CK performs the final matting. It does not generate a tracked hint sequence.

Hint path, mode, and strength are stored separately for each loaded clip and
captured separately for queued renders. They last for the app session; the PNG
files remain on disk and can be attached again with **File…** after reopening.

SAM 3.1 is installed on this machine, with the checkpoint at
`weights/sam3.1_multiplex.pt`. To install the optional feature elsewhere:

```bash
./4-install-sam.sh
```

This pins Meta's official SAM code to commit
`f1647e8d0c1d280991f4d1b7d974c2704537fe66` and installs its inference dependencies
without replacing the CK torch build. Python 3.12 is required for this feature.
Request access to [Meta's SAM 3.1 checkpoint](https://huggingface.co/facebook/sam3.1),
download `sam3.1_multiplex.pt`, and choose it in the editor's checkpoint picker.
The official source includes tokenizer assets; no hosted inference service or
Hugging Face token is used during generation. The local adapter handles the
pinned predictor's unsupported `offload_state_to_cpu` session argument and preserves
first-dot masks on frames with no cached text detections.

### Internal resolution and output

**Controls → Internal Resolution** offers Full, Half, and Quarter. Inference uses
that fraction of the source width and height; decoded linear foreground and alpha
are Lanczos-upscaled to the original dimensions for every output channel. Full is
the default. Lower settings reduce model memory use and detail in fine edges.
Automatic memory selection uses the padded internal dimensions.

**Output → RGBA alpha** selects Premultiplied (the desktop default) or Straight.
Premultiplied multiplies cutout RGB by alpha in its stored encoding: scene-linear
for EXR and linear ProRes, sRGB for ordinary ProRes. Matte and Straight Foreground
remain unassociated. Set your compositor's alpha interpretation accordingly.
The standalone CLI retains straight output unless `--cutout_premultiplied` is set.
The preview and completed-render viewer unassociate cutouts for display, using the
saved render settings so later Inspector changes do not reinterpret old exports.

**Output → Keep Original in Solid Areas** restores full-resolution source RGB
where the upscaled alpha exceeds 0.95. This preserves opaque detail when using
Half or Quarter and bypasses despill in those pixels. Semi-transparent pixels
retain the model result, and the matte is unchanged. It applies to foreground,
cutout, and checkerboard output. Restoration happens after input color conversion;
ACEScg input still exports in linear Rec.709. EXR storage uses the chosen EXR
precision (half by default). The option starts off.

These settings update automatic previews and invalidate cached keys. Preview
plates remain capped at 1280 pixels before the internal scale is applied;
full renders always read the full source. CLI equivalents:

```bash
venv/bin/python infer.py --input /path/to/frames --output_dir outputs/half-test \
  --frame_dir_linear --frame_dir_fps 25 --model_scale 0.5 \
  --keep_original --cutout_premultiplied --output_format exr \
  --outputs alpha fg checker cutout
```

### Clip cache

Preview frames are cached automatically as you visit them. Click **Cache clip**
above the viewer to key every frame of the selected clip using the current
settings. Click it again to stop filling. Interactive frame requests take priority
over background caching. The cache readout shows completed and retained frames.
**Clear cache** removes all cached previews and regenerates the current frame if
Auto key is enabled. Use a live keyed channel such as Composite when filling.

The session cache stores all four display channels, capped at 2 GB on disk;
least-recently-used frames are evicted if it fills. Larger clips may not fit in
full. It does not pre-copy source footage or cache full-resolution exports.
Source/hint path, size and modification time, frame, FPS, input color space,
linear interpretation, hint mode/strength, internal resolution, alpha association,
original-pixel restoration, and despill settings identify reusable
results. Settings changes do not accidentally reuse an old key. Cache files are
local temporary files and are removed when the app closes.

### ACEScg input

In **Inspector → Controls → Input primaries**, choose
**ACEScg → linear Rec.709** for ACEScg image sequences. ACEScg is already
scene-linear: this converts its AP1 primaries and D60 white to Rec.709/sRGB
primaries with D65 white using Bradford chromatic adaptation. It is not an ACES
view transform or tone map. See the [ACEScg specification](https://docs.acescentral.com/encodings/acescg/).

The conversion preserves floating-point HDR and negative values at the input
conversion step, and does not transform alpha/hints. The existing model/display
paths can subsequently clip values as documented upstream. Linear input is
forced on for ACEScg. Encoded videos are rejected in ACEScg mode; use an image
sequence for this workflow. Rec.709/sRGB remains the default input selection.

Automatic previews, the Original sequence viewer, and full inference share this
conversion. **EXR color outputs are linear Rec.709/D65, not ACEScg**; label them
accordingly when reading them into your compositor. Video previews use sRGB
encoding. The output settings file records the input space and output primaries.
Original/frame-output viewing uses an sRGB display transfer for linear RGB;
matte viewing stays scalar. Media-card and filmstrip thumbnails remain simple
source thumbnails, not color-managed inspection views. Source files are unchanged.

The Status panel shows GPU free/total memory reported by NVIDIA every five
seconds. This is available memory, not a prediction of the next render's needs.
Automatic memory selection still runs in CK2.0 at inference time.

Time Awareness selects the public runtime's Hann-window frame count (automatic,
single-frame, or 2–80 frames), with optional low-memory processing. Internal Hint
Strength maps to carried-hint quality. Despill defaults to zero and Alpha Hint
Strength to 0.75, matching the manual's starting workflow. Linearize cutout
output applies to ProRes RGBA; EXR output is already linear.

This is an independent Linux front end for the public CK2.0 runtime, not the
commercial Windows app. Differences that remain:

- Single-frame hints must reference the first frame, with forward propagation;
  arbitrary reference-frame placement is not exposed by the public CLI.
- Custom despill colors/methods and project/session restoration are not implemented.
- Input is Linear applies to frame sequences, as supported by the public CLI.


## Export and hints

- **Video:** alpha, foreground, and checkerboard MP4 previews; RGBA cutout as
  ProRes 4444 MOV. The outputs do not retain the source audio.
- **EXR:** scene-linear half-float image sequences; RGBA for cutout.
- **GPU memory:** automatic uses upstream free-VRAM estimation; low-memory mode
  uses staged processing with 16-frame windows and an 8-frame stride.
- **Hints:** no hint, first-frame matte, or full hint video/frame directory.
  White means subject and black means background. Each loaded clip retains its
  own hint path, mode, and strength when switching selection or starting a queue.
- **Frame limit:** zero means the full clip. A small positive limit is useful for
  checking your settings before a long render.
- **Frame sequences:** set the correct FPS and enable scene-linear input when
  appropriate for your images. Video inputs use their own frame rate.

## Install on another Linux machine

Requirements: Linux x86-64, Git, curl or wget, util-linux (`setsid`), Qt desktop
libraries, and a CUDA-capable NVIDIA Ampere or newer GPU. Keep sufficient disk
space for CUDA packages, roughly 5 GB of model assets, and footage/output scratch.

```bash
./1-install.sh
./2-start.sh
```

The installer provisions local Python 3.12, a local `venv`, pinned PyTorch 2.9.1 /
torchvision 0.24.1 CUDA 12.8, managed FFmpeg/ffprobe, and a desktop shortcut.
It downloads official model assets unless `--skip-weights` is supplied. It does
not use sudo or change drivers, system Python, or global PATH. Repairs preserve
an environment backup and recover interrupted migrations. `--sam` enables the
optional hint model dependencies; the gated checkpoint remains user supplied.
The SAM choice is remembered. `--repair` forces a rebuild of the environment.

`./1-install.sh --skip-weights` installs software without fetching models.
Use `./3-check.sh` to check CUDA and model readiness separately. Fetch missing
weights later with:

```bash
venv/bin/python scripts/download_weights.py
./3-check.sh
```

On Rocky Linux, the system may need `git`, `libxcb`,
`xcb-util-cursor`, `libxkbcommon-x11`, and Mesa/OpenGL libraries. FFmpeg packaging
varies by enabled repositories; this machine already supplies working encoders.
On Debian/Ubuntu, Python venv support is usually a separate `python3-venv`
package, and Qt commonly needs `libxcb-cursor0` and `libxkbcommon-x11-0`.

## Troubleshooting

For 4K footage, automatic memory selection now reserves 30% above the estimated
peak plus 2 GiB, and prefers staged low-memory processing. For the reported
4096×2176 padded input and 24.7 GiB budget, this chooses an 8-frame window with
4-frame overlap instead of 24 frames. Estimates are not guarantees if other GPU
applications change their memory use during processing.

If inference raises CUDA out-of-memory, the CLI restarts the same clip in a fresh
process with smaller temporal windows and tighter low-memory settings. It retries
from frame one in the same job folder, preserving output resolution and input
files. The log announces the changed temporal context; the final settings file
records the settings actually used. Retries stop at the minimum profile. Pass
`--no_oom_retry` to the CLI to fail instead of changing temporal settings.
The CLI defaults to PyTorch's expandable allocator segments unless you already
set `PYTORCH_ALLOC_CONF` or `PYTORCH_CUDA_ALLOC_CONF`; see
[PyTorch CUDA memory management](https://docs.pytorch.org/docs/stable/notes/cuda).

Automatic previews resize a temporary copy of the input and hint before inference.
The selected internal resolution applies to this capped plate, and the renderer
upscales predictions back to its dimensions using explicit Lanczos output rendering. Linear EXR values are retained
in floating-point EXR intermediates. Source files, including symlink targets, are
never rewritten. After updating a running app, toggle Auto key off/on or restart
the app to reload its persistent preview worker.


Run `./3-check.sh` for dependency, model, FFmpeg, and real CUDA-computation checks.
If CUDA is unavailable, check `nvidia-smi` in your normal desktop terminal.
Sandboxed sessions can hide the GPU even when the host driver works.

If Qt cannot load the xcb plugin, run `QT_DEBUG_PLUGINS=1 ./2-start.sh` and inspect
the missing shared-library message. The launcher clears inherited Qt plugin
paths to avoid collisions with other DCC applications. A graphical desktop
session is required; `QT_QPA_PLATFORM=offscreen` is for testing only.

If moved to another location, rerun
`venv/bin/python scripts/create_linux_launcher.py` to regenerate the shortcut.
Virtual environments themselves are not portable; recreate `venv` on another
machine. Output scratch is isolated per job under `.cache/inference/`;
cancelled jobs may leave cache files that can be removed after processing stops.

## Validation

Verified on Rocky Linux 9.8, Python 3.12.13, RTX 5090 32 GB, NVIDIA driver
590.48.01, and PyTorch 2.9.1+cu128:

```bash
venv/bin/python -m pip check
venv/bin/python -m unittest discover -s tests -v
./3-check.sh
venv/bin/python scripts/smoke_test_runtime.py --load_model
venv/bin/python scripts/smoke_test_linux.py
venv/bin/python scripts/smoke_test_auto_preview.py
venv/bin/python scripts/smoke_test_cache_color.py
venv/bin/python scripts/smoke_test_render_features.py
venv/bin/python scripts/smoke_test_sibling_export.py
# Requires a local SAM checkpoint and sufficient free GPU memory:
venv/bin/python scripts/smoke_test_hint_editor.py --source /path/to/frames --prompt person --render
venv/bin/python scripts/smoke_test_hint_selection.py --source /path/to/frames
```

The desktop smoke test processes a synthetic four-frame 512×288 video and an
image sequence through the actual GUI queue and CUDA model. It checks four
video exports (including alpha-bearing ProRes) and sixteen EXR images for correct
dimensions/frame counts and finite pixel values. It also exercises explicit
time-awareness settings and all four rendered viewer channels in both formats. Artifacts live under
`outputs/linux-smoke/`. This validates execution and file structure, not matte
quality on production footage, long-clip memory use, or every hint combination.

The sibling-export GPU test uses two-frame 512×288 sources. It checks alpha-only
EXRs, shared versions for the other passes, source numbering, preserved inputs
and previous exports, private logs, custom-folder video exports, and rendered
viewer lookup. Artifacts live under `outputs/sibling-export-smoke/`. The regression
suite also covers concurrent reservations, collision rollback,
receipt-write failure rollback, and numeric frame ordering.

## Sources

- [CorridorKey2.0](https://github.com/nikopueringer/CorridorKey2.0), `master`
  archive retrieved 2026-10-30; SHA-256
  `0c9e8ef4e06f67f64fec117d90ab67f7ecd6bc985423dd47f3855fbb728a9db8`.
- [EZ-CorridorKey](https://github.com/edenaion/EZ-CorridorKey), `main` reference
  archive retrieved 2026-10-30; SHA-256
  `bcb1853e7ef6d22c045387b772283316f20f6bd71c7f92368251aa6a513351ee`.

The upstream `LICENSE` and `THIRD_PARTY_NOTICES.md` are retained. This is a local
development setup; nothing has been published or uploaded. The upstream model architecture is retained. Local runtime/CLI changes add
conservative memory selection, bounded OOM recovery, and writer-error cleanup.

The memory and preview fixes were additionally checked against 4096×2160 linear
EXR production input: automatic preview completed at 1280×675, and a 24-frame
section exported all four EXR channels at native resolution. First/last frames
were checked for dimensions and finite pixels; this did not rerender all 92 frames.

The internal-resolution/alpha features were verified with 27 regression tests,
CUDA previews at quarter/half resolution, full-size EXR and ProRes exports, and
two frames of the production 4096×2160 EXR clip processed at half resolution.
All eight exported EXRs retained native dimensions and finite pixels. Solid
foreground pixels matched the full-resolution source within half-float storage
precision, and cutout RGB matched foreground times alpha. This additional check
covers two frames, not the complete 92-frame production shot.

The in-app SAM hint workflow was additionally validated on the production 4K
sequence: local SAM 3.1 text-prompt inference, brush undo, native 4096×2160 PNG
saving, per-clip attachment, automatic CK preview, and two full-size frames across
all four EXR output channels. The CK preview used Quarter and Low GPU Memory;
the render used Half and Low GPU Memory. Hint creation/attachment and CK execution
were validated in separate GPU runs because other desktop GPU apps occupied VRAM.
All 34 regression tests and dependency consistency checks passed. The generated
mask is a semantic selection, not a ground-truth matte-quality assessment.

Point/box/object selection was verified with 41 regression tests and real SAM 3.1
GPU inference on the production clip: positive and negative dots without text,
multiple objects, inference-free object picking, box prompts, refinement of a
text-detected object, selection-aware undo/redo, and native-size hint saving.
The separate GPU check uses `scripts/smoke_test_hint_selection.py`; its default
point/box coordinates match this validation clip and can be overridden for others.
