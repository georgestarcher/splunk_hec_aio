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
default concurrent-post limit is 10 and the maximum is 20. Smaller batches can
spread work across concurrent requests, but the best values depend on event
size, network latency, and the Splunk deployment. Enable DEBUG logging during a
controlled test when you need to inspect how events are divided among posts.

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
