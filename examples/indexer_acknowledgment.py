"""Splunk Enterprise indexer-acknowledgment delivery."""

import os
import time

from splunk_hec_aio.splunk_hec_aio import HecAcknowledgmentError, SplunkHecAio


def configured_sender():
    sender = SplunkHecAio(
        os.environ["SPLUNK_HEC_HOST"],
        os.environ["SPLUNK_HEC_TOKEN"],
    )
    sender.set_port(int(os.environ.get("SPLUNK_HEC_PORT", "8088")))
    sender.set_sourcetype(os.environ.get("SPLUNK_HEC_SOURCETYPE", "splunk_hec_aio"))
    sender.set_source("splunk_hec_aio:ack-example")
    if index := os.environ.get("SPLUNK_HEC_INDEX"):
        sender.set_index(index)
    return sender


def main():
    if os.environ.get("SPLUNK_HEC_ENABLE_ACK_EXAMPLE") != "yes":
        raise RuntimeError(
            "Set SPLUNK_HEC_ENABLE_ACK_EXAMPLE=yes only after confirming that "
            "this Splunk Enterprise HEC token has indexer acknowledgment enabled."
        )

    timeout = float(os.environ.get("SPLUNK_HEC_ACK_TIMEOUT", "300"))
    poll_interval = float(os.environ.get("SPLUNK_HEC_ACK_POLL_INTERVAL", "10"))
    sender = configured_sender()
    confirmed = []
    try:
        confirmed.extend(
            sender.post_data_ack(
                {
                    "time": round(time.time(), 3),
                    "event": {"message": "hello from indexer acknowledgment"},
                },
                timeout=timeout,
                poll_interval=poll_interval,
            )
        )
        confirmed.extend(sender.flush_ack(timeout=timeout, poll_interval=poll_interval))
    except HecAcknowledgmentError as error:
        for result in error.results:
            print("acknowledged", result.batch_index, result.ack_id)
        for failure in error.failures:
            print(
                "unconfirmed",
                failure.batch_index,
                failure.ack_id,
                failure.category,
                failure.retryable,
            )
        raise

    for result in confirmed:
        print("acknowledged", result.batch_index, result.ack_id)


if __name__ == "__main__":
    main()
