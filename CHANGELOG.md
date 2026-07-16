# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Secret-safe runnable examples for compatible JSON, strict synchronous,
  strict asynchronous, raw, and indexer-acknowledgment delivery, with mocked
  execution tests and source-distribution coverage for every example.

### Changed

- Replaced the historical high-volume example with an environment-configured
  compatible example that sends one event by default and always flushes.
- Updated the README and project Wiki for the stable v3 release and routed
  detailed example guidance through a dedicated Wiki page.

## [3.0.0] - 2026-07-16

This major release raises the supported Python floor to 3.9 and delivers the
behavior corrections and opt-in delivery modes developed after v2.1.2. The
immutable v2.1.2 release remains available for callers that need the legacy
Python or runtime contract. See the [v3 migration guide](docs/migrating-to-v3.md)
before upgrading.

### Added

- A v2-to-v3 migration guide with explicit stay-on-v2 and upgrade paths,
  corrected behavior, delivery-mode selection, and verification guidance.
- Major-release support in the exact-candidate verification and protected
  immutable-publication workflows, including a required
  `breaking-major-release` evidence classification.
- Additive `post_data_ack()` and `flush_ack()` indexer-acknowledgment APIs, with
  matching async entry points, stable per-sender channels, structured confirmed
  results and bounded failures, configurable polling deadlines, immediate
  removal of confirmed IDs, and resumable unconfirmed IDs after timeout or
  cancellation without automatic event resend. Existing compatible and strict
  delivery methods remain unchanged. ACK event POSTs are single-attempt so
  response uncertainty cannot cause a silent duplicate; retryable uncertain
  batches remain queued for an explicit caller decision. General ACK use is
  documented as Splunk Enterprise-only, with Splunk Cloud Platform limited to
  its AWS Kinesis Data Firehose integration.
- Additive `check_connectivity_async()`, `post_data_async()`, `flush_async()`,
  `post_data_strict_async()`, and `flush_strict_async()` entry points for
  applications that already run an event loop. Existing synchronous names,
  signatures, defaults, return values, and event-loop behavior remain
  unchanged.
- Additive `post_data_strict()` and `flush_strict()` delivery APIs with
  structured per-batch HEC results, bounded and token-redacted response
  context, explicit connect/read/total timeouts, deterministic retryability,
  propagated aggregate failures, ordered retention of retryable failed batches,
  stable batch indexes across delivery attempts and flushes,
  concurrency-bounded retry dispatch, and cancellation propagation with queued
  retention for cancelled or unfinished batches. Existing `post_data()` and
  `flush()` defaults remain
  unchanged.
- Linux runtime coverage for Python 3.10, 3.11, and 3.12, alongside the
  cross-platform Python 3.9 and 3.13 compatibility anchors.
- A protected live integration assertion that sends one standalone JSON event
  and one three-event batch, then uses querysplunk to prove Splunk indexed both
  send shapes and all three batch events separately.

### Changed

- Moved detailed guidance for delivery modes, configuration, batching, and
  troubleshooting to the project Wiki while keeping installation, quick start,
  and mode selection in the README.
- Moved the maintained live example from the repository root to
  `examples/example.py` and included the examples directory in source
  distributions while keeping it out of installed wheels.
- Finalized the v3 development line as stable `3.0.0` while retaining v2.1.2
  as the immutable final legacy-compatible v2 release.
- Set the v3 supported-Python contract to Python 3.9 and later, with Python
  3.13 as the primary modern tooling target and classifiers for every supported
  Python minor version.
- Marked v3 artifacts as production/stable and updated metadata, artifact
  verification, contributor guidance, and release documentation for the new
  support matrix.
- Preserved v2.1.2 runtime dependencies, nested import identity, compatible
  method signatures and defaults, and the legacy `None` return contract while
  isolating each approved behavior correction behind focused tests.

### Fixed

- Closed compatible GET and POST retry clients consistently after success,
  request exceptions, and cancellation without changing their public return,
  exception, request, retry, or timeout behavior.
