# Changelog

## Unreleased

### Added

- [2026-11-03T13:49:00+00:00] Added selected-clip requeuing with preserved hints and previous exports.

- [2026-11-03T13:24:12+00:00] Added managed Python, CUDA environment recovery, and verified FFmpeg downloads.
- [2026-11-03T13:24:12+00:00] Added Windows launchers and cross-platform worker process ownership.
- [2026-11-03T13:24:12+00:00] Added startup update checks, changelog viewer, and explicit restart updates.
- [2026-11-03T13:24:12+00:00] Added update-state, migration, UI, and native Windows regression coverage.

- [2026-11-03T11:32:54+00:00] Added versioned sibling exports and per-pass Deliver controls.
- [2026-11-03T11:32:54+00:00] Added source-frame numbering and private export job storage.
- [2026-11-03T11:32:54+00:00] Added transactional publication, collision protection, and export validation.
- [2026-11-03T11:32:54+00:00] Added sibling-export regression tests, GPU checks, and documentation.

- [2026-11-02T18:02:31+00:00] Added SAM include/exclude dots and box selection.
- [2026-11-02T18:02:31+00:00] Added colored object picking and individual mask selection.
- [2026-11-02T18:02:31+00:00] Added selection-aware undo and brush-preserving object toggles.

- [2026-11-02T17:43:37+00:00] Added local SAM 3.1 hint generation and mask editing.
- [2026-11-02T17:43:37+00:00] Added per-clip hints and native-resolution matte saving.
- [2026-11-02T17:43:37+00:00] Added optional SAM setup and hint-editor regression coverage.

- [2026-11-02T14:41:44+00:00] Added full-size exports with selectable internal processing resolution.
- [2026-11-02T14:41:44+00:00] Added premultiplied RGBA and original-pixel restoration controls.
- [2026-11-02T14:41:44+00:00] Added render-feature regression, GPU, and production-footage validation.

- [2026-11-02T14:16:24+00:00] Added bounded clip-preview caching, prefill, reuse, and cache clearing.
- [2026-11-02T14:16:24+00:00] Added ACEScg-to-linear-Rec.709 conversion for previews and sequence renders.
- [2026-11-02T14:16:24+00:00] Added color metadata and cache/color GPU integration validation.

- [2026-11-02T12:35:54+00:00] Added bounded CUDA retries with smaller temporal windows.
- [2026-11-02T12:35:54+00:00] Added production-resolution validation and source-preservation preview tests.

- [2026-11-02T12:26:18+00:00] Added media thumbnails, queue navigation, and clickable filmstrip.

- [2026-11-02T12:18:32+00:00] Added automatic GPU key previews with persistent model loading.
- [2026-11-02T12:18:32+00:00] Added debounced scrubbing, settings updates, and stale-result protection.
- [2026-11-02T12:18:32+00:00] Added preview/render GPU exclusion and automatic-preview smoke tests.

- [2026-11-02T12:10:57+00:00] Added manual-inspired panels, timeline, playback, and rendered-channel viewer.
- [2026-11-02T12:10:57+00:00] Added temporal controls, internal hint strength, and linear cutouts.
- [2026-11-02T12:10:57+00:00] Added GPU memory status and viewer regression coverage.

- [2026-10-30T16:47:01+00:00] Added Linux desktop queue, previews, hints, and export controls.
- [2026-10-30T16:47:01+00:00] Added isolated installer, desktop launcher, and CUDA readiness checks.
- [2026-10-30T16:47:01+00:00] Added Linux setup documentation and upstream source provenance.
- [2026-10-30T16:47:01+00:00] Added command tests and real GPU export smoke tests.

### Changed

- [2026-11-03T13:49:00+00:00] Covered requeue states, busy guards, settings, and output-version preservation.

- [2026-11-03T13:35:56+00:00] Validated managed-environment previews, SAM selections, and full-resolution EXR exports.

- [2026-11-03T13:24:12+00:00] Documented installation, repair, updates, and Windows validation limitations.

- [2026-11-03T11:57:03+00:00] Added README introduction crediting CK2 developers and UI inspiration.

- [2026-11-03T11:54:54+00:00] Prepared fork setup with pinned SAM and local-file exclusions.
- [2026-11-03T11:54:54+00:00] Documented fork installation and submodule-compatible SAM setup.

- [2026-11-02T12:35:54+00:00] Reserved more VRAM headroom and preferred staged 4K processing.

- [2026-11-02T12:26:18+00:00] Matched reference layout with Media, Inspector, and Deliver panels.

- [2026-11-02T12:20:02+00:00] Defaulted sequence playback to 25fps and enabled linear input.

### Fixed

- [2026-11-03T13:24:12+00:00] Closed retained scratch mappings before Windows file cleanup.

- [2026-11-02T18:02:31+00:00] Fixed upstream SAM first-point mask loss on empty frames.

- [2026-11-02T12:35:54+00:00] Fixed 4K previews using temporary resized inputs and hints.
- [2026-11-02T12:35:54+00:00] Preserved CUDA errors during writer cleanup for reliable recovery.

- [2026-11-02T12:26:18+00:00] Isolated smoke-test preferences from normal application settings.

- [2026-10-30T16:47:01+00:00] Isolated desktop job outputs and scratch files between runs.
