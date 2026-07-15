# Compatibility tests

These tests characterize the public surface and selected observable behavior of
the v2.1.1 release. They must remain secret-free and must never contact a public
network or a live Splunk instance.

Characterization tests record released behavior, including behavior that has a
separate issue proposing a correction. Update such a test only in the isolated,
approved change that replaces the behavior, and follow the rules in
`docs/compatibility.md`.

Run the suite from the repository root:

```shell
PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=error python -m unittest discover -s tests -v
```

The initial compatibility CI job runs this command on Python 3.9 because the
baseline is locally verified on Python 3.9.6. That bootstrap target is not a
declaration of the minimum or complete supported Python range.

`test_live_integration_support.py` tests the live-workflow helper, query
template, and security boundaries entirely offline. The real HEC send and
querysplunk search run only from the manually approved GitHub Actions workflow.
