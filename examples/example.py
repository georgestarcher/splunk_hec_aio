"""Compatible synchronous JSON delivery with explicit final flushing."""

import logging
import os
import time

from splunk_hec_aio.splunk_hec_aio import SplunkHecAio


def configured_sender():
    """Build a sender from environment variables without embedding a token."""
    sender = SplunkHecAio(
        os.environ["SPLUNK_HEC_HOST"],
        os.environ["SPLUNK_HEC_TOKEN"],
    )
    sender.set_port(int(os.environ.get("SPLUNK_HEC_PORT", "443")))
    sender.set_sourcetype(os.environ.get("SPLUNK_HEC_SOURCETYPE", "splunk_hec_aio"))
    sender.set_source("splunk_hec_aio:compatible-example")
    if index := os.environ.get("SPLUNK_HEC_INDEX"):
        sender.set_index(index)
    return sender


def main():
    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        level=logging.INFO,
    )
    event_count = int(os.environ.get("SPLUNK_HEC_EVENT_COUNT", "1"))
    if event_count < 1:
        raise ValueError("SPLUNK_HEC_EVENT_COUNT must be a positive integer")

    sender = configured_sender()
    for sequence in range(event_count):
        sender.post_data(
            {
                "time": round(time.time(), 3),
                "event": {
                    "message": "hello from compatible splunk_hec_aio delivery",
                    "sequence": sequence,
                },
            }
        )

    # Always flush so the final partial batch is sent before the process exits.
    sender.flush()


if __name__ == "__main__":
    main()
