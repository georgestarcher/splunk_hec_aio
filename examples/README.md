# Examples

These examples cover the supported v3 payload and delivery choices without
embedding a HEC token or private endpoint:

| Example | Purpose |
| --- | --- |
| [`example.py`](example.py) | Compatible synchronous JSON delivery and final flushing |
| [`strict_delivery.py`](strict_delivery.py) | Structured synchronous results and failures |
| [`async_strict_delivery.py`](async_strict_delivery.py) | Strict delivery inside asynchronous code |
| [`raw_delivery.py`](raw_delivery.py) | Raw-event mode and HEC metadata request parameters |
| [`indexer_acknowledgment.py`](indexer_acknowledgment.py) | Splunk Enterprise indexer acknowledgment |

Set the shared connection variables before running an example:

```shell
export SPLUNK_HEC_HOST="splunk.example.com"
export SPLUNK_HEC_TOKEN="replace-with-a-test-token"
export SPLUNK_HEC_PORT="443"
export SPLUNK_HEC_INDEX="test"
export SPLUNK_HEC_SOURCETYPE="splunk_hec_aio"
```

Then run a focused example from the repository root:

```shell
python examples/example.py
python examples/strict_delivery.py
python examples/async_strict_delivery.py
python examples/raw_delivery.py
```

Keep the token outside source code, use a test index and non-production token,
and always call the matching flush method before the process exits. These files
are copied into source distributions but are not installed by the wheel.

## Indexer acknowledgment safety gate

Run the ACK example only with Splunk Enterprise and a HEC token whose **Enable
indexer acknowledgment** option is on. General ACK use is not available to
ordinary Splunk Cloud Platform HEC clients. The example requires an additional
explicit opt-in so it cannot be run accidentally:

```shell
export SPLUNK_HEC_ENABLE_ACK_EXAMPLE="yes"
export SPLUNK_HEC_ACK_TIMEOUT="300"
export SPLUNK_HEC_ACK_POLL_INTERVAL="10"
python examples/indexer_acknowledgment.py
```

See the
[Delivery modes Wiki guide](https://github.com/georgestarcher/splunk_hec_aio/wiki/Delivery-Modes)
and
[Indexer acknowledgment Wiki guide](https://github.com/georgestarcher/splunk_hec_aio/wiki/Indexer-Acknowledgment)
before selecting a production delivery mode.
