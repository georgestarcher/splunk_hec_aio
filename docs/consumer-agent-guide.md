# Consumer-agent integration guide

This file is the self-contained starting contract for an AI coding assistant
adding the released `splunk_hec_aio` module to another Python application. It
is consumer guidance, not permission to modify this repository, retrieve a
credential, send live data, or change a Splunk deployment.

The application owns secret management, event contents, index selection,
scheduling, shutdown, retry policy, duplicate tolerance, search permissions,
and operational monitoring. `splunk_hec_aio` supplies HEC request construction,
batching, compatible and strict delivery, asynchronous entry points, and
optional Splunk Enterprise indexer acknowledgment.

## Start with the smallest required facts

Ask for these facts before writing integration code:

1. Is this a new v3 integration or an existing application deliberately pinned
   to legacy v2.1.2?
2. Which supported Python version does the application run?
3. Is the deployment Splunk Cloud Platform or Splunk Enterprise, and what HEC
   hostname and port did its administrator approve?
4. Is the payload JSON event envelopes or raw text?
5. Does the application already run an event loop?
6. Does the caller need compatible logging behavior, structured strict results,
   or supported indexer acknowledgment?
7. Which index, sourcetype, source, and event host should be attached?
8. What application-owned secret reference supplies the HEC token?

Never ask the user to paste a HEC token into chat, source code, a test, an issue,
or generated documentation. Record facts as confirmed, proposed, or unknown;
do not invent a hostname, port, index, sourcetype, token capability, or ACK
setting.

## Select and pin the release

New integrations should use stable v3 on Python 3.9 or later:

```shell
python -m pip install \
  "git+https://github.com/georgestarcher/splunk_hec_aio.git@v3.0.0"
```

An existing application that requires the legacy Python or exact v2 runtime
contract can remain on immutable v2.1.2:

```shell
python -m pip install \
  "git+https://github.com/georgestarcher/splunk_hec_aio.git@v2.1.2"
```

The project is distributed through GitHub Releases, not PyPI. Pin a release
tag and inspect the documentation for that selected tag. Do not install a
production application from untagged `main` or copy API names from an issue or
future roadmap.

## Integration decision tree

Choose one row from each applicable decision:

| Question | Choice | Public path |
| --- | --- | --- |
| How should outcomes surface? | Compatible | `post_data()` and `flush()` return `None` and use logging-oriented failure handling |
| How should outcomes surface? | Strict | `post_data_strict()` and `flush_strict()` return typed results and raise structured aggregate failures |
| Is supported replication acknowledgment required? | Splunk Enterprise ACK | `post_data_ack()` and `flush_ack()` poll typed ACK IDs to a bounded deadline |
| Does the application already run an event loop? | Yes | Use the matching `_async` queue and flush methods and await both |
| Does the application already run an event loop? | No | Use the synchronous method pair |
| What is being sent? | JSON | Keep the default JSON mode and pass dictionaries containing HEC event envelopes |
| What is being sent? | Raw | Call `set_payload_json_format(False)` before queueing and pass strings |

Use one delivery mode and one execution style for a queued sequence. Do not mix
compatible, strict, or ACK methods—or synchronous and asynchronous queue
operations—before the matching flush completes.

General HEC indexer acknowledgment is for supported Splunk Enterprise
deployments whose token has **Enable indexer acknowledgment** turned on. Do not
select ACK for an ordinary Splunk Cloud Platform HEC client. Splunk documents a
separate Cloud exception for its AWS Kinesis Data Firehose integration.

## Build the sender without embedding secrets

The maintained examples read configuration from the process environment. In a
production application, an approved secret manager may populate the same
application-owned boundary:

```python
import os

from splunk_hec_aio.splunk_hec_aio import SplunkHecAio

sender = SplunkHecAio(
    os.environ["SPLUNK_HEC_HOST"],
    os.environ["SPLUNK_HEC_TOKEN"],
)
sender.set_port(int(os.environ.get("SPLUNK_HEC_PORT", "443")))
sender.set_sourcetype(os.environ.get("SPLUNK_HEC_SOURCETYPE", "splunk_hec_aio"))
index = os.environ.get("SPLUNK_HEC_INDEX")
if index:
    sender.set_index(index)
source = os.environ.get("SPLUNK_HEC_SOURCE")
if source:
    sender.set_source(source)
event_host = os.environ.get("SPLUNK_EVENT_HOST")
if event_host:
    sender.set_host(event_host)
```

`SPLUNK_HEC_SOURCE` and `SPLUNK_EVENT_HOST` are optional. Set them only when
the consuming application has confirmed metadata values; leaving either unset
preserves the module's default for that field.

Port `443` is typical for Splunk Cloud Platform. Splunk Enterprise commonly
uses HEC port `8088`; the deployment administrator's actual configuration is
authoritative. Keep TLS verification enabled. Do not use
`set_verify_tls(False)` as a general certificate-error workaround.

Start from the maintained file matching the selected path:

- [`examples/example.py`](../examples/example.py): compatible synchronous JSON;
- [`examples/strict_delivery.py`](../examples/strict_delivery.py): strict synchronous JSON;
- [`examples/async_strict_delivery.py`](../examples/async_strict_delivery.py): strict delivery in an existing event loop;
- [`examples/raw_delivery.py`](../examples/raw_delivery.py): compatible raw delivery; or
- [`examples/indexer_acknowledgment.py`](../examples/indexer_acknowledgment.py): guarded Splunk Enterprise ACK delivery.

