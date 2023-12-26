"""splunk_hec_aio.py
    Splunk payload submission class to HTTP collector endpoint
"""

__version__ = "2.0.0"

import json
import logging
import gzip
import uuid

import asyncio
from aiohttp import ClientSession
from aiohttp_retry import RetryClient, JitterRetry

# Class for Queue objects.
class _SplunkQueue:
    """
    This is an internal class for Queue objects.
      
    Attributes:
        elements (list): Optional list of elements to place on the queue at initializaiton.
    """

    def __init__(self, elements = None):
        """
        The constructor for _Queue class.
  
        Parameters:
           elements (list): Optional list of elements to place on the queue at initializaiton  
        """

        if elements is None:
            self.elements = list()
        else:
            self.elements = elements

    def enqueue(self, item):
        """Add an element to the queue.

            Parameters:
                item (dict): dictionary item to add to the queue
            Returns:
                none
        """
        self.elements.append(item)

    def dequeue(self):
        """Remove an element to the queue.

            Parameters:
               none
            Returns:
                dict: dictionary item removed from the queue
        """

        if self.elements:
            return self.elements.pop(0)
      
    def clear(self):
        """Clears the queue of all elements.

            Parameters:
               none
            Returns:
                none
        """
         
        self.elements = list()

    def __str__(self):
        """Outputs current list of elements in the queue.

            Parameters:
               none
            Returns:
                str: string of the list of the elements in the queue.
        """
        return str(self.elements)

    @property
    def size(self):
        """Property returns the number of elements in the queue.
            
            Returns:
                int: length of the queue
        """
        return(len(self.elements))
    
    @property
    def first(self):
        """Property returns the first element in the queue.

            Does not remove the returned item from the queue.
            
            Returns:
                dict: the first element in the queue
        """

        if self.size>=1:
            return self.elements[0]

    @property
    def last(self):
        """Property returns the last element in the queue.

            Does not remove the returned item from the queue.
            
            Returns:
                dict: the last element in the queue
        """

        if self.size>=1:
            return self.elements[-1]

    @property
    def is_empty(self):
        """Property returns if the queue is empty.
            
            Returns:
                bool: the boolean representing if the queue is empty
        """
        return (self.size == 0)
    
    @property
    def byte_size(self):
        """Property returns the size in bytes of the queue.

            The size is the length of the JSON string representation of the queue elements.
            
            Returns:
                int: the size of the string representation of the elements in the queue
        """
        if not self.is_empty:
            return(len(json.dumps(self.elements,default=str)))
        else:
            return(0)