- Changed `check_connectivity()` from an invalid event POST to an
  unauthenticated GET of Splunk's documented HEC health endpoint, and clarified
  that service health does not validate a token or prove indexed delivery.
- Calculated JSON and raw batch thresholds from the exact uncompressed UTF-8
  request-body bytes, and stopped individually oversized events from creating
  empty queued batches.
- Replaced time- and node-derived HEC request channels with random UUIDv4
  identifiers while preserving the existing header and raw query-parameter
  wire shape.
- Preserved top-level numeric zero and `False` values under the default
  empty-field policy, and stopped configured JSON metadata from mutating
  caller-owned payload dictionaries.
- Corrected JSON-mode HEC batching to concatenate complete event envelopes as
  required by Splunk's wire protocol instead of wrapping each batch in a JSON
  array. Public methods, queueing, compression, and raw-mode framing are
  unchanged.
- Made `str(sender)` side-effect-free. It preserves the existing representation
  fields but reports `Reachable=NotChecked`; callers that need a live result
  must invoke `check_connectivity()` explicitly.
- Corrected constructor validation so `host` and `token` must be non-empty
  strings. Missing, whitespace-only, and non-string values now raise a clear
  `ValueError` before any sender configuration is initialized.

## [2.1.2] - 2026-07-15

This is the final planned legacy-compatible v2 release. It preserves the
v2.1.1 public API and observable runtime behavior; the installed module changes
only its authoritative version identifier from `2.1.1` to `2.1.2`.

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
- Low-noise weekly Dependabot updates for Python dependencies, quality tools,
  and pinned GitHub Actions.
- Secret-free runtime compatibility coverage on Linux, macOS, and Windows at
  the Python 3.9 and 3.13 Splunk-aligned anchors.
- Extracted-source-distribution test execution and an offline mocked check of
  the maintained root example.
- A security policy, private vulnerability-reporting route, and security-aware
  public issue routing.
- A read-only manual release-verification workflow that reuses the protected
  compatibility, quality, and packaging gates, verifies the exact wheel and
  source distribution, and uploads a temporary checksummed candidate manifest.
- A separate approval-gated GitHub Release workflow that accepts only a
  successful, unexpired verification bundle for the current signed tag and
  never creates or moves tags, overwrites an existing release, or publishes
  package-index artifacts.
- Pre-publication source-equivalence, canonical-filename, dispatched-revision,
  and post-approval branch-tip checks for the immutable release path.
- Release documentation for the GitHub-Releases-only final v2 policy, protected
  live verification, publication prerequisites, and no-overwrite recovery.

### Changed

- Expanded repository ignore rules for Python development and generated Splunk
  integration artifacts.
- Updated the MIT copyright notice to cover 2023-2026.
- Linked compatibility, contribution, license, changelog, and example guidance
  from the README.
- Made the runtime module version the authoritative distribution version and
  changed that identifier from `2.1.1` to `2.1.2` while preserving the
  distribution name, dependency declarations, `python_requires`, package
  location, and documented nested import.
- Updated the Python 3.9-compatible packaging frontend and constrained
  Dependabot from proposing releases that require Python 3.10.
- Moved the historical network-dependent test module out of the installed
  package and into `tests/legacy/`.
- Reworked the README to distinguish the previous v2.1.1 release from the
  final planned v2.1.2 release, pin stable installation to a release tag, and
  provide secret-safe setup, product, payload-mode, performance, and TLS
  guidance.

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

[Unreleased]: https://github.com/georgestarcher/splunk_hec_aio/compare/v3.0.0...HEAD
[3.0.0]: https://github.com/georgestarcher/splunk_hec_aio/compare/v2.1.2...v3.0.0
[2.1.2]: https://github.com/georgestarcher/splunk_hec_aio/compare/v2.1.1...v2.1.2
[2.1.1]: https://github.com/georgestarcher/splunk_hec_aio/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/georgestarcher/splunk_hec_aio/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/georgestarcher/splunk_hec_aio/releases/tag/v2.0.0
