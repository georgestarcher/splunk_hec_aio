"""Compatible raw-event delivery with HEC metadata request parameters."""

import os
import time

from splunk_hec_aio.splunk_hec_aio import SplunkHecAio


def main():
    sender = SplunkHecAio(
        os.environ["SPLUNK_HEC_HOST"],
        os.environ["SPLUNK_HEC_TOKEN"],
    )
    sender.set_port(int(os.environ.get("SPLUNK_HEC_PORT", "443")))
    sender.set_payload_json_format(False)
    sender.set_sourcetype(os.environ.get("SPLUNK_HEC_SOURCETYPE", "splunk_hec_aio_raw"))
    sender.set_source("splunk_hec_aio:raw-example")
    sender.set_host(os.environ.get("SPLUNK_EVENT_HOST", "example-host"))
    if index := os.environ.get("SPLUNK_HEC_INDEX"):
        sender.set_index(index)

    sender.post_data("{} hello from raw delivery\n".format(round(time.time(), 3)))
    sender.flush()


if __name__ == "__main__":
    main()