Adapt one example instead of combining fragments from several modes. Every
queued sequence must end with its matching `flush()`, `flush_async()`,
`flush_strict()`, `flush_strict_async()`, `flush_ack()`, or `flush_ack_async()`
operation before process shutdown.

## Side effects and signal boundaries

- Constructing a sender and changing its settings perform no network request.
- `str(sender)` is local and reports `Reachable=NotChecked`.
- `check_connectivity()` and `check_connectivity_async()` issue an
  unauthenticated GET to the documented HEC health endpoint. A reverse proxy or
  deployment policy may block that endpoint while the event endpoint remains
  usable, so health is not a prerequisite for an approved delivery test.
- A healthy response proves only that the HEC service answered. It does not
  validate the token, selected index, request acceptance, parsing, or indexing.
- Queue methods can send automatically when a batch threshold is reached.
  Matching flush methods send the final partial batch.
- Strict success confirms HEC request acceptance, not searchable indexing.
- ACK success confirms the configured replication target, not event parsing or
  searchability.

Treat event contents, Splunk response context, endpoint details, and indexed
results according to the application's data classification. Enable debug
logging only for a bounded controlled test, and never print a token or
authorization header.

## Delivery and failure behavior

Compatible delivery preserves the familiar `None` return contract. It is
appropriate when existing application logging is the intended signal, but it
does not provide a typed per-batch success record to application code.

Strict delivery returns immutable accepted-batch results and raises
`HecBatchDeliveryError` for classified failures. Retryable or uncertain batches
remain queued in order for an explicit later strict flush. Accepted and
terminally rejected batches are not queued again. Inspect typed fields rather
than parsing exception text or logging complete response bodies.

HEC delivery is at least once. If Splunk accepts a request but its response is
lost, retrying an uncertain batch can create duplicates. Events and downstream
searches should tolerate duplicate delivery or carry an application-owned
deduplication identifier.

ACK event POSTs are single-attempt because an automatic resend after a lost
response could silently create a duplicate associated with a different ACK ID.
An ACK timeout or status-query failure retains unconfirmed IDs; a later ACK
flush resumes polling without resending batches already accepted by HEC.

## Guided adoption and verification

An integrating agent should make each side effect visible and obtain approval
at the application's normal authorization boundary.

1. Confirm the release, Python version, Splunk product, endpoint, payload mode,
   delivery mode, execution style, target metadata, and secret reference.
2. Add the pinned dependency and adapt exactly one maintained example.
3. Unit-test configuration, event construction, queueing, flushing, results,
   and failures with a mocked sender or transport. Ordinary tests must not need
   a real host or token.
4. Use a non-production HEC token and test index for an approved live check.
   Treat the health call as optional preflight, not a delivery gate.
5. Send one standalone event containing a unique marker and flush it.
6. Send one three-event batch containing the same marker plus distinct batch
   positions, then flush it with the same selected mode.
7. Query Splunk through the application's approved search boundary. Confirm
   four individual event rows: one standalone row and three distinct batch
   positions. Sender-side success alone is insufficient evidence.
8. Exercise shutdown and failure behavior, including the final matching flush,
   a rejected index or token in an isolated test, and the application's retry
   and duplicate policy.

The repository's protected live workflow follows this send-and-query shape
with `querysplunk`. A consuming application may use its approved Splunk search
tool or UI; ingestion and search credentials should remain separate and
least-privileged.

## Prohibited shortcuts

- Do not paste, print, commit, or place a HEC or search token in generated code,
  documentation, test fixtures, logs, command history, or public issues.
- Do not guess that port 443 means Splunk Cloud or that port 8088 means Splunk
  Enterprise; confirm the deployment.
- Do not enable ACK merely because the methods exist. Confirm product support
  and token configuration first.
- Do not call synchronous wrappers from an existing event loop.
- Do not mix delivery modes or execution styles in one queued sequence.
- Do not omit the final matching flush.
- Do not treat health, HTTP acceptance, or ACK confirmation as proof of
  searchable event rows.
- Do not disable TLS verification to make an unexplained connection error
  disappear.
- Do not add an unbounded retry loop or claim exactly-once delivery.
- Do not install a production application from an untagged branch.

## Consumer integration checklist

- [ ] Pin v3.0.0 or deliberately retain immutable v2.1.2.
- [ ] Confirm Python 3.9 or later for v3.
- [ ] Confirm Splunk product, approved HEC hostname, port, TLS trust, index, and
      token permissions.
- [ ] Keep the token behind an application-owned secret reference.
- [ ] Select JSON or raw payloads before queueing.
- [ ] Select compatible, strict, or supported ACK delivery.
- [ ] Select synchronous or asynchronous methods and use the matching pair.
- [ ] Always perform the final matching flush during shutdown.
- [ ] Handle strict or ACK typed failures without exposing payloads or secrets.
- [ ] Document retry uncertainty and duplicate tolerance.
- [ ] Test offline with mocks before any live delivery.
- [ ] Send one standalone event and one three-event batch with a unique marker.
- [ ] Query Splunk and confirm four individual searchable event rows.
- [ ] Keep TLS verification enabled and debug logging bounded.
- [ ] Preserve the prior release pin as the rollback path until validation is
      complete.

For complete mode semantics, read the
[Delivery modes Wiki guide](https://github.com/georgestarcher/splunk_hec_aio/wiki/Delivery-Modes),
[Indexer acknowledgment Wiki guide](https://github.com/georgestarcher/splunk_hec_aio/wiki/Indexer-Acknowledgment),
and [Connectivity and troubleshooting guide](https://github.com/georgestarcher/splunk_hec_aio/wiki/Connectivity-and-Troubleshooting).
