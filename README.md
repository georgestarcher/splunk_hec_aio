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
- [Modernization roadmap](https://github.com/users/georgestarcher/projects/2)

## Release verification

Maintainers can run the **Release verification** GitHub Actions workflow
manually from `main`. It reuses the complete compatibility, quality, and
packaging checks, builds the exact wheel and source distribution, installs
both artifacts outside the checkout, and produces a temporary bundle with
SHA-256 checksums and a manifest tied to the candidate commit and v2
compatibility classification.

This workflow is a read-only dry run. It cannot create or move a tag, publish a
GitHub release, upload to PyPI, or change the installed module. A separate
approval-gated publication workflow accepts only that exact verified bundle
after it matches a GitHub-verified signed tag. Future releases are immutable,
so their tags, assets, and generated provenance cannot be replaced after
publication. The final planned v2.1.2 release keeps the existing GitHub
Releases distribution channel and preserves all prior releases. See
[`docs/releasing.md`](docs/releasing.md) for the workflow inputs, evidence
review, protected live Splunk check, signed-tag and publication procedure, and
recovery policy. The stable release path accepts only `X.Y.Z` versions, so it
intentionally rejects the current `3.0.0.dev0` development version.

## Notes

### Post performance

Test with representative payloads before tuning. The default maximum batch size
is 512,000 bytes and the accepted range is 4,000 through 800,000 bytes. The
limit applies to the uncompressed UTF-8 request body: concatenated serialized
event envelopes in JSON mode or concatenated strings in raw mode. Gzip is
applied only after the batch is formed. A single event larger than the limit is
sent alone because events are never split. The default concurrent-post limit is
10 and the maximum is 20. Smaller batches can spread work across concurrent
requests, but the best values depend on event size, network latency, and the
Splunk deployment. Enable DEBUG logging during a controlled test when you need
to inspect how events are divided among posts.

### JSON and raw modes

JSON payload mode is enabled by default. To send raw string lines, call
`set_payload_json_format(False)` before `post_data`. Optional metadata setters
work in both modes:

```python
sender.set_index("test")
sender.set_sourcetype("syslog")
sender.set_host("dollybean")
sender.set_source("aio_python")
```

In JSON mode the client adds configured metadata to the HEC payload. In raw
mode it adds the supported values to the request parameters.

JSON mode queues its own top-level payload dictionary, so adding configured
metadata does not modify the dictionary passed to `post_data`. With the default
`set_pop_empty_fields(True)` policy, top-level `None` values and empty strings,
lists, tuples, and dictionaries are removed. Meaningful values such as numeric
zero and `False` are preserved. Call `set_pop_empty_fields(False)` to retain
the empty values as well.

When multiple JSON events are sent in one request, the v3 client follows
Splunk's HEC batch format by concatenating complete event objects without
wrapping them in a JSON array. See Splunk's
[event-formatting and batching documentation](https://help.splunk.com/en/splunk-enterprise/get-started/get-data-in/9.2/get-data-with-http-event-collector/format-events-for-http-event-collector).

HEC request channels use random UUIDv4 identifiers. Raw-mode requests include
the required channel query parameter as well as the request-channel header.

`check_connectivity()` performs an unauthenticated `GET` request to Splunk's
`/services/collector/health` endpoint and returns `True` only when HEC reports
HTTP 200 health. It checks whether the service can accept input; it does not
validate the configured token, confirm event acceptance, or prove that an event
was indexed. Delivery responses are a separate concern, and the protected live
integration workflow proves indexing by searching for uniquely marked events.
See Splunk's
[HEC health endpoint documentation](https://help.splunk.com/en/splunk-enterprise/rest-api-reference/9.4/input-endpoints/input-endpoint-descriptions#servicescollectorhealth).

### Strict delivery results

The legacy `post_data()` and `flush()` methods keep their compatible behavior:
they return `None`, and delivery failures may only be logged. V3 adds an
explicit strict path for callers that need a result or exception:

```python
from splunk_hec_aio.splunk_hec_aio import (
    HecBatchDeliveryError,
    HecResponseError,
    SplunkHecAio,
)

sender = SplunkHecAio("splunk.example", "token-from-secret-manager")

try:
    sender.post_data_strict({"event": "first"})
    sender.post_data_strict({"event": "second"})
    results = sender.flush_strict()
except HecBatchDeliveryError as error:
    for failure in error.failures:
        if isinstance(failure, HecResponseError):
            print(
                failure.result.batch_index,
                failure.result.http_status,
                failure.result.hec_code,
                failure.result.hec_text,
            )
    raise
```

Use `post_data_strict()` for every payload in a strict sequence and finish with
`flush_strict()`. This ensures automatic size/concurrency flushes also
propagate failures. A successful strict flush returns an immutable tuple with
one `HecDeliveryResult` per HTTP batch. Each result reports the batch position,
event count, HTTP status, HEC `code` and `text`, optional
`invalid-event-number`, acceptance status, and whether a final failure is
retryable. It never contains the submitted events, authorization header, or
token. Response text is bounded and the configured token is redacted.

Each strict HTTP attempt uses a 30-second total/read timeout and a 10-second
connection timeout. Retryable transport failures and HTTP 408, 429, 500, 502,
503, and 504 responses use the configured retry count. Retrying HEC delivery
provides
at-least-once behavior: if a connection fails after Splunk accepted a request,
a retry can create duplicate events. Design events and downstream processing
to tolerate duplicates. After the configured attempts are exhausted, strict
delivery keeps retryable failed batches queued in their original order. Calling
`flush_strict()` again retries those batches; accepted batches and terminally
rejected batches are not requeued. A cancelled batch is also retained before
the original cancellation is re-raised. If the whole strict dispatch is
cancelled, unfinished and retryable batches remain queued while batches already
known to be accepted or terminally rejected are not requeued. A successful HEC
response confirms request acceptance, not searchable indexing; use protected
search-backed validation or optional indexer acknowledgment when that stronger
signal is required.

These strict methods are synchronous and retain the existing `asyncio.run()`
execution model. Async-friendly public entry points are tracked separately so
the event-loop API can be reviewed without changing this delivery contract.

### 400 Bad Request

If Splunk returns `400 Bad Request` while an index is configured, confirm that
the HEC token is allowed to write to that index.

### TLS verification

TLS certificate verification is enabled by default and should remain enabled
for Splunk Cloud Platform and production Splunk Enterprise deployments. A local
Splunk Enterprise test instance may initially use a self-signed certificate;
prefer installing its CA certificate. Use `set_verify_tls(False)` only for an
isolated development instance whose identity you have verified, never as a
general fix for certificate errors.
