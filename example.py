"""main.py
    Demo use of HEC Class
"""

import logging
import sys
import time
import json

from splunk_hec_aio.splunk_hec_aio import SplunkHecAio

# help(SplunkHecAio)

# init logging config, this would be job of your main code using this class.
logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S %z')

log = logging.getLogger(u"MAIN")
log.setLevel(logging.INFO)

trustHEC = SplunkHecAio("MYINSTANCE.splunkcloud.com","MYTOKEN")
trustHEC.log.setLevel(logging.INFO)
trustHEC.set_port(443)

# Set Index and Sourctype for Post Parameters. Very helpful when using raw data mode.
trustHEC.set_index("starcher_hec")
trustHEC.set_sourcetype("aio_json")

# Setting Post Limits:
# We set to maximum number of AIO concurrent POSTs
trustHEC.set_concurrent_post_limit(20)
# set_post_max_byte_size: defaults to 512000 (max 800000)
# We set the smaller 10,000 max size to force data to spread across the AIO concurrent POSTs
trustHEC.set_post_max_byte_size(10000)

if not trustHEC.check_connectivity():
    sys.exit(1)

testJSON = {}

log.info("Starting Data Post")
for i in range(100000):
    testJSON.update({"event":{"count":i,"name":"dolly bean"}})
    testJSON.update({"time":str(round(time.time(),3))})
    trustHEC.post_data(testJSON)
    payloadLength = len(json.dumps(testJSON))

trustHEC.flush()

log.info("Completed Data Post: Post Max Size:{0} Max Payload Size:{1} Ratio to Event Size: {2}".format(trustHEC.get_post_max_byte_size(),payloadLength,round(20000/payloadLength,0)))

# This Example:
# time python3 main.py
# python3 main.py  11.78s user 0.35s system 58% cpu 20.806 total
# Completed Data Post: Post Max Size:10000 Max Payload Size:75 Ratio to Event Size: 267.0
 