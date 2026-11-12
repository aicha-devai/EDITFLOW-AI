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
- Reproducibility: the API Dockerfile now pins the Python base image by the digest observed in CI and installs the exact Debian FFmpeg package version `7:7.1.5-0+deb13u1`. The apt dependency closure is still resolved from the Debian repositories at build time; retain the generated SBOM and Debian copyright archive for every release build.
- CI preserves the CycloneDX container SBOM, license metadata inventory, exact FFmpeg build configuration, Debian package version list, and a tarball of installed Debian package copyright files as workflow artifacts.

### Licensing evidence

- FFmpeg legal/licensing guidance: https://www.ffmpeg.org/legal.html
- OpenCV-Python wheel licensing statement (including bundled FFmpeg LGPLv2.1): https://github.com/opencv/opencv-python#licensing
- OpenCV licensing (Apache-2.0 for OpenCV 4.5.0+): https://opencv.org/license/

## Web container and JavaScript dependency scope

- The web Dockerfile has a Node build stage (`node:22-alpine`) and an Nginx runtime stage (`nginx:1.27-alpine`); both base images are pinned by the exact digests observed in CI. CI generates separate SBOMs for both images so build-time npm dependencies are not hidden by the multi-stage runtime image.
- The web package manifest currently has no committed `package-lock.json`; the Dockerfile runs `npm install`. The generated SBOM records the exact resolved dependency tree for that CI build, but future builds can resolve different versions within the semver ranges.
- The Node and Nginx base image digests are now pinned. The remaining web-build reproducibility gap is npm dependency resolution: commit and review a `package-lock.json`, then switch the Dockerfile and CI from `npm install` to `npm ci` before treating the web build as fully reproducible.

## Build-time and runtime licenses confirmed from the full-stack SBOM

The inventory below was manually reconciled against upstream license texts where Syft did not return a license identifier. It remains a technical review record, not a legal opinion.

### Node.js build image and bundled build tooling

- Node.js `22.23.5`: MIT License. The official Node.js license file also enumerates externally maintained components with separate licenses; preserve the license bundle captured by CI rather than assuming the whole Node distribution is covered by one MIT notice.
- esbuild `v0.0.0-20251101233416-208f539945b1`: MIT License (upstream `evanw/esbuild` `LICENSE`).
- `golang.org/x/sys` `v0.0.0-20220715151400-c0bba94af5f8`: BSD-3-Clause.
- `editflow-story-graph-explorer@0.1.0` is the first-party private application package (`private: true`), not a third-party dependency. It is excluded from third-party license-missing counts; this does not grant or assert an open-source license for EDITFLOW AI itself.

### Reproducible container inputs pinned on the feature branch

- API base: `python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`.
- Web build base: `node:22-alpine@sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a`.
- Web runtime base: `nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10`.
- API FFmpeg Debian package: `7:7.1.5-0+deb13u1` (version epoch included in the apt package pin).
- These image digests are the exact inputs observed in the successful CI build and are pinned in the Dockerfiles. Update them only through a reviewed dependency refresh with a new SBOM.

### API development-only dependencies

- `pytest` and `pytest-asyncio` are in `apps/api/requirements-dev.txt`, which includes the production `requirements.txt`; they are no longer installed into the production API image.
- CI installs the development requirements for test execution. The production Dockerfile installs only `apps/api/requirements.txt`.

### Remaining reproducibility limitation

- The web image still uses `npm install` with semver ranges and does not yet commit a lockfile. CI preserves the generated lockfile and exact dependency tree in its SBOM artifact, but the web build is not fully dependency-reproducible until a reviewed `package-lock.json` is committed and the Dockerfile switches to `npm ci`.
