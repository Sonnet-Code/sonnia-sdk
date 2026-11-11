# Changelog

All notable changes to Sonnia SDK are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow the releases in the [roadmap](docs/roadmap.md).

## [Unreleased]

### Added

- Continuous integration: lint, format check, type check and the test suite on Linux, macOS and Windows, and a gitleaks scan of the whole history.
- A public roadmap in `docs/roadmap.md`.
- Contributor guide, security policy, code of conduct, issue and pull request templates, `.editorconfig` and this changelog.

### Fixed

- The test suite runs on Windows: long parametrized test ids no longer overflow the environment variable pytest sets.

## [0.1.0] - 2026-10-29

First public release.

### Added

- Python orchestrator: realtime speech-to-speech engine over a raw WebSocket, delegated actions (`look`, `show_image`, `hide_image`, `play_animation`), on-demand camera snapshots described by a vision model, local control panel, idle lines and trivia mode.
- Unity client: default avatar from the Genies Avatar Starter Pack with optional Genies Avatar SDK support, phoneme lip-sync, procedural eyes, blinking and breathing, Playables-based animation, vertical 9:16 stage, image panel, subtitles and trivia screen.
- WebSocket protocol between both, documented in `docs/protocol.md`.
- MIT license, README, `.env.example` and a sample knowledge base.
