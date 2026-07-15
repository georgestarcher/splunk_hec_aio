# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A written v2 backward-compatibility contract.
- Characterization tests for the v2.1.1 public API and released behavior.
- Secret-safe bug-report and compatibility-aware feature-request forms.
- A pull-request compatibility checklist and contributor guide.
- An examples landing page that preserves the existing root example path.
- Standards-based, declarative packaging configuration with clean wheel and
  source-distribution verification.
- Installed-artifact checks for the documented nested import and v2.1.1 public
  API on Python 3.9 and 3.13.
- Current-Python quality gates for formatting, linting, scoped static typing,
  branch coverage, and dependency vulnerability auditing.
- Bounded property tests for queue ordering, transport round trips, and batch
  preservation in the modern quality environment.

### Changed

- Expanded repository ignore rules for Python development and generated Splunk
  integration artifacts.
- Updated the MIT copyright notice to cover 2023-2026.
- Linked compatibility, contribution, license, changelog, and example guidance
  from the README.
- Made the runtime module version the authoritative distribution version while
  preserving version `2.1.1`, the distribution name, dependency declarations,
  `python_requires`, package location, and documented nested import.
- Moved the historical network-dependent test module out of the installed
  package and into `tests/legacy/`.

### Removed

- Repository-tracked VS Code test settings that selected the legacy
  live-network test module.

## [2.1.1] - 2024-01-18

### Fixed

- Corrected JSON payload mode and application of configured HEC metadata fields.

### Added

- Added the MIT license file.

## [2.1.0] - 2024-01-01

### Added

- Added optional index, sourcetype, source, and host configuration used by HEC
  payload and raw endpoint handling.

## [2.0.0] - 2023-12-26

### Added

- Initial public v2 release of the asynchronous Splunk HEC sender.

[Unreleased]: https://github.com/georgestarcher/splunk_hec_aio/compare/v2.1.1...HEAD
[2.1.1]: https://github.com/georgestarcher/splunk_hec_aio/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/georgestarcher/splunk_hec_aio/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/georgestarcher/splunk_hec_aio/releases/tag/v2.0.0
