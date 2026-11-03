# CK2 desktop setup and updates

The fork provides Linux and Windows launchers with a project-local Python 3.12,
venv, and FFmpeg. Windows support is implemented but has not yet been verified
on a Windows NVIDIA GPU. Linux is tested on Rocky Linux 9.8.

## Install and run

Install Git and a suitable NVIDIA driver first. CK2 requires an Ampere
(RTX 30-series) or newer NVIDIA GPU. Linux also needs desktop Qt libraries,
util-linux (`setsid`), and curl or wget. Windows requires x86-64 Windows 10/11
and Windows PowerShell. Neither installer installs drivers or changes system
Python, registry Python registrations, or global PATH.

Clone `https://github.com/chiefjackvfx/CorridorKey2.0.git`, then use:

| Action | Linux | Windows |
| --- | --- | --- |
| Install / repair | `./1-install.sh` | `windows_install.bat` |
| Run | `./2-start.sh` | `windows_run.bat` |
| Check prerequisites | `./3-check.sh` | `windows_check.bat` |
| Enable SAM | `./4-install-sam.sh` | `windows_install_sam.bat` |
| Update outside the app | `./5-update.sh` | `windows_update.bat` |

The standalone `linux_install.sh` or `windows_install.bat` can also be downloaded
and run outside a checkout. Pass an optional destination directory; otherwise
it clones into `CorridorKey2.0` beside the installer. The target must be empty,
absent, or an existing CK2 checkout. Existing checkout installation repairs
software; it does not discard source changes or switch branches.

Setup provisions pinned uv 0.12.21 and managed Python 3.12 under `.runtime/tools/`.
It installs Torch 2.9.1 and torchvision 0.24.1 from the CUDA 12.8 index, with
NumPy below 2. FFmpeg and ffprobe come from checksum-pinned BtbN builds, with
required EXR, H.264, and ProRes codec checks. Their archive notices are retained
under `.runtime/ffmpeg/`. The application and workers use these binaries without
changing your global PATH. A local desktop shortcut is generated for this folder.

Initial setup offers SAM support. Existing SAM installations are detected during
the first migration; later repair/update runs remember the choice. The dedicated
SAM launcher enables it later. Obtain `sam3.1_multiplex.pt` from Meta separately;
setup never downloads that gated checkpoint. Choose its path in the hint editor.

Windows uses portable distance-transform, connected-component, and mask-NMS
helpers because this Torch Windows stack does not supply Triton. These mask
operations use existing SciPy/PyTorch dependencies, returning results to the
original device. SAM model inference remains on CUDA. Both installer verification
and the hint worker prepare this compatibility layer before importing SAM; the
pinned SAM submodule stays unchanged. Linux retains native Triton helpers when
available. `CK_SAM_PORTABLE_OPS=1` can force the portable path for testing.


Setup needs internet access and substantial disk space for CUDA dependencies,
model weights, temporary downloads, and an environment backup. Later ordinary
launches install nothing and can run offline with previously downloaded weights.
On Linux, `./1-install.sh --skip-weights` skips model downloads; `--repair` forces
an environment rebuild and `--no-sam` disables optional SAM in the rebuilt venv.
Windows can pass equivalent arguments directly to `setup_runtime.ps1`.

## Updates and changelog

Open **Updates & Changelog** in the workbench header. It shows the installed
commit, update source, incoming notes, and the local changelog. Select
**Unreleased**, an individual version, or **All changes**. No numbered release
is necessary: new commits on `chiefjackvfx/CorridorKey2.0` **master** are updates.
The fork must contain the implementation before other installations can receive it.

**Check at startup** defaults on and is remembered. Startup checks run in a
background process with a timeout. Available updates offer **Update and restart**,
**View changes**, or **Later**. Network failures do not stop normal use. With
startup checks disabled, the app only inspects local Git state until you request
a check. Notifications wait until queued work and hint generation finish.

An update requires a master checkout with origin pointing to this fork,
no local commits ahead of the target, and a fast-forwardable history. Tracked
changes, untracked source files, and modified submodules normally block installation;
ignored weights, logs, caches, settings, and generated outputs do not. Archive
installations can run, but need a Git checkout for self-updates. Nothing is
stashed, reset, force-pulled, committed, or pushed automatically.

One narrow exception permits an unstaged edit to the unused legacy
`CorridorKey_DRAG_CLIPS_HERE.bat` when the incoming commit leaves that file
unchanged. Git fast-forwards while preserving the local launcher byte-for-byte.
If the update changes that launcher, it is staged, or other source files are
modified, installation stays blocked. The status message lists blocking files.


