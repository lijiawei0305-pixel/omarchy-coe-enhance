# Changelog

## Unreleased

- Fixed "服务未启动" on every monitor but one: the bridge now lives in a single `Service.qml`, and each monitor's bar widget reads it instead of starting its own bridge.
- Fixed unreadable panel and bar text on Qt 6.12: qualify Omarchy theme imports so `Color` is not resolved to the new QtQuick `Color` singleton.

## 0.2.6

First packaged public release.

- Native Chinese Quattro panel, online ASR Profiles, optional independent LLM cleanup.
- Fixed right Alt push-to-talk, safe Unicode paste, and original Voxtype recording waveform.
- Official voice-input conflict checks without changing Voxtype configuration or services.
- Standalone pinned backend build, early installer safeguards, first-boot coverage and public CI.
- Installation/upgrade/removal documentation, reviewed screenshots, security policy and upstream licenses.

## 0.2.5

Initial public source snapshot. The first GitHub workflow required a context correction before the packaged release.
