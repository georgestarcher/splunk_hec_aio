# Examples

The existing [`example.py`](../example.py) remains at the repository root so
current users and documentation links continue to work. It is a high-volume
live example that sends events to the configured Splunk HEC endpoint.

Before running it:

- replace the placeholder host and token with your own configuration;
- use a test index and non-production HEC token;
- review the loop count and batching settings;
- never commit a real token or private endpoint; and
- do not run the example as part of the secret-free test suite.

Future focused examples should be added to this directory. Moving or replacing
the root example belongs to the packaging/layout migration tracked in issue
[#13](https://github.com/georgestarcher/splunk_hec_aio/issues/13).
