# Migrating from v2.1.2 to v3.0.0

V3 is the modern supported release line. It keeps the documented nested import,
the existing synchronous method names and defaults, and the compatible
`post_data()`/`flush()` return contract. It intentionally raises the Python
floor and corrects several constructor, batching, payload, and connectivity
behaviors. Review those changes before replacing a v2.1.2 pin.

The immutable v2.1.2 release remains available. There is no requirement to
upgrade an application that depends on its older Python or exact runtime
behavior.

## Choose a release line

Stay on v2.1.2 when any of these are true:

- the application cannot run Python 3.9 or later;
- it depends on the exact v2.1.2 request bytes or characterization behavior;
- its upgrade and Splunk-side verification cannot be completed yet.

```shell
python -m pip install \
  "git+https://github.com/georgestarcher/splunk_hec_aio.git@v2.1.2"
```

Choose v3.0.0 when the application runs Python 3.9 or later and should use the
corrected HEC protocol behavior or the new opt-in strict, async, or indexer
acknowledgment APIs. Python 3.13 is the primary modern Splunk-aligned target.

```shell
python -m pip install \
  "git+https://github.com/georgestarcher/splunk_hec_aio.git@v3.0.0"
```

Both release lines are distributed through GitHub Releases rather than PyPI.
Pin a release tag; do not install production applications from an untagged
branch.

## Existing compatible delivery path

The documented import and familiar synchronous flow remain available:

```python
from splunk_hec_aio.splunk_hec_aio import SplunkHecAio

sender = SplunkHecAio(host, token)
sender.post_data(event)
sender.flush()
```

`post_data()` and `flush()` retain their `None` return contract and
logging-oriented failure handling. V3 does not silently switch existing callers
to strict results, async execution, or indexer acknowledgment. Applications can
upgrade on this compatible path before separately adopting a new mode.

Do not interpret API compatibility as identical wire behavior. V3 deliberately
corrects the behaviors listed below.

## Intentional behavior corrections

### Constructor inputs

`host` and `token` must now be non-empty strings. Missing, non-string, empty, or
whitespace-only values raise `ValueError` immediately. Validate configuration
before constructing the sender if an application previously used placeholders
such as `None`.

### String representation and connectivity

`str(sender)` no longer performs a network request. It reports connectivity as
`Reachable=NotChecked`. Call `check_connectivity()` or
`check_connectivity_async()` explicitly when a live health check is required.

Connectivity checks now use Splunk's unauthenticated HEC health endpoint rather
than sending an invalid event. A healthy response proves that the HEC service is
reachable; it does not validate the token or prove that an event was indexed.

### JSON payloads and batching

- JSON-mode batches are sent as concatenated complete HEC event envelopes, not
  as a JSON array. Splunk can therefore parse each item as an individual event.
- Batch limits use the exact uncompressed UTF-8 request-body byte count.
- An individually oversized event no longer creates an empty queued batch.
- Top-level numeric zero and `False` values are preserved by the default empty
  field policy.
- Configured metadata no longer mutates caller-owned payload dictionaries.
- Request channels use random UUIDv4 values instead of time- and node-derived
  identifiers.

These corrections can change request bytes and the resulting Splunk events.
Use representative Unicode, empty-field, single-event, and multi-event batches
in upgrade testing.

### Transport cleanup and cancellation

V3 consistently closes compatible GET and POST retry clients after success,
request failures, and cancellation. Existing compatible method signatures and
return values remain unchanged.

## Optional v3 delivery modes

Choose one delivery mode for a queued sequence and do not mix modes before
flushing it.

### Strict delivery

Use `post_data_strict()` and `flush_strict()` when the caller must receive
structured per-batch results and aggregate delivery failures. The async
equivalents are `post_data_strict_async()` and `flush_strict_async()`.

Strict mode defines bounded timeouts, response and transport failure types,
retryability, ordered retention of retryable or uncertain batches, and
cancellation behavior. A retry after an uncertain outcome can still duplicate
an event if Splunk accepted the original request but the response was lost.

### Async entry points

Applications that already run an event loop should await
`check_connectivity_async()`, `post_data_async()`, and `flush_async()` instead
of invoking the synchronous wrappers from that loop. The synchronous APIs
remain available for non-async callers.

### Indexer acknowledgment

Splunk Enterprise deployments with indexer acknowledgment enabled can use
`post_data_ack()` and `flush_ack()`, or their async equivalents. ACK mode uses a
stable channel and returns structured confirmation results. A timeout retains
pending acknowledgment IDs so a later ACK flush resumes polling without
automatically resending accepted event data.

ACK event POSTs are intentionally single-attempt. If the send outcome is
uncertain, any resend is an explicit caller decision because it may create a
duplicate. General HEC indexer acknowledgment is not available for ordinary
Splunk Cloud Platform HEC clients; Splunk documents a limited Cloud use case for
the AWS Kinesis Data Firehose integration.

See the [Delivery modes Wiki guide](https://github.com/georgestarcher/splunk_hec_aio/wiki/Delivery-Modes)
and [Indexer acknowledgment Wiki guide](https://github.com/georgestarcher/splunk_hec_aio/wiki/Indexer-Acknowledgment)
for the complete result, exception, polling, and retry contracts.

## Upgrade verification

Before changing a production pin:

1. Test on the same Python minor version used by the application. Include
   Python 3.9 and 3.13 when the deployment spans current Splunk runtimes.
2. Exercise the application's existing compatible path before adopting an
   optional delivery mode.
3. Send a standalone event and a small multi-event batch containing a unique
   marker.
4. Search Splunk for that marker and confirm the batch became the expected
   number of individual event rows.
5. Test failure and shutdown paths, including a final `flush()` and any retry
   or duplicate-delivery policy used by the application.

Sender-side HTTP success alone is not proof of searchable delivery. The
project's protected live integration follows the same send-and-query pattern
with querysplunk before a release is approved.

## Rollback

If validation finds an incompatibility, restore the v2.1.2 tag pin. Do not
replace or move release tags. Capture the Python version, selected delivery
mode, sanitized request shape, exception or result category, and Splunk-side
search evidence when reporting an upgrade problem.
