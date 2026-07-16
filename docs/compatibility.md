# v2 compatibility contract

`splunk_hec_aio` has active users. The immutable v2.1.2 release preserves the
v2.1.1 behavior captured by the repository's compatibility baseline. The v3
development line keeps that evidence intact while each approved behavior
change is reviewed separately.

The characterization tests under `tests/` describe that baseline. They are
deliberately separate from tests that specify corrected or new behavior. A
characterization test is evidence of what v2.1.1 does; it is not necessarily a
claim that the behavior is ideal.

## Protected compatibility surface

Within the v2 release line, maintainers should preserve:

- the distribution and package names;
- the documented import path
  `from splunk_hec_aio.splunk_hec_aio import SplunkHecAio`;
- public class and method names, signatures, positional arguments, keyword
  arguments, and defaults;
- successful-call return values and existing exception behavior;
- existing synchronous entry points;
- default configuration, queueing, batching, retry, and flush behavior;
- request endpoints, headers, parameters, payload shaping, and compression,
  except for an explicitly approved protocol bug fix;
- Python versions that are established as supported by compatibility evidence.

V2.1.2 retains its historical `python_requires >3.5` metadata. V3 declares
`python_requires >=3.9`: Python 3.9 is the supported compatibility floor and
Python 3.13 is the primary modern Splunk-aligned target. Current-Python lint,
type, audit, and build tools remain separate from the runtime compatibility
suite.

## Change classifications

Every pull request that can affect users should select one classification:

1. **No observable behavior change** — tests, documentation, CI, repository
   governance, or an internal refactor that preserves the protected surface.
2. **Backward-compatible bug fix** — an observable correction that keeps public
   entry points usable. It requires focused before-and-after tests and release
   notes.
3. **Opt-in addition** — a new API or mode that is disabled by default and does
   not alter existing callers.
4. **Breaking change** — a removed import, changed signature or default, new
   default exception, higher Python floor, or other incompatible behavior.

Breaking changes are not eligible for a v2 release unless a compatibility shim
preserves existing callers.

## Rules for approved behavior changes

A characterization test may change only when the pull request:

- identifies the exact released behavior being changed;
- links the issue approving the change and its classification;
- adds a test for the intended replacement behavior;
- explains migration impact in release notes;
- uses an opt-in path when that can preserve v2 callers; and
- performs live Splunk verification when request bytes or endpoint semantics
  change.

New async entry points, strict delivery results, and indexer acknowledgment must
remain additive and opt-in in v3. Existing synchronous methods retain their
signatures, defaults, return values, and exception behavior.

The v3 strict delivery API follows this rule by adding `post_data_strict()` and
`flush_strict()`. Async applications can opt into
`check_connectivity_async()`, `post_data_async()`, `flush_async()`,
`post_data_strict_async()`, and `flush_strict_async()` so they await the same
internals without starting another event loop. The legacy synchronous methods
and defaults remain unchanged. Strict callers opt into explicit timeouts,
structured per-batch results, and propagated aggregate failures; callers that
do not select the new methods retain the compatibility baseline.

Indexer acknowledgment is selected only through `post_data_ack()` and
`flush_ack()`, or their async counterparts. It does not change compatible or
strict request headers, results, retries, defaults, or queue behavior. ACK mode
uses a lazy stable channel for its own event and status requests. Confirmed IDs
are removed immediately and never polled again. Timeout and cancellation leave
unconfirmed IDs pending so a later ACK flush resumes polling without
automatically resending an accepted event batch. This avoids creating
duplicates when HEC accepted a batch but its acknowledgment status remains
uncertain.

ACK event POSTs do not inherit strict mode's automatic transport retries. If a
request or response becomes uncertain, the batch remains queued and the typed
failure makes any later resend an explicit caller action. Such a resend can
still create a duplicate when Splunk accepted the original request but its
response was lost. ACK status polling remains safely retryable because it does
not resend event data.

ACK response and failure objects contain batch metadata and acknowledgment IDs,
not event contents, token values, or arbitrary response bodies. A confirmed
indexer acknowledgment proves the configured replication condition, not event
parsing or searchability. The protected query-backed live integration remains
the separate evidence for indexed, searchable individual events.

## Running the baseline

The compatibility suite uses `unittest` from the Python standard library so it
does not establish a new runtime dependency or Python-version floor:

```shell
python -m unittest discover -s tests -v
```

The suite performs no network requests and needs no Splunk host or token.

The packaging workflow separately builds the wheel and source distribution,
checks their metadata and file allowlists, installs each artifact into a clean
environment, and runs the nested-import and v2 public-API snapshot from outside
the checkout on Python 3.9 and 3.13. Runtime CI also exercises Python 3.10,
3.11, and 3.12 on Linux, plus Python 3.9 and 3.13 on macOS and Windows.

Version 2.1.2 remains the final planned legacy-compatible v2 release. V3 begins
at `3.0.0.dev0` with a minimum of Python 3.9. Raising that floor is the only
intentional compatibility break in the foundation change; constructor,
string, async, transport, endpoint, batching, retry, logging, and failure
behavior remain unchanged until their focused v3 issues are approved.