Installation is disabled during renders, queued work, or hint generation.
After confirmation, CK2 stops preview workers, closes, and hands the checked
commit to an external updater running outside the venv. The updater waits for
exit, rechecks Git state, fast-forwards to that commit, synchronizes initialized
submodules, repairs software while remembering SAM, and restarts only after
verification succeeds. Close every CK2 instance before using the standalone
update launcher. A project lock prevents setup from replacing a running app's venv.

## Project-local cache and temporary files

Disposable CK2 files live in `.cache/` beside the app, resolved from the
installation directory rather than the current working directory or Windows
AppData. The folder is created automatically and ignored by Git.

- `.cache/previews/` and `.cache/hints/`: per-session previews and hint-editor work.
- `.cache/renders/` and `.cache/inference/`: per-job intermediate media and scratch.
- `.cache/temp/` and `.cache/downloads/`: library/setup temporary files and downloads.
- `.cache/uv/`, `.cache/pip/`, `.cache/huggingface/`, `.cache/torch/`, and related
  subfolders: package, model-library, Python bytecode, and CUDA/Triton caches.

Windows and Linux setup scripts set temporary/cache paths before provisioning
Python. The app and workers also set these paths before importing model libraries.
Preview/hint workspaces are removed on close, and successful exports remove
intermediate render media and scratch. Failed render cache locations are recorded
in `logs/jobs/<job>/export.json` for inspection. Durable logs and settings receipts
stay under `logs/jobs/`; final exports, weights, and saved hints keep their paths.

Atomic folder publication must use the destination filesystem. When exporting to
another filesystem, the short-lived publication stage therefore uses
`<output parent>/.cache/ck2-publish/`; its working folders are removed afterward.

Windows image-sequence previews copy the requested frame into the local cache,
including frames read from UNC/NAS shares. Administrator access and Developer
Mode are not required. Linux retains symbolic links where supported, with a copy
fallback when permissions or filesystem support prevent linking. The original
frame remains untouched, including during preview resizing.

Close CK2 and stop setup/update jobs before manually deleting `.cache/`.
Reusable library and installer caches are rebuilt as needed. Preferences and
exported media are not stored in this disposable folder. Explicit CLI
`--temp_dir` overrides remain available.

## Repair and troubleshooting

Rerun Install / Repair after a failure. OS-held locks prevent concurrent setup
or updates. Environment replacement creates the new venv at its final path;
venvs are not moved into place after installation. The previous environment is
retained under `.runtime/backups/`. A migration journal restores the previous
venv and configuration if setup fails or is interrupted. Backups must be restored
to `venv/` before use; their entrypoints are not independently relocatable.

Update logs live under `logs/updates/`. A failed update leaves a message shown
on the next application launch and never automatically starts an unverified
venv. Code may already have fast-forwarded when dependency setup fails: repair
that checkout, then run again. Software verification is separate from the Check
launcher's driver, CUDA computation, codec, and model-file checks. Missing GPU
memory does not mean environment installation failed.

For local source changes or diverged history, resolve the Git state manually.
Do not delete weights, exports, or preferences to make the working tree clean.
If an update cannot finish, the local changelog remains available offline.

`.runtime/`, `venv/`, generated shortcuts, caches, weights, hints, and outputs are
excluded from Git. User preferences remain in the existing application settings.
Moving a checkout requires rerunning setup to repair environment paths and
regenerate its shortcut.

## Validation boundaries

The regression suite covers Git update states, incoming Unreleased notes,
background UI behavior, busy-state restrictions, checksum rejection, setup
locking, migration rollback, remembered SAM, and scratch-map cleanup. Windows
Job Object cancellation, exclusive directory publication, and file-handle tests
are included but run only on Windows. A real Windows NVIDIA validation of
preview, SAM, EXR/video export, and update/restart is still required.


Current Linux validation: 93 tests passed, with three Windows-only tests skipped.
The real managed installer and its healthy-environment reuse passed. The external
updater also passed a local-repository fast-forward/setup/restart integration
test. CUDA prerequisites and actual EXR/video GPU export checks passed in the
managed environment. After freeing VRAM previously occupied by other apps,
automatic preview, model reuse, and preview-to-render GPU handoff also passed.
Real SAM 3.1 checks passed on a production 4096×2160 EXR sequence: text prompts,
include/exclude dots, box selection, colored object picking, brush undo, native
hint saving and attachment, CK preview after releasing SAM, and two native-size
frames across all four EXR passes. This covers two rendered frames, not the full
production clip, and does not establish native Windows GPU support as verified.

The portable SAM path additionally passed an import test with Triton explicitly
blocked and real CUDA tests for points, boxes, text refinement, object picking,
and native-resolution hint saving. Native Windows GPU verification remains pending.
