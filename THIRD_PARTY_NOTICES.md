# Third-party notices

Omarchy Coe Enhance is distributed under the Apache License, Version 2.0; see [LICENSE](LICENSE). Existing upstream copyright notices must be retained when extending or redistributing this project.

## Coe

- Source: https://github.com/quailyquaily/coe
- Pinned source commit: `1345eccb5129cb067a49646e6b73572562d38521`
- License: Apache-2.0, reproduced in this repository's [LICENSE](LICENSE).
- The installer obtains the original source and applies the clearly separated modifications in `patches/` and additions in `core/`. These modify privacy logging, output ownership, provider integration, stage tracing, HTTP/audio handling, and OSD audio levels. This repository does not vendor the entire upstream source or ship a prebuilt Coe binary.
- Third-party Go dependencies retain their upstream licenses; Go module metadata is retained in the built checkout.

## Voxtype

- Source: https://github.com/peteonrails/voxtype
- Audio-frame compatibility audited against v1.1.1.
- Copyright (c) 2025 Peter Jackson.
- License: [MIT](licenses/voxtype-MIT.txt).
- The plugin launches the user's separately installed, unmodified `voxtype-osd-gtk4` frontend. It does not copy the waveform renderer or start Voxtype recording. The recording screenshot illustrates that original frontend. The new adapter sends only derived audio levels through the native 16-byte frame protocol.

## Omarchy

- Source: https://github.com/omacom/omarchy
- License and upstream copyright: [MIT](licenses/omarchy-MIT.txt).
- The plugin imports the separately installed Omarchy Shell UI components. It does not redistribute or modify the packaged Shell. CI checks the manifest with the official validator from the pinned Omarchy 4.0.4 source.

## Omarchy Voxtype Enhance

- UI and output-integration reference: https://github.com/iamcheyan/omarchy-voxtype-enhance
- License and upstream copyright: [MIT](licenses/voxtype-enhance-MIT.txt).
- Credited as an implementation and interaction reference. This project supplies its own Coe configuration bridge and online ASR integration, and does not redistribute the reference project's offline model-download interface.

Product and project names belong to their respective owners. This is an independent third-party plugin, not an official release from these projects.
