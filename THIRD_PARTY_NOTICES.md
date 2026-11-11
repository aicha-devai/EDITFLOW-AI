# Third-party software notices

This file records third-party software intentionally used by EDITFLOW AI or reviewed during engineering. It is not a claim that the listed projects are owned by EDITFLOW AI.

## Included as a runtime dependency

### PySceneDetect

- Upstream: https://github.com/Breakthrough/PySceneDetect
- Package: `scenedetect[opencv]`
- Version constraint: `>=0.7.3,<1`
- License: BSD 3-Clause
- Copyright: Copyright (C) 2014, Brandon Castellano
- Use in EDITFLOW AI: scene-boundary detection during timestamped render-evidence extraction.
- Integration: imported as an installed third-party package through `apps/api/requirements.txt`; upstream source is not copied or vendored.
- Local changes: EDITFLOW AI contains its own adapter in `apps/api/app/scene_detection.py`; no modifications are made to PySceneDetect itself.
- License text: [third_party/licenses/PYSCENEDETECT-BSD-3-CLAUSE.txt](third_party/licenses/PYSCENEDETECT-BSD-3-CLAUSE.txt)

## Engineering references reviewed; no source code copied or dependency added

These repositories were inspected for architectural ideas only. EDITFLOW AI does not redistribute their code as part of this integration.

### Kinocut

- Upstream: https://github.com/KyaniteLabs/kinocut
- Upstream license: Apache License 2.0
- Review purpose: agent-oriented FFmpeg workflows, guarded editing operations, and resumable workflow design.
- Integration status: reference only; no code copied, vendored, or installed.

### VidAPI

- Upstream: https://github.com/moshehbenavraham/vidapi
- Upstream license: MIT
- Review purpose: JSON timeline rendering API, worker separation, and S3-compatible artifact storage patterns.
- Integration status: reference only; no code copied, vendored, or installed.

## Existing system dependency requiring release-build review

### FFmpeg

- Upstream: https://ffmpeg.org/
- Use in EDITFLOW AI: media probing, extraction, rendering, and quality-control filters.
- Distribution note: FFmpeg's effective license depends on the exact build configuration and enabled external libraries. Before redistributing a packaged application/container outside the current deployment environment, record the deployed FFmpeg build configuration and include all applicable notices. Do not assume every FFmpeg build has identical licensing terms.

## Maintenance rules

1. Keep this file and the corresponding license texts with source distributions.
2. Re-check upstream license files and dependency versions before upgrades.
3. Generate and review a complete Software Bill of Materials (SBOM), including transitive Python and OS packages, before public commercial distribution.
4. Do not imply endorsement by upstream maintainers or use their names/logos as product endorsements.
