# Examples

The maintained [`example.py`](example.py) is a high-volume live example that
sends events to the configured Splunk HEC endpoint.

Before running it:

- replace the placeholder host and token with your own configuration;
- use a test index and non-production HEC token;
- review the loop count and batching settings;
- never commit a real token or private endpoint; and
- do not run the example live as part of the secret-free test suite.

Future focused examples should also be added to this directory.
