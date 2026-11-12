# Third-party software notices

This file records third-party software intentionally used by EDITFLOW AI or reviewed during engineering. It is not a claim that the listed projects are owned by EDITFLOW AI.

## Included as a runtime dependency

### PySceneDetect

- Upstream: https://github.com/Breakthrough/PySceneDetect
- Package: `scenedetect-headless`
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

### OpenCV-Python headless (transitive dependency)

- Upstream: https://github.com/opencv/opencv-python
- Package observed in the API container SBOM: `opencv-python-headless 5.0.0.93`
- OpenCV library license: Apache-2.0 (OpenCV 4.5.0 and later).
- Wheel build scripts: MIT.
- Bundled FFmpeg libraries: LGPL-2.1, as stated by the upstream wheel project.
- Why present: transitive dependency of `scenedetect-headless`; the headless wheel is appropriate for a server/container without GUI requirements.
- Important distinction: this wheel bundles its own FFmpeg shared libraries in addition to the separate Debian `ffmpeg` executable installed by the API Dockerfile. Both must be included in the release inventory.

### FFmpeg in the API container (observed build snapshot)

- Container image source: `apps/api/Dockerfile` (`python:3.12-slim`, Debian 13 at the time of this SBOM run).
- Observed executable: FFmpeg `7.1.5-0+deb13u1`; FFprobe `7.1.5-0+deb13u1`.
- Observed configure flags include `--enable-gpl`, `--enable-libx264`, `--enable-libx265`, and `--enable-libxvid`; `--enable-version3` was not present.
- License consequence: this particular FFmpeg build is GPL-2.0-or-later, not an LGPL-only build. The FFmpeg project documents that enabling GPL components makes the resulting FFmpeg binaries/libraries GPL-covered. The exact Debian package copyright files and the SBOM must travel with any redistributed image.
- The API invokes the standalone FFmpeg executable as a separate process; this fact alone does not mean EDITFLOW's Python application source is automatically relicensed. Redistribution of the FFmpeg executable/container still carries its own license and corresponding-source obligations.
- Reproducibility caveat: the current Dockerfile uses a floating `python:3.12-slim` tag and installs an unpinned `ffmpeg` apt package. The recorded versions are a dated build snapshot, not a guarantee that future builds resolve to the same versions. Regenerate the SBOM and review the FFmpeg build configuration for every release image.

### Licensing evidence

- FFmpeg legal/licensing guidance: https://www.ffmpeg.org/legal.html
- OpenCV-Python wheel licensing statement (including bundled FFmpeg LGPLv2.1): https://github.com/opencv/opencv-python#licensing
- OpenCV licensing (Apache-2.0 for OpenCV 4.5.0+): https://opencv.org/license/
