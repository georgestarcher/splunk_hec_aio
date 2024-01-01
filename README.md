# Python Class for Sending Events to Splunk HTTP Event Collector

Version/Date: 2.1.0 2024-01-01

Author: George Starcher (starcher)
Email: george@georgestarcher.com

This code is presented **AS IS** under MIT license.

## Description:

This is a python class file for use with other python scripts to send events to a Splunk http event collector.

## Supported product(s): 

* Splunk

## Using this Python Class

### Configuration: Manual

You will need to put this with any other code and import the class as needed.
Instantiate a copy of the SplunkHecAio object and use to generate and submit payloads as you see in the example.

### Configuration: With pip

    pip3 install git+git://github.com/georgestarcher/splunk_hec_aio.git

### Example:

        import logging
        import sys
        import time
        import json

        from splunk_hec_aio.splunk_hec_aio import SplunkHecAio

        # help(SplunkHecAio)

        # init logging config, this is the job of your main code using this class.
        logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S %z')

        log = logging.getLogger(u"MAIN")
        log.setLevel(logging.INFO)

        # instantiate a HEC AIO Sender using server name and HEC token.
        testHec = SplunkHecAio("MYINSTANCE.splunkcloud.com","MYTOKEN")

        # Set HEC logging level (Default is INFO, can set to DEBUG if needed)
        testHec.log.setLevel(logging.INFO)

        # Splunkcloud needs port 443 (Default is 8088)
        testHec.set_port(443)

        # Set Index and Sourctype for Post Parameters. Very helpful when using raw data mode.
        testHec.set_index("starcher_hec")
        testHec.set_sourcetype("aio_json")

        # Setting Post Limits:
        # We set to maximum number of AIO concurrent POSTs
        testHec.set_concurrent_post_limit(20)
        # set_post_max_byte_size: defaults to 512000 (max 800000)
        # We set the smaller 10,000 max size to force data to spread across the AIO concurrent POSTs
        testHec.set_post_max_byte_size(10000)

        if not testHec.check_connectivity():
            sys.exit(1)

        testJSON = {}

        log.info("Starting Data Post")
        for i in range(100000):
            testJSON.update({"event":{"count":i,"name":"dolly bean"}})
            testJSON.update({"time":str(round(time.time(),3))})
            testHec.post_data(testJSON)
            payloadLength = len(json.dumps(testJSON))

        # Always call flush method to ensure last data is posted to Splunk HEC
        testHec.flush()

## Notes

### Post Performance:

I recommend testing your data payloads to determine their maximum size. Then lower the set_post_max_byte_size down to get in the range of 100-200 events per HTTP post. This helps spread the workload across the AIO HTTP posts for performance. The default set_post_max_byte_size is 512000. So lower it if your max event payload is notably smaller. Raise as needed up to the 800000 maximum. Then if needed adjust set_concurrent_post_limit. Maximum is 20 AIO concurrent posts, default is 10.  You could run in DEUG Logging to see the post spread across when first developing your code.

### JSON vs RAW mode:

Typically when working in Python your data is a list of dictionary (JSON) objects. This class is intended for that as the norm so you can iterate over the data and blast it into Splunk HEC with minimal work. 

If you choose to post raw string lines you will want to set set_payload_json_format to False. Then your payload input to post_data should be a string. To make forcing the index, sourcetype, host and source of raw events easier set these prior to data posting.

    hec_server.index = "test"
    hec_server.sourcetype = "syslog"
    hec_server.set_host("dollybean")
    hec_server.set_source("aio_python")

This works for either RAW or JSON. JSON has the option of the normal existing behavior to override per event by placing in the payload. But it is meant for RAW mode as it adds the values to the HEC POST URL parameters.