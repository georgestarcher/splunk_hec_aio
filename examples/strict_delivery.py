"""Synchronous strict delivery with structured results and failures."""

import os
import time

from splunk_hec_aio.splunk_hec_aio import HecBatchDeliveryError, SplunkHecAio


def configured_sender():
    sender = SplunkHecAio(
        os.environ["SPLUNK_HEC_HOST"],
        os.environ["SPLUNK_HEC_TOKEN"],
    )
    sender.set_port(int(os.environ.get("SPLUNK_HEC_PORT", "443")))
    sender.set_sourcetype(os.environ.get("SPLUNK_HEC_SOURCETYPE", "splunk_hec_aio"))
    sender.set_source("splunk_hec_aio:strict-example")
    if index := os.environ.get("SPLUNK_HEC_INDEX"):
        sender.set_index(index)
    return sender


def main():
    sender = configured_sender()
    results = []
    try:
        results.extend(
            sender.post_data_strict(
                {
                    "time": round(time.time(), 3),
                    "event": {"message": "hello from strict delivery"},
                }
            )
        )
        results.extend(sender.flush_strict())
    except HecBatchDeliveryError as error:
        for result in error.results:
            print("accepted", result.batch_index, result.event_count)
        for failure in error.failures:
            print("failed", type(failure).__name__, str(failure))
        raise

    for result in results:
        print("accepted", result.batch_index, result.event_count)


if __name__ == "__main__":
    main()
