# Security and Open-Source License Review

**Review date:** 2026-11-12  
**Scope:** Production API image, web build image, web runtime image, and dependencies represented in CI run #477 SBOM.  
**Status:** Preliminary engineering review; not legal advice and not a complete vulnerability attestation.

## Executive findings

1. The web production runtime image in the reviewed SBOM used Nginx 1.27.5 on Alpine 3.21.3. Alpine 3.21 reached end of support on 2026-11-01. This is a lifecycle/security maintenance blocker. The Dockerfile has now been updated to the pinned Nginx 1.30.6 / Alpine 3.24 image index digest `sha256:f65ed258206d1eb6c4eb6141111715a2cf94ac0a4ec9675fc2da186f7aadb163`; the next CI run must prove the resulting image and SBOM.
2. The API Dockerfile has been updated from the older floating-name `python:3.12-slim` digest to the explicit Python 3.12.16 slim-trixie image index digest `sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54`. The Debian APT snapshot and exact FFmpeg package pin remain in place. The next CI run must prove that this combination builds and that the new OS package set is recorded.
3. Trivy image scans are now wired into the container SBOM job for both production images. HIGH and CRITICAL findings, including findings without an upstream fix, fail the security gate. JSON scan reports are uploaded even when a scan fails. The gate is not considered passed until the new workflow run completes successfully.
4. The existing CI SBOM inventory has no `review_required` or `unknown` rows, but metadata completeness is not the same as legal clearance. Several items need explicit interpretation below.

## License review requiring manual attention

### FFmpeg and codec stack (API image)

The captured FFmpeg build configuration includes `--enable-gpl`, `--enable-libx264`, and `--enable-libx265`. The package metadata also reports GPL-family and LGPL-family licenses among the FFmpeg/codec package set.

- Treat this FFmpeg build as GPL-enabled; do not label the complete FFmpeg binary as LGPL-only.
- Confirm which codecs and libraries are actually used by the application, whether the deployed container is only operated as a hosted service or is distributed to customers, and whether any binary/container distribution triggers corresponding source and license-notice obligations.
- Preserve the exact Debian copyright files and FFmpeg build configuration in release artifacts.
- If a non-GPL distribution posture is required, replace this build with a deliberately configured LGPL-compatible FFmpeg build and validate required codecs/features. Do not merely edit the license inventory label.

### OpenCV bundled FFmpeg

The SBOM separately identifies an FFmpeg 8.1.1 binary bundled with the OpenCV Python wheel. The inventory's LGPL-2.1 manual override is based on the upstream wheel notice. Keep this distinct from Debian's GPL-enabled system FFmpeg package. Verify the exact installed wheel, bundled binary provenance, and upstream notice for the wheel version in each release.

### Python and Node runtimes

- Python 3.12.16 is marked PSF-2.0 from the upstream Python license.
- Node.js 22.23.5 is marked MIT from its upstream license.
- Preserve upstream license texts alongside the SBOM, as CI currently does.

### esbuild and Go toolchain metadata

The web build SBOM contains esbuild and `golang.org/x/sys` components with manual MIT/BSD overrides. These are build-stage components, not production runtime components. Verify these overrides against the exact source release metadata when upgrading the Node/Vite toolchain. Keep them classified as build-time dependencies.

### Debian/Alpine package license strings

Distro package metadata often lists multiple licenses because different files in a source package can have different licenses. The semicolon-separated inventory is an evidence index, not an SPDX OR expression and not a conclusion that every license applies to the whole package. For redistribution, retain the distro copyright files and map obligations to the actual shipped binaries/files.

## Dependency reproducibility gaps

- The web dependency tree is reproducible through the committed npm lockfile and `npm ci`.
- API `requirements.txt` still uses version ranges rather than a fully hash-locked Python dependency set. A successful SBOM records what happened in one build, but does not make future builds deterministic. Add a generated, reviewed Python lock/constraints file with hashes before claiming fully reproducible dependency resolution.
- CI service images and GitHub Actions should also be pinned to immutable digests/SHAs in a separate hardening pass; this review updated production Docker base images only.

## Required evidence before marking the PR ready

- New CI run succeeds after both base image digest updates.
- Trivy JSON reports for API and web are reviewed; no unresolved HIGH/CRITICAL findings are accepted without a documented, time-bounded risk exception.
- New CycloneDX SBOMs and license inventories are regenerated from the refreshed images.
- The Nginx runtime SBOM reports the updated Nginx/Alpine versions and no longer reports Alpine 3.21.
- FFmpeg GPL implications and distribution model are reviewed by the project owner/legal reviewer.
- Python dependency resolution is locked and hash-verified, or the remaining non-reproducibility is explicitly accepted.

## References

- Alpine release lifecycle: https://www.alpinelinux.org/releases/
- Debian FFmpeg security tracker: https://security-tracker.debian.org/tracker/ffmpeg
- Debian DSA-6361-1: https://security-tracker.debian.org/tracker/DSA-6361-1
- Trivy: https://github.com/aquasecurity/trivy
