# Test suites

All default tests are deterministic and secret-free. They must never contact a
public network or a live Splunk instance.

## v2 characterization

The top-level `test_v2_*` modules characterize the public surface and selected
observable behavior of the v2.1.1 release.

Characterization tests record released behavior, including behavior that has a
separate issue proposing a correction. Update such a test only in the isolated,
approved change that replaces the behavior, and follow the rules in
`docs/compatibility.md`.

## Unit and protocol tests

`unit/` covers deterministic implementation helpers. `contract/` executes the
HTTP, gzip, batching, retry, and concurrency paths against controlled in-memory
fakes. These tests inspect exact request bodies without opening a socket.

Known specification gaps are expressed as narrow assertions of released v2
behavior linked to the issue that owns the correction. The owning change must
replace those assertions with the approved behavior and document the change.

Run the suite from the repository root:

```shell
PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=error python -m unittest discover -s tests -v
```

The initial compatibility CI job runs this command on Python 3.9 because the
baseline is locally verified on Python 3.9.6. That bootstrap target is not a
declaration of the minimum or complete supported Python range.

The **Quality** workflow runs the same deterministic tests under pytest on
Python 3.13 and enforces at least 70% branch coverage. Pytest is configured to
collect only `test_*.py` beneath `tests/`; `tests/legacy/` remains excluded.
Run that coverage gate from the repository root with:

```shell
python -m pytest --cov=splunk_hec_aio --cov-branch --cov-report=term-missing --cov-fail-under=70
```

`property/` contains bounded, deterministic Hypothesis checks for queue FIFO
behavior, JSON and raw transport round trips, and preservation across batching
boundaries. It intentionally has no `__init__.py`: pytest collects it in the
Python 3.13 quality environment, while the Python 3.9 unittest compatibility
suite remains free of modern tooling dependencies.

`test_live_integration_support.py` tests the live-workflow helper, query
template, and security boundaries entirely offline. The real HEC send and
querysplunk search run only from the manually approved GitHub Actions workflow.

## Packaging verification

`packaging/verify_artifacts.py` checks the built wheel and source distribution
metadata and contents. `packaging/verify_installed_distribution.py` is run by
GitHub Actions only after each artifact is installed into a clean environment
and the working directory has been moved outside the source checkout. This
prevents an in-tree import from hiding a broken installation.

The legacy test module was moved to `legacy/` so it is not installed as part of
the runtime package. It remains excluded from default test discovery because it
contains historical network-dependent cases.