# Splunk HTTP Sender Class
class SplunkHecAio:
    """
    This is a class for posting JSON dictionary data to the Splunk HTTP Endpoint.
      
   Arguments:
        SPLUNK_HOST -- The Splunk HOST - required (Example: myhost.splunkcloud.com)
        SPLUNK_TOKEN -- The configured HEC Token - required

    Functions:
        check_connectivity() returns:(bool) - returns if configured Splunk API instance is reachable
        post_data(dict OR str) returns(none) - posts JSON dictionary OR plain/text to configured Splunk HTTP API Endpoint
            NOTE: payload type is controlled by set_payload_json_format listed below and should be setup at instantiation
        flush() - returns(none) - required call before exiting your code to flush any remaining batched data
        set_pop_empty_fields(bool) - returns(none) - accepts bool value to control if empty/null fields are removed. Default is True.
        get_pop_empty_fields() - returns(bool) - displays current value controlling removing empty/null fields
        set_payload_json_format(bool) - returns(none) - accepts bool value to control payload format is application/json (True) or text/plain (False). Default is True.
        get_payload_json_format() - returns(bool) - displays current value controlling removing empty/null fields
        set_concurrent_post_limit(int) - returns(none) - accepts value 1-20. Defaults to 10.
        get_concurrent_post_limit() - returns(int) - displays current concurrent http post limit
        set_post_max_byte_size(int) - returns(none) - accepts value 4000-800000. Defaults to 512000.
        get_post_max_byte_size() - returns(int) - displays current http max bytes post size.
        set_verify_tls(bool) - returns(none) - accepts bool value to control if HTTP TLS certificates are verified. Default is True.
        get_verify_tls() - returns(bool) - displays current value controlling TLS certificate verification.
        set_index(string) - returns(none) - accepts string value to control if HTTP Posts place index value as a parameter. Default is None.
        get_index() - returns(string) - displays current value controlling HTTP Post parameter index value.
        set_sourcetype(string) - returns(none) - accepts string value to control if HTTP Posts place sourcetype value as a parameter. Default is None.
        get_sourcetype() - returns(string) - displays current value controlling HTTP Post parameter sourcetype value.
        set_https(bool) - returns(none) - accepts bool value to control if HTTPS is used in the Splunk URL. Default is True.
        get_https() - returns(bool) - displays current value controlling if HTTPS is used in the Splunk URL.
     
    Help:
    
        from splunk_hec_aio.splunk_hec_aio import SplunkHecAio
        help(SplunkHecAio)

    Example Usage:

        import logging
        import sys
        import time
        import json

        from splunk_hec_aio.splunk_hec_aio import SplunkHecAio

        splunkSender = SplunkHecAio($SPLUNK_SERVER$,$SPLUNK_TOKEN$)
        splunkSender.log.setLevel(logging.DEBUG)
        splunkSender.set_port(443)

        # Helpful when in raw payload mode
        splunkSender.set_index("myindex")
        splunkSender.set_sourcetype("mysourcetype")

        testJSON = dict()
        testJSON.update({"event":{"count":10,"name":"dolly bean"}})
        testJSON.update({"time":str(round(time.time(),3))})

        if not splunkSender.check_connectivity():
            sys.exit(1)

        splunkSender.post_data(testJSON)

        splunkSender.flush()

    """

    # ASync Web Get Method
    async def _http_get_task(self,work_queue):

        # Use JitteryRetry which is exponential with some randomness.
        retry_options = JitterRetry(attempts=self.http_retries,statuses=self.retry_http_status_codes)

        async with ClientSession() as session:
            retry_client = RetryClient(session,self.http_raise_for_status)

            while not work_queue.empty():
                try:
                    url = await work_queue.get()
                    async with retry_client.get(url,verify_ssl=self.get_verify_tls(),headers=self.splunk_headers,retry_options=retry_options) as response:
                        await response.text()   
                    await retry_client.close()
                    return(response.status,response.reason) 
                except Exception as e:
                    self.log.exception(e)

    # ASync Web Post Method
    async def _http_post_task(self,url,work_queue):

       # Use JitteryRetry which is exponential with some randomness.
        retry_options = JitterRetry(attempts=self.http_retries,statuses=self.retry_http_status_codes)

        async with ClientSession() as session:
            retry_client = RetryClient(session,self.http_raise_for_status)

            while not work_queue.empty():
                try:
                    payload = await work_queue.get()
                    if isinstance(payload, list) and len(payload) == 0:
                        continue
                    
                    self.log.debug("Payload JSON Mode:{0} Events:{1}".format(self._payload_mode_json,len(payload)))
                    response = ""

                    if self._payload_mode_json:
                         # If True payload is expected to be form application/json
                        payload_string = gzip.compress(json.dumps(payload).encode('utf-8'))
                        if payload_string:
                            async with retry_client.post(url,verify_ssl=self.get_verify_tls(),headers=self.splunk_headers,retry_options=retry_options,params=self.splunk_params,data=payload_string) as response:
                                await response.text()               
                            if response.status == 400:
                                raise(ValueError(response.text))
                    else:
                        # If False payload is expected to be form text/plain
                        payload_batch = "".join(payload)
                        payload_string = gzip.compress(payload_batch.encode('utf-8'))
                        
                        if payload_string:
                            async with retry_client.post(url,verify_ssl=self.get_verify_tls(),headers=self.splunk_headers,retry_options=retry_options,params=self.splunk_params,data=payload_string) as response:
                                await response.text()               
                        if response.status == 400:
                            raise(ValueError(response.text))
                except Exception as e:
                    self.log.exception(e)
                    raise e

        await retry_client.close()

        return(response.status,response.reason) 
    
     # ASync Web Post Method Specific for Checking HEC Reachability and Authentication
    async def _http_health_task(self,url,work_queue):

       # Use JitteryRetry which is exponential with some randomness.
        retry_options = JitterRetry(max_timeout=0.3,attempts=1.0,statuses=self.retry_http_status_codes)

        health_headers = dict()
        health_headers["Authorization"] = "Splunk %s" % (self.token)
        health_headers["Content-Encoding"] = "gzip"
        health_headers["Content-Type"] = "application/json"
        health_headers["User-Agent"] = "Splunk-hec-sender/2.0 (Python)"

        async with ClientSession() as session:
            retry_client = RetryClient(session,self.http_raise_for_status)

            while not work_queue.empty():
                try:
                    payload = await work_queue.get()
                    payload_string = gzip.compress(json.dumps(payload).encode('utf-8'))
                    async with retry_client.post(url,verify_ssl=self.get_verify_tls(),headers=health_headers,retry_options=retry_options,params=self.splunk_params,data=payload_string) as response:
                        await response.json()              
                    await retry_client.close()
                    return(response.status,response.reason) 
                except Exception as e:
                    self.log.debug(e)
        return()

    def __init__(self,host: str,token: str):
        """
        The constructor for the SplunkHttpSender class.
  
        Parameters:
            hec_host (string): Required Splunk HEC hostname/ip.
            token (string): Required the API Token for the datastream to receive the data.
        """

        self.log = logging.getLogger(u"SPLUNK_HEC")
        self.log.setLevel(logging.INFO)

        self.host = host
        self.token = token
  
        if self._http_post_task is None:
            raise(ValueError("HOST is missing."))
        if self.token is None:
            raise(ValueError("HEC Token is missing."))

        # Set HEC HTTP Header to default True
        self.set_https()

        # Set HEC server port to default 8088
        self.set_port()

        # Set pop empty fields to default True
        self.set_pop_empty_fields()

        # Set payload application/json mode to default True
        self.set_payload_json_format()

        # Set optional URL Parameters for index and sourcetype. This appends to the post URL.
        # We default to None as these are optional and the user should intentionally set the values. 
        self._index = None
        self._sourcetype = None

        # Set HTTP Controls
        self.http_raise_for_status = False
        self.http_retries = 3
        self.set_verify_tls()

        # Set Default batch max size for max bytes for the HTTP Endpoint.
        # Auto flush will occur if next event payload will exceed limit.
        # Default 10000
        self.set_post_max_byte_size()

        # Number of "threads" used to send events to the endpoint (max concurrency).
        self.set_concurrent_post_limit()

        # Create initial queue of payloads.
        self.payload_queue = _SplunkQueue()

        # Create queue of combined payloads for http batch payload posts.
        self.post_queue = _SplunkQueue()

        self.log.info("Splunk HEC Ready: host=%s",self.host)

    def __str__(self):
        """Outputs the information about Splunk HTTP HEC

            Parameters:
               none
            Returns:
                str: string of the attributes of the configured Splunk HTTP receiver.
        """
        return "Splunk: HOST={0} HTTPS={1} Reachable={2} PopEmptyFields={3} PayloadModeJSON={4} ConcurrentPostLimit={5}".format(self.host,self.get_https(),self.check_connectivity(),self._pop_empty_fields,self._payload_mode_json,self.get_concurrent_post_limit())
  
    @property 
    def retry_http_status_codes(self):
        """Property returns HTTP status codes to retry.

            Codes to retry: [408, 500, 502, 503, 504]

            Returns:
                dict: list of http codes to force retry for.
        
        Notes:
            https://developer.mozilla.org/en-US/docs/Web/HTTP/Status
        """

        status_codes = {408}    # 408 Request Timeout
        status_codes.add(429)   # 429 Too Many Retries
        status_codes.add(500)   # 500 Internal Server Error
        status_codes.add(502)   # 502 Bad Gateway
        status_codes.add(503)   # 503 Service Unavailable
        status_codes.add(504)   # 504 Gateway Timeout
    
        return(status_codes)
    
    @property 
    def splunk_post_url(self):
        """Property returns Splunk HEC Post URL.
            
            Returns:
                string: formed URL for the Splunk HEC endpoint.
        """
        if self.get_https():
             http_header = "https"
        else:
             http_header = "http"
             
        if self._payload_mode_json is None or self._payload_mode_json is False:
            url = "%s://%s:%d/services/collector/raw" % (http_header, self.host,self._port)
        else:
            url = "%s://%s:%d/services/collector/event" % (http_header,self.host,self._port)

        return(url)
    
    @property 
    def splunk_health_url(self):
        """Property returns Splunk API HTTP Health Check URL.

            We use the JSON event endpoint because we want our empty payload to return a 400 not index an empty event.
                  
            Returns:
                string: formed URL for the Splunk API heath check endpoint.
        """

        if self.get_https():
            http_header = "https"
        else:
            http_header = "http"

        url = "%s://%s:%d/services/collector/event" % (http_header,self.host,self._port)

        return url

    @property
    def splunk_headers(self):
        """Property returns the required Splunk HTTP Headers."""

        headers = dict()
        headers["Authorization"] = "Splunk %s" % (self.token)
        headers["Content-Encoding"] = "gzip"
        if self._payload_mode_json:
            headers["Content-Type"] = "application/json"
        else:
            headers["Content-Type"] = "text/plain"
        headers["User-Agent"] = "Splunk-hec-sender/1.0 (Python)"
        headers["X-Splunk-Request-Channel"] = str(uuid.uuid1())
        return headers

    @property
    def splunk_params(self):
        """Property returns the required Splunk HTTP Headers."""

        params = dict()
        if not self._payload_mode_json:
            params["channel"] = str(uuid.uuid1())
        if self._index:
            params["index"] = self._index
        if self._sourcetype:
            params['sourcetype'] = self._sourcetype

        return params
    
    def set_https(self,value=True):
        """Set HEC Service HTTPS URL (bool).

        This sets the HTTPS portion of HEC Service URL. Default is True.

        Parameters:
                value (bool): Expected format example True
        Returns:
                none

        """

        if type(value) != bool:
            self.log.error("Non Bool Value: {0}".format(value))
            return
        
        self._https = value
        self.log.info("Splunk HEC HTTPS URL Set: https={0}".format(value))

    def get_https(self):
        """Get HEC Service HTTPS URL (bool).
        
            Default value is True
            Value: True

            Parameters:
                none
            Returns:
                bool: value of HEC HTTPS url Header
                
        """

        return self._https

    def set_port(self,value=8088):
        """Set HEC Service Port (int).

        This sets the expected HEC Collector Service Port. Default is 8000.

        Parameters:
                value (string): Expected format example `8000`
        Returns:
                none

        """

        if type(value) != int or value <=0 :
            self.log.error("Invalid Value: {0}".format(value))
            return

        self._port = value
        self.log.info("Splunk HEC Port Set: port={0}".format(value))

    def get_port(self):
        """Get the HEC port value (int).
        
            Default value is 8088
            Value: 8088

            Parameters:
                none
            Returns:
                int: value of HEC Service Port
                
        """

        return self._port

    def set_pop_empty_fields(self,value=True):
        """Set pop empty fields mode (bool).

        This mode only works for payload mode (True) application/json. It is ignored for payload mode (False) text/plain.

        Parameters:
                value (bool): Sets if empty/null fields are removed from the payload before posting.
        Returns:
                none

        """
        if type(value) != bool:
            self.log.error("Non Bool Value: {0}".format(value))
            return

        self._pop_empty_fields = value
        self.log.info("Splunk Mode Set: pop_empty_fields={0}".format(value))

    def get_pop_empty_fields(self):
        """Get pop empty fields mode (bool).
        
            Default value is True to save data ingestion cost.

            Parameters:
                none
            Returns:
                bool: True/False control if empty fields are removed from payloads.
        """

        return self._pop_empty_fields

    def set_concurrent_post_limit(self,value=10):
        """Set Post Concurrent Limit (int).

        Parameters:
                value (int): Sets the max number of async posts
        Note:
                default to 10
        Returns:
                none

        """

        if type(value) != int or value <=0 :
            self.log.error("Invalid Value: {0}".format(value))
            return

        value = max(value, 1)
        value = min(value, 20)

        self._concurrent_post_limit = value

        # Set the work queue with the size for limit  
        self.work_queue = asyncio.Queue(maxsize=self.get_concurrent_post_limit())

        self.log.info("Splunk Post Max Concurrent limit: concurrent_post_limit={0}".format(value))

    def get_concurrent_post_limit(self):
        """Get Maximum ssync concurrent posts (int).
        
            Default value is 2 - maximum number of concurrent async http posts
            Value: 2

            Parameters:
                none
            Returns:
                int: the maximum concurrent async post limit
                
        """

        return self._concurrent_post_limit

    def set_post_max_byte_size(self,value=512000):
        """Set Post Max Byte Size (int).

        Parameters:
                value (int): Sets the max byte size per HTTP post
        Note:
                Thanks to Brett Adams of the SplunkTrust for default limit input to support older Splunk versions.
                The value is recommended to be set to a size that is approximately 256 * the max  of a data payload length.
                This better fit value forces more spread across the AIO concurrent posts for better performance.
        Returns:
                none

        """

        if not isinstance(value, int) or value <=0 :
            self.log.error("Invalid Value: {0}".format(value))
            return

        # Maximum value based on current max_content_length in https://docs.splunk.com/Documentation/Splunk/9.1.2/Admin/Limitsconf 
        value = max(value, 4000)
        value = min(value, 800000)
        self._max_byte_size = value

        self.log.info("Splunk Post Max Byte Size: max_byte_size={0}".format(value))

    def get_post_max_byte_size(self):
        """Get payload plain JSON mode (bool).
        
            Default value is True - payload is expected to be a application/json dict.
            Value: False - payload is expected to be text/plain.

            Parameters:
                none
            Returns:
                bool: True/False control if payload is plain JSON dict.
                
        """

        return self._max_byte_size
       
    def set_payload_json_format(self,value=True):
        """Set payload plain JSON mode (bool).

        Parameters:
                value (bool): Sets if empty/null fields are removed from the payload before posting.
                * Value: True - payload is expected to be a application/json dict.
                * Value: False - payload is expected to be text/plain. User will need to configure LINE_BREAKER in Splunk
        Returns:
                none

        """

        if not isinstance(value, bool):
            self.log.error("Non Bool Value: {0}".format(value))
            return

        self._payload_mode_json = value
        self.log.info("Splunk Mode Set: payload_mode_json={0}".format(value))

    def get_payload_json_format(self):
        """Get payload plain JSON mode (bool).
        
            Value:  True - application/json
                    False - plain/text

            Parameters:
                none
            Returns:
                bool: payload format
                
        """

        return self._payload_mode_json

    def set_verify_tls(self,value=True):
        """Set verify TLS verification (bool).

        Parameters:
                value (bool): Sets if HTTPS methods perform TLS verification
                * Value: True - TLS is verified.
                * Value: False - TLS is not verified.
        Returns:
                none

        """

        if not isinstance(value, bool):
            self.log.error("Non Bool Value: {0}".format(value))
            return

        self._verify_tls = value
        self.log.info("Splunk Mode Set: verify_tls={0}".format(value))

    def get_verify_tls(self):
        """Get veritfy TLS JSON mode (bool).
        
            Value:  True - TLS is to verify.
                    False - TLS is to not verify.

            Parameters:
                none
            Returns:
                bool: verify TLS for HTTPS Connections
                
        """

        return self._verify_tls

    def set_index(self,value=None):
        """Set HEC Index Value to use in Post URL parameters (string).

        This sets the optional URL parameter index=... Default is None.
        Some users may want to specify the target index in the URL for Post instead of in the event JSON payload.
        This is useful for raw data mode.
        The configured HEC Token does need permission to post into the specified index.

        Parameters:
                value (string): Expected format example `myindex`
        Returns:
                none

        """

        if not isinstance(value,str):
            self.log.error("Invalid Value: {0}".format(value))
            return

        self._index = value
        self.log.info("Splunk Default Index Set: port={0}".format(value))

    def get_index(self):
        """Get the HEC default index optionally used in Post URL (string).
        
            Default value is None
            Value: "myindex"

            Parameters:
                none
            Returns:
                string: value of HEC Default Index Token in URL
                
        """

        return self._index

    def set_sourcetype(self,value=None):
        """Set HEC Sourectype Value to use in Post URL parameters (string).

        This sets the optional URL parameter sourcetype=... Default is None.
        Some users may want to specify the target sourcetype in the URL for Post instead of in the event JSON payload.
        This is useful for raw data mode.

        Parameters:
                value (string): Expected format example `mysourcetype`
        Returns:
                none

        """

        if not isinstance(value, str):
            self.log.error("Invalid Value: {0}".format(value))
            return
   
        self._sourcetype = value
        self.log.info("Splunk Default Index Set: port={0}".format(value))

    def get_sourcetype(self):
        """Get the HEC default sourcetype optionally used in Post URL (string).
        
            Default value is None
            Value: "mysourcetype"

            Parameters:
                none
            Returns:
                string: value of HEC Default Sourcetype Token in URL
                
        """

        return self._sourcetype
    
    def check_connectivity(self):
        """Checks connectivity to the Splunk API.

        Reference:
            https://docs.splunk.com/Documentation/Splunk/9.1.2/Data/TroubleshootHTTPEventCollector

        Notes: 
            method will log warning on reachable errors such as bad token
            method will warn on splunk hec server health codes

        Returns:
            bool: Boolean result of if HEC is reachable
        Notes:
            method will warn on server health codes
        """

        is_available = asyncio.run(self._check_connectivity())

        return is_available

    async def _check_connectivity(self):
        """Private ASYNC function to check connectivity to the Splunk API.

        Returns:
            bool: Boolean result of if API is reachable
        Notes:
            Method will log warnings on server health codes [500,503].
            Internal Method.
        """

        self.log.info("Checking Splunk reachability. HOST=%s",self.host)

        response = dict() 
        splunk_reachable = False
        # We add 400 Bad Request to Acceptable since our test payload won't be indexed. But URL and Token will be checked.
        ACCEPTABLE_STATUS_CODES = [200,400]
        AUTHENTICATION_ERROR_STATUS_CODES = [401,403]
        HEATH_WARNING_STATUS_CODES = [500,503]

        try:

            # Intentionally make useless payload
            work_item = {}

            await self.work_queue.put(work_item)
            response = await asyncio.gather(
                asyncio.create_task(self._http_health_task(self.splunk_health_url,self.work_queue)),
                )

            response_status_code = "unknown"
            response_text = ""

            if not response[0]:
                self.log.warning("Splunk is unreachable. HOST=%s",self.host)
                self.log.debug("RESPONSE: {0}".format(response))
                return splunk_reachable
            else:
                try:
                    response_status_code, response_text = response[0]
                except:
                    self.log.debug("RESPONSE: {0}".format(response))
                    raise ConnectionError("Unreachable.")

            # A 400 is acceptable as this only comes up if the URL and TOKEN are valid and reachable
            if response_status_code==200 or response_status_code == 400:
                self.log.info("Splunk is reachable. HOST=%s",self.host)
                splunk_reachable = True
            else:
                if response_status_code in ACCEPTABLE_STATUS_CODES:
                    self.log.info("Splunk is reachable. HOST=%s",self.host)
                    self.log.warning("Connectivity Check: HOST=%s http_status_code=%s http_message=%s",self.host,response_status_code,response_text)
                    splunk_reachable = True
                elif response_status_code in AUTHENTICATION_ERROR_STATUS_CODES:
                    self.log.debug("RESPONSE: {0}".format(response))
                    self.log.warning("Splunk has potential authentication issues. HOST=%s",self.host)
                    self.log.error("Connectivity Check: HOST=%s http_status_code=%s http_message=%s",self.host,response_status_code,response_text)
                elif response_status_code in HEATH_WARNING_STATUS_CODES:
                    self.log.warning("Splunk has potential health issues. HOST=%s",self.host)
                    self.log.error("Connectivity Check: HOST=%s http_status_code=%s http_message=%s",self.host,response_status_code,response_text)
                else:
                    self.log.debug(response)
                    self.log.warning("Splunk is unreachable. HOST=%s",self.host)
                    self.log.error("HOST=%s HTTP status_code=%s message=%s ",self.host, response_status_code,response_text)
        except Exception as e:
            self.log.warning("Splunk is unreachable. HOST=%s",self.host)
            self.log.exception(e)

        return splunk_reachable

    async def _post_batch(self):
        """Asyncronously posts the accumulated payloads to Splunk.

            Parameters:
                none
            Returns:
                none
            Notes:
                Internal Method.
        """

        if self.post_queue.is_empty:
            self.log.debug("Batch Post: No Payloads to Post.")
            return

        self.log.debug("Batch Post: Posting to HTTP Endpoint")

        batch_size = self.post_queue.size
        for _ in range(batch_size):
            try:
                await self.work_queue.put(self.post_queue.dequeue())
            except Exception as e:
                self.log.exception(e)

        post_tasks = list()
        for _ in range(batch_size):
            try:
                post_tasks.append(asyncio.create_task(self._http_post_task(self.splunk_post_url,self.work_queue)))
            except Exception as e:
                self.log.exception(e)

        if post_tasks:
            try:
                await asyncio.gather(*post_tasks)
            except Exception as e:
                self.log.exception(e)

        return
    
    def flush(self):
        """Flushes the remaining payloads that were not auto-batch posted to Splunk.

            Parameters:
                none
            Returns:
                none
            Notes:
                Always call this method before exiting your code to send any partial batched data.
        """
    
        if not self.payload_queue.is_empty:
            self.log.debug("Final Flush: Posting %s",str(self.payload_queue.size))
            try:
                self.post_queue.enqueue([self.payload_queue.dequeue() for x in range(self.payload_queue.size)])
                if not self.post_queue.is_empty:
                    asyncio.run(self._post_batch())
            except Exception as e:
                self.log.exception(e)

        return

    def post_data(self,payload):
        """Places the JSON/text payload into a batch queue for optimal HTTP Posting to Splunk.

        Parameters:
            payload (dict): The JSON dictionary of the data payload if Payload Mode is True.
            payload (text): The plain/text of the data payload if Payload Mode is False.
        Returns:
            none
        Notes:
           Queue will auto flush as needed.
           Adding Splunk metafields like time are the responsiblity of the user.
           Example: {"time":str(round(time.time(),3))}
        """

        # Safety check to ensure payload form matches the intended operation mode
        if self._payload_mode_json and type(payload) is not dict:
            self.log.warning("Skipping Payload: set_payload_json_format:%s expected type dict received type %s",self.get_payload_json_format(),str(type(payload)))
            return
        elif not self._payload_mode_json and type(payload) is not str:
            self.log.warning("Skipping Payload: set_payload_json_format:%s expected type str received type %s",self.get_payload_json_format(),str(type(payload)))
            return
            
        # Pop empty fields if feature enabled and Payload mode JSON is True.
        if self._pop_empty_fields and self._payload_mode_json:
            payload = {k:payload.get(k) for k,v in payload.items() if v}

        # Convert payload to string of json.
        payloadString = json.dumps(payload,default=str)
        if not self._payload_mode_json and type(payload) is str:
            # Enforce payload to string.
            payloadString = str(payload)

        # Measure length of the payload string.
        payloadLength = len(payloadString)

        # Check if next payload will exceed limits, post current batch and set next batch to the new payload that exceeded the limit.
        if ((self.payload_queue.byte_size+payloadLength) > self.get_post_max_byte_size() or (self.get_post_max_byte_size() - self.payload_queue.byte_size) < payloadLength):
            # Move batch to post queue.
            self.post_queue.enqueue([self.payload_queue.dequeue() for x in range(self.payload_queue.size)])

            # If self.concurrent_post_limit batches have accumulated post flush them to Splunk.
            if self.post_queue.size >= self.get_concurrent_post_limit():
                self.log.debug("Auto Flush: Posting the Batch.")
                asyncio.run(self._post_batch())

        # Add new payload to batch accumulation.
        self.payload_queue.enqueue(payload)
