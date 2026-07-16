# splunk_hec_aio

An asynchronous Python client for batching and sending JSON or raw events to a
Splunk HTTP Event Collector (HEC).

The latest published release is
[`v2.1.2`](https://github.com/georgestarcher/splunk_hec_aio/releases/tag/v2.1.2).
It is the final planned legacy-compatible v2 release. The previous
[`v2.1.1`](https://github.com/georgestarcher/splunk_hec_aio/releases/tag/v2.1.1)
release and all other existing releases remain available on the
[GitHub Releases page](https://github.com/georgestarcher/splunk_hec_aio/releases).
The `main` branch is now the unreleased v3 development line and reports
`3.0.0.dev0`.

Maintained by George Starcher (starcher). Licensed under the
[MIT License](LICENSE).

## Supported Splunk products

- Splunk Cloud Platform with HEC enabled
- Splunk Enterprise with HEC enabled

Your HEC token must be allowed to write to every index selected by the client.

## Install

The v2 line is distributed through GitHub Releases rather than PyPI. Pin the
tag when installing the current stable release:

```shell
python -m pip install \
  "git+https://github.com/georgestarcher/splunk_hec_aio.git@v2.1.2"
```

Installing from untagged `main` opts into the v3 prerelease, which requires
Python 3.9 or later and is not a stable release. For a local checkout used for
development, follow the environment and test commands in
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Quick start

Keep HEC tokens outside source code and load them from a secret manager or the
process environment:

```python
import os
import time

from splunk_hec_aio.splunk_hec_aio import SplunkHecAio

sender = SplunkHecAio(
    os.environ["SPLUNK_HEC_HOST"],
    os.environ["SPLUNK_HEC_TOKEN"],
)
sender.set_port(int(os.environ.get("SPLUNK_HEC_PORT", "443")))
sender.set_index("starcher_hec")
sender.set_sourcetype("aio_json")

sender.post_data(
    {
        "time": str(round(time.time(), 3)),
        "event": {"message": "hello from splunk_hec_aio"},
    }
)

# Always flush before the process exits so the final queued batch is sent.
sender.flush()
```

Port `443` is typical for Splunk Cloud Platform. Splunk Enterprise HEC commonly
uses port `8088`; use the port configured by your Splunk administrator. See
[`examples/README.md`](examples/README.md) for the maintained full example and
its safety notes.

The documented v2 import remains:

```python
from splunk_hec_aio.splunk_hec_aio import SplunkHecAio
```

## Delivery modes

The existing compatible path remains unchanged:

```python
sender.post_data(event)
sender.flush()
```

These methods preserve v2 behavior, return `None`, and are appropriate when
delivery logging is sufficient. The v3 development line also provides an
optional strict path:

```python
results = sender.post_data_strict(event)
results += sender.flush_strict()
```

Strict delivery returns structured per-batch results, propagates aggregate
failures, and retains retryable or uncertain batches for another attempt. Use
one mode consistently for a queued sequence; do not mix compatible and strict
methods before flushing. See the
[Delivery modes Wiki guide](https://github.com/georgestarcher/splunk_hec_aio/wiki/Delivery-Modes)
for result fields, exceptions, retries, cancellation, and examples.

Splunk Enterprise users whose HEC token has indexer acknowledgment enabled can
opt into confirmation that each accepted batch reached the configured
replication target:

```python
confirmed = sender.post_data_ack(event)
confirmed += sender.flush_ack()
```

ACK mode is separate from compatible and strict delivery. It uses one stable
channel per sender, returns structured `HecAcknowledgmentResult` values, and
raises `HecAcknowledgmentError` with bounded per-batch failures when an ID
cannot be confirmed. A timeout keeps the pending ACK ID; calling `flush_ack()`
again resumes polling without automatically resending the accepted batch.
ACK event POSTs are single-attempt because silently retrying after a lost or
truncated response could create duplicates. An uncertain send remains queued,
but retrying it is an explicit caller decision and can still produce a
duplicate if Splunk accepted the original request.
Splunk documents general indexer acknowledgment as Splunk Enterprise-only;
Splunk Cloud Platform supports it only for the AWS Kinesis Data Firehose
integration. See the
[Indexer acknowledgment Wiki guide](https://github.com/georgestarcher/splunk_hec_aio/wiki/Indexer-Acknowledgment)
and Splunk's
[indexer acknowledgment documentation](https://help.splunk.com/en/splunk-enterprise/get-started/get-data-in/9.2/get-data-with-http-event-collector/about-http-event-collector-indexer-acknowledgment)
before enabling this mode. Do not mix ACK and other delivery methods in one
queued sequence.

Applications that already run an event loop should use the matching async
entry points instead of the synchronous methods:

```python
await sender.post_data_async(event)
await sender.flush_async()
```

Async strict callers use `post_data_strict_async()` and
`flush_strict_async()`. ACK callers use `post_data_ack_async()` and
`flush_ack_async()`. Connectivity checks likewise have
`check_connectivity_async()`. The synchronous API remains unchanged; choose
one sync or async style for a queued sequence. The Wiki guide covers both
patterns in detail.

## Compatibility and project documentation

The immutable v2.1.2 release preserves the released public API and existing
user behavior. The v3 development line currently preserves that API and
behavior while establishing its supported-Python baseline. The compatibility
policy and local baseline-test command are documented in
[`docs/compatibility.md`](docs/compatibility.md).
Contributor setup and review requirements are documented in
[`CONTRIBUTING.md`](CONTRIBUTING.md).

V3 supports Python 3.9 and later. Python 3.9 is the compatibility floor and
Python 3.13 is the primary modern Splunk-aligned target. CI tests both anchors
across Linux, macOS, and Windows and exercises Python 3.10 through 3.12 on
Linux.

Additional project documentation:

- [Changelog](CHANGELOG.md)
- [Examples](examples/README.md)
- [License](LICENSE)
- [Release verification](docs/releasing.md)
- [Security policy](SECURITY.md)
- [User Wiki](https://github.com/georgestarcher/splunk_hec_aio/wiki)
- [Modernization roadmap](https://github.com/users/georgestarcher/projects/2)

## Release verification

Maintainers use protected verification and publication workflows that preserve
artifact identity and require signed stable tags. See
[`docs/releasing.md`](docs/releasing.md) for the complete procedure.

## Usage guides

The [project Wiki](https://github.com/georgestarcher/splunk_hec_aio/wiki)
contains the detailed user documentation:

- [Delivery modes](https://github.com/georgestarcher/splunk_hec_aio/wiki/Delivery-Modes)
- [Indexer acknowledgment](https://github.com/georgestarcher/splunk_hec_aio/wiki/Indexer-Acknowledgment)
- [Configuration and batching](https://github.com/georgestarcher/splunk_hec_aio/wiki/Configuration-and-Batching)
- [Connectivity and troubleshooting](https://github.com/georgestarcher/splunk_hec_aio/wiki/Connectivity-and-Troubleshooting)

Splunk's authoritative endpoint behavior remains documented in the
[HEC REST API endpoint reference](https://help.splunk.com/en/splunk-enterprise/get-started/get-data-in/9.2/get-data-with-http-event-collector/http-event-collector-rest-api-endpoints).
