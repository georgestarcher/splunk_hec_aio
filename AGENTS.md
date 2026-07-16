# Repository maintainer guide for splunk_hec_aio

This repository contains a Python library for batching and sending JSON or raw
events to Splunk HTTP Event Collector (HEC). Use this guide when an automated
coding agent is modifying this repository or helping another application adopt
the released module.

## Audience boundary

- Agents integrating the released module into another application must begin
  with `docs/consumer-agent-guide.md`, then use the maintained example matching
  the selected delivery mode. Consumer guidance does not grant permission to
  modify this repository, retrieve credentials, send live data, or change a
  Splunk deployment.
- This `AGENTS.md` is the repository-maintainer contract. README, Wiki,
  migration guide, examples, and installed public API remain the user-facing
  contracts.
- When a public method, default, result, exception, request shape, supported
  Python version, or Splunk product limitation changes, update the applicable
  user documentation, consumer-agent guide, examples, tests, and changelog in
  the same pull request.

## Compatibility and release boundaries

- `v2.1.2` is the immutable final legacy-compatible v2 release. Do not move its
  tag, replace its assets, or rewrite its documented runtime contract.
- Stable v3 supports Python 3.9 and later. Preserve the documented
  `from splunk_hec_aio.splunk_hec_aio import SplunkHecAio` import unless an
  explicitly approved migration supplies a compatibility path.
- Compatible methods retain their names, defaults, `None` return contract, and
  logging-oriented failure handling. Do not silently route them through strict
  or acknowledgment behavior.
- Treat runtime behavior, request bytes, dependencies, packaging structure,
  documentation, examples, and release publication as independently
  reviewable boundaries.
- Do not change an existing release to correct later documentation. Update
  `main` and publish a new version when runtime or packaged artifacts must
  change.

## Delivery contracts to preserve

- Compatible: `post_data()` / `flush()` and their async counterparts.
- Strict: `post_data_strict()` / `flush_strict()` and their async counterparts,
  with typed results, failures, bounded response context, ordered retryable
  retention, and cancellation propagation.
- Indexer acknowledgment: `post_data_ack()` / `flush_ack()` and their async
  counterparts, with stable sender channels, bounded polling, resumable pending
  IDs, and no automatic resend after an uncertain ACK event POST.
- JSON batches are concatenated complete HEC envelopes, not JSON arrays. Raw
  mode uses strings and carries its channel in both header and query parameter.
- Always keep health, request acceptance, indexer acknowledgment, and
  searchable indexing documented as different signals.

## Tests and documentation

- Keep ordinary unit, contract, quality, and packaging tests deterministic,
  secret-free, and isolated from public networks.
- Run the Python 3.9 compatibility suite plus current-Python formatting,
  linting, typing, coverage, audit, and packaging checks described in
  `CONTRIBUTING.md`.
- Every maintained example must execute against mocks, use environment-based
  configuration, and finish with the matching flush operation.
- Keep the README concise. Detailed user behavior belongs in the Wiki;
  migration decisions belong in `docs/migrating-to-v3.md`; integrating-agent
  decisions belong in `docs/consumer-agent-guide.md`.
- The GitHub Wiki is a separate repository. Do not publish Wiki links to new
  repository files until those files exist on `main`.

## Live Splunk and secret handling

- Normal pull-request CI must never require a real HEC host, token, search
  credential, private endpoint, or public-network target.
- Live verification must use the protected workflow, a non-production token,
  a test index, a unique marker, and a Splunk query proving the standalone event
  and every batched event became separate searchable rows.
- In the maintainer's configured environment, use the 1Password MCP server for
  1Password Developer Environments. Use `splunkquery` or the configured Splunk
  MCP server for Splunk searches; obtain their credentials through the approved
  1Password boundary.
- Never print, commit, paste into an issue, or place in an example a HEC token,
  search token, authorization header, private endpoint, or sensitive event
  payload.
- Debug logging is for bounded controlled tests. Redact secrets and do not
  upload generated Splunk results as ordinary CI artifacts.

## Pull requests and releases

- Use signed commits and focused branches. Explain compatibility classification
  and user impact in every pull request.
- Require the complete secret-free CI matrix and a clean Codex review before
  merge. Resolve review threads only after the addressing commit is pushed.
- Use protected live verification only when request bytes, endpoints, delivery
  semantics, or release readiness require it.
- Follow `docs/releasing.md` for candidate verification, signed tags, protected
  approval, immutable assets, checksums, and attestations.
