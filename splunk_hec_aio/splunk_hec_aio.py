"""splunk_hec_aio.py
    Splunk payload submission class to HTTP collector endpoint
"""

__version__ = "3.0.0.dev0"

import json
import logging
import gzip
import uuid
from dataclasses import dataclass
from typing import Optional

import asyncio
from aiohttp import ClientConnectionError, ClientSession, ClientTimeout
from aiohttp_retry import RetryClient, JitterRetry


@dataclass(frozen=True)
class HecDeliveryResult:
    """Structured outcome for one strict HEC batch request."""

    batch_index: int
    event_count: int
    http_status: int
    http_reason: str
    hec_code: Optional[int]
    hec_text: str
    invalid_event_number: Optional[int]
    accepted: bool
    retryable: bool


class HecDeliveryError(Exception):
    """Base exception for strict HEC delivery failures."""


class HecResponseError(HecDeliveryError):
    """Raised when HEC returns a response that does not accept a batch."""

    def __init__(self, result):
        self.result = result
        code = "unknown" if result.hec_code is None else result.hec_code
        super().__init__(
            "HEC rejected batch {0} ({1} event(s)): HTTP {2} {3}; "
            "HEC code {4}: {5}".format(
                result.batch_index,
                result.event_count,
                result.http_status,
                result.http_reason,
                code,
                result.hec_text,
            )
        )


class HecTransportError(HecDeliveryError):
    """Raised when a strict HEC request cannot produce a response."""

    def __init__(self, batch_index, event_count, category, retryable):
        self.batch_index = batch_index
        self.event_count = event_count
        self.category = category
        self.retryable = retryable
        super().__init__(
            "HEC {0} for batch {1} ({2} event(s))".format(
                category,
                batch_index,
                event_count,
            )
        )


class HecBatchDeliveryError(HecDeliveryError):
    """Raised after strict concurrent delivery collects one or more failures."""

    def __init__(self, results, failures):
        self.results = tuple(results)
        self.failures = tuple(failures)
        super().__init__(
            "HEC strict delivery failed for {0} batch request(s); "
            "{1} batch request(s) succeeded".format(
                len(self.failures),
                len(self.results),
            )
        )


def _is_empty_json_value(value):
    """Return whether a top-level JSON field is empty under the sender policy."""

    return value is None or (
        isinstance(value, (str, list, tuple, dict)) and not value
    )


def _new_hec_channel():
    """Return a random UUID suitable for a HEC request channel."""

    return str(uuid.uuid4())


def _strict_failure_is_retryable(failure):
    """Return whether a strict delivery failure should remain queued."""

    return (
        isinstance(failure, HecResponseError) and failure.result.retryable
    ) or (isinstance(failure, HecTransportError) and failure.retryable)


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
        check_connectivity() returns:(bool) - returns whether HEC reports healthy
        post_data(dict OR str) returns(none) - posts JSON dictionary OR plain/text to configured Splunk HTTP API Endpoint
            NOTE: payload type is controlled by set_payload_json_format listed below and should be setup at instantiation
        flush() - returns(none) - required call before exiting your code to flush any remaining batched data
        post_data_strict(dict OR str) - queues data with strict auto-flush failures enabled
        flush_strict() - returns per-batch delivery results or raises HecBatchDeliveryError
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
        set_source(string) - returns(none) - accepts string value to control if HTTP Posts place source value as a parameter. Default is None.
        get_source() - returns(string) - displays current value controlling HTTP Post parameter source value.
        set_host(string) - returns(none) - accepts string value to control if HTTP Posts place host value as a parameter. Default is None.
        get_host() - returns(string) - displays current value controlling HTTP Post parameter host value.
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
                        payload_batch = "".join(json.dumps(event) for event in payload)
                        payload_string = gzip.compress(payload_batch.encode('utf-8'))
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

    def _strict_response_result(self,response_status,response_reason,response_body,batch_index,event_count):
        """Parse one strict HEC response without retaining arbitrary body data."""

        response_data = None
        try:
            candidate = json.loads(response_body)
            if isinstance(candidate, dict):
                response_data = candidate
        except (TypeError, ValueError):
            pass

        hec_code = None
        hec_text = "HEC returned an invalid JSON response"
        invalid_event_number = None
        if response_data is not None:
            candidate_code = response_data.get("code")
            if isinstance(candidate_code, int) and not isinstance(candidate_code, bool):
                hec_code = candidate_code

            candidate_text = response_data.get("text")
            if isinstance(candidate_text, str):
                hec_text = candidate_text
            else:
                hec_text = "HEC response did not include text"

            candidate_invalid_event = response_data.get("invalid-event-number")
            if isinstance(candidate_invalid_event, int) and not isinstance(candidate_invalid_event, bool):
                invalid_event_number = candidate_invalid_event

        hec_text = " ".join(hec_text.split())
        if self.token:
            hec_text = hec_text.replace(self.token,"[REDACTED]")
        hec_text = hec_text[:256] or "HEC response text was empty"

        http_reason = " ".join(str(response_reason or "").split())
        if self.token:
            http_reason = http_reason.replace(self.token,"[REDACTED]")
        http_reason = http_reason[:80]

        accepted_codes = {0,24,25}
        accepted = 200 <= response_status < 300 and hec_code in accepted_codes
        retryable_codes = {8,9,18,19,20,23,26,27}
        retryable = (
            not accepted
            and (
                response_status in self.retry_http_status_codes
                or hec_code in retryable_codes
            )
        )

        return HecDeliveryResult(
            batch_index=batch_index,
            event_count=event_count,
            http_status=response_status,
            http_reason=http_reason,
            hec_code=hec_code,
            hec_text=hec_text,
            invalid_event_number=invalid_event_number,
            accepted=accepted,
            retryable=retryable,
        )

    async def _http_post_strict_task(self,url,payload,batch_index):
        """Post one batch and return a structured result or raise a strict error."""

        retry_options = JitterRetry(
            attempts=self.http_retries,
            statuses=self.retry_http_status_codes,
            exceptions={asyncio.TimeoutError,ClientConnectionError},
        )
        timeout = ClientTimeout(total=30.0,connect=10.0,sock_read=30.0)
        event_count = len(payload)

        if self._payload_mode_json:
            payload_batch = "".join(json.dumps(event) for event in payload)
        else:
            payload_batch = "".join(payload)
        payload_string = gzip.compress(payload_batch.encode("utf-8"))

        async with ClientSession(timeout=timeout) as session:
            retry_client = RetryClient(session,raise_for_status=False)
            try:
                async with retry_client.post(
                    url,
                    verify_ssl=self.get_verify_tls(),
                    headers=self.splunk_headers,
                    retry_options=retry_options,
                    params=self.splunk_params,
                    data=payload_string,
                ) as response:
                    response_body = await response.text()

                result = self._strict_response_result(
                    response.status,
                    response.reason,
                    response_body,
                    batch_index,
                    event_count,
                )
                if not result.accepted:
                    raise HecResponseError(result)
                return result
            except asyncio.CancelledError:
                raise
            except HecDeliveryError:
                raise
            except asyncio.TimeoutError as error:
                raise HecTransportError(
                    batch_index,
                    event_count,
                    "request timed out",
                    True,
                ) from error
            except ClientConnectionError as error:
                raise HecTransportError(
                    batch_index,
                    event_count,
                    "connection failed",
                    True,
                ) from error
            except Exception as error:
                raise HecTransportError(
                    batch_index,
                    event_count,
                    "transport failed",
                    False,
                ) from error
            finally:
                await retry_client.close()

    async def _post_batch_strict(self):
        """Post all completed batches and report every strict outcome."""

        if self.post_queue.is_empty:
            return tuple()

        batches = [self.post_queue.dequeue() for _ in range(self.post_queue.size)]
        tasks = [
            asyncio.create_task(
                self._http_post_strict_task(
                    self.splunk_post_url,
                    batch,
                    batch_index,
                )
            )
            for batch_index,batch in enumerate(batches)
        ]
        try:
            outcomes = await asyncio.gather(*tasks,return_exceptions=True)
        except asyncio.CancelledError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            cancelled_outcomes = await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )
            for batch_index,outcome in enumerate(cancelled_outcomes):
                if isinstance(outcome, HecDeliveryResult):
                    continue
                if isinstance(outcome, HecDeliveryError) and not (
                    _strict_failure_is_retryable(outcome)
                ):
                    continue
                self.post_queue.enqueue(batches[batch_index])
            raise
        results = []
        failures = []
        retryable_batches = []
        propagated_outcome = None

        for batch_index,outcome in enumerate(outcomes):
            if isinstance(outcome, asyncio.CancelledError):
                retryable_batches.append(batches[batch_index])
                if propagated_outcome is None:
                    propagated_outcome = outcome
            elif isinstance(outcome, HecDeliveryResult):
                results.append(outcome)
            elif isinstance(outcome, HecDeliveryError):
                failures.append(outcome)
                if _strict_failure_is_retryable(outcome):
                    retryable_batches.append(batches[batch_index])
            elif isinstance(outcome, Exception):
                failures.append(
                    HecTransportError(
                        batch_index,
                        len(batches[batch_index]),
                        "transport failed",
                        False,
                    )
                )
            elif isinstance(outcome, BaseException):
                retryable_batches.append(batches[batch_index])
                if propagated_outcome is None:
                    propagated_outcome = outcome

        for batch in retryable_batches:
            self.post_queue.enqueue(batch)

        if propagated_outcome is not None:
            raise propagated_outcome
        if failures:
            raise HecBatchDeliveryError(results,failures)
        return tuple(results)
    
     # ASync Web Get Method Specific for Checking HEC Service Health
    async def _http_health_task(self,url):

       # Use JitteryRetry which is exponential with some randomness.
        retry_options = JitterRetry(max_timeout=0.3,attempts=1.0,statuses=self.retry_http_status_codes)

        health_headers = {"User-Agent": "Splunk-hec-sender/3.0 (Python)"}

        async with ClientSession() as session:
            retry_client = RetryClient(session,self.http_raise_for_status)
            try:
                async with retry_client.get(url,verify_ssl=self.get_verify_tls(),headers=health_headers,retry_options=retry_options) as response:
                    await response.text()
                    return(response.status,response.reason)
            except Exception as e:
                self.log.debug(e)
            finally:
                await retry_client.close()
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

        if not isinstance(host, str) or not host.strip():
            raise(ValueError("HOST must be a non-empty string."))
        if not isinstance(token, str) or not token.strip():
            raise(ValueError("HEC Token must be a non-empty string."))

        self.host = host
        self.token = token

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
        self._source = None
        self._host = None

        # Set HTTP Controls
        self.http_raise_for_status = False
        self.http_retries = 3
        self.set_verify_tls()
        self._strict_delivery = False

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

            Notes:
                Reachability is not checked while rendering. Call
                check_connectivity() explicitly when a live result is needed.
        """
        return "Splunk: HOST={0} HTTPS={1} Reachable={2} PopEmptyFields={3} PayloadModeJSON={4} ConcurrentPostLimit={5}".format(self.host,self.get_https(),"NotChecked",self._pop_empty_fields,self._payload_mode_json,self.get_concurrent_post_limit())
  
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
        """Property returns the documented HEC service health URL.

            Returns:
                string: formed URL for the HEC health endpoint.
        """

        if self.get_https():
            http_header = "https"
        else:
            http_header = "http"

        url = "%s://%s:%d/services/collector/health" % (http_header,self.host,self._port)

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
        headers["X-Splunk-Request-Channel"] = _new_hec_channel()
        return headers

    @property
    def splunk_params(self):
        """Property returns the needed Splunk HTTP Parameters."""

        params = dict()
        if not self._payload_mode_json:
            params["channel"] = _new_hec_channel()
        json_format = self.get_payload_json_format()
        if self._index and not json_format:
            params["index"] = self._index
        if self._sourcetype and not json_format:
            params['sourcetype'] = self._sourcetype
        if self._source and not json_format:
            params['source'] = self._source
        if self._host and not json_format:
            params['host'] = self._host

        if not params:
            return None
        
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

        This mode only works for payload mode (True) application/json. It removes
        top-level None values and empty strings, lists, tuples, and dictionaries.
        Numeric zero and False are preserved. It is ignored for payload mode
        (False) text/plain.

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
                value (int): Sets the maximum uncompressed UTF-8 request-body
                    size per HTTP post.
        Note:
                Thanks to Brett Adams of the SplunkTrust for default limit input to support older Splunk versions.
                The value is recommended to be set to a size that is approximately 256 * the max  of a data payload length.
                This better fit value forces more spread across the AIO concurrent posts for better performance.
                A single payload larger than this value is queued alone because
                the sender does not split individual events.
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
        """Get the maximum uncompressed UTF-8 request-body bytes per batch.

            Default value is 512000.

            Parameters:
                none
            Returns:
                int: maximum byte size per HTTP post.
                
        """

        return self._max_byte_size

    def _payload_wire_size(self,payload):
        """Return this payload's uncompressed UTF-8 request-body size."""

        if self._payload_mode_json:
            payload_string = json.dumps(payload,default=str)
        else:
            payload_string = str(payload)
        return len(payload_string.encode("utf-8"))
       
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
        self.log.info("Splunk Default Index Set: index={0}".format(value))

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
        """Set HEC Sourcetype Value to use in Post URL parameters (string).

        This sets the optional URL parameter sourcetype=... Default is None.
        Some users may want to specify the sourcetype in the URL for Post instead of in the event JSON payload.
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
        self.log.info("Splunk Default Sourcetype Set: sourcetype={0}".format(value))

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

    def set_source(self,value=None):
        """Set HEC Source Value to use in Post URL parameters (string).

        This sets the optional URL parameter source=... Default is None.
        Some users may want to specify the source in the URL for Post instead of in the event JSON payload.
        This is useful for raw data mode.

        Parameters:
                value (string): Expected format example `mysource`
        Returns:
                none

        """

        if not isinstance(value, str):
            self.log.error("Invalid Value: {0}".format(value))
            return
   
        self._source = value
        self.log.info("Splunk Default Source Set: source={0}".format(value))

    def get_source(self):
        """Get the HEC default source optionally used in Post URL (string).
        
            Default value is None
            Value: "mysource"

            Parameters:
                none
            Returns:
                string: value of HEC Default Source Token in URL
                
        """

        return self._source
    

    def set_host(self,value=None):
        """Set HEC Host Value to use in Post URL parameters (string).

        This sets the optional URL parameter host=... Default is None.
        Some users may want to specify the host in the URL for Post instead of in the event JSON payload.
        This is useful for raw data mode.

        Parameters:
                value (string): Expected format example `myhost`
        Returns:
                none

        """

        if not isinstance(value, str):
            self.log.error("Invalid Value: {0}".format(value))
            return
   
        self._host = value
        self.log.info("Splunk Default Host Set: host={0}".format(value))

    def get_host(self):
        """Get the HEC default host optionally used in Post URL (string).
        
            Default value is None
            Value: "myhost"

            Parameters:
                none
            Returns:
                string: value of HEC Default Host Token in URL
                
        """

        return self._host
    
    def check_connectivity(self):
        """Return whether the HEC service reports that it can accept input.

        Reference:
            https://help.splunk.com/en/splunk-enterprise/rest-api-reference/9.4/input-endpoints/input-endpoint-descriptions

        Notes:
            Uses the unauthenticated GET /services/collector/health endpoint.
            This checks service and queue health only. It does not validate the
            configured token or prove that an event was accepted or indexed.

        Returns:
            bool: True only when the health endpoint returns HTTP 200.
        """

        is_available = asyncio.run(self._check_connectivity())

        return is_available

    async def _check_connectivity(self):
        """Private ASYNC function to check documented HEC service health.

        Returns:
            bool: True only when HEC reports healthy.
        Notes:
            Internal Method.
        """

        self.log.info("Checking Splunk HEC health. HOST=%s",self.host)

        try:
            response = await self._http_health_task(self.splunk_health_url)
            if not response:
                self.log.warning("Splunk HEC health check failed. HOST=%s",self.host)
                return False

            response_status_code, response_reason = response
            if response_status_code == 200:
                self.log.info("Splunk HEC is healthy. HOST=%s",self.host)
                return True
            if response_status_code in (429,503):
                self.log.warning("Splunk HEC is unhealthy. HOST=%s http_status_code=%s http_message=%s",self.host,response_status_code,response_reason)
            else:
                self.log.warning("Splunk HEC health request was not successful. HOST=%s http_status_code=%s http_message=%s",self.host,response_status_code,response_reason)
        except Exception as e:
            self.log.warning("Splunk HEC health check failed. HOST=%s",self.host)
            self.log.exception(e)

        return False

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

    def flush_strict(self):
        """Flush queued payloads with structured results and propagated failures.

        Returns:
            tuple: One HecDeliveryResult for every accepted batch request.
        Raises:
            HecBatchDeliveryError: One or more batch requests failed.

        Notes:
            Use post_data_strict() consistently for the same sender so any
            automatic batch flush also uses strict delivery. Each HTTP attempt
            has explicit 30-second total/read and 10-second connect timeouts.
        """

        if not self.payload_queue.is_empty:
            self.post_queue.enqueue(
                [
                    self.payload_queue.dequeue()
                    for _ in range(self.payload_queue.size)
                ]
            )
        if self.post_queue.is_empty:
            return tuple()
        return asyncio.run(self._post_batch_strict())

    def post_data_strict(self,payload):
        """Queue one payload and propagate failures from any automatic flush.

        Returns:
            tuple: Results from an automatic flush, or an empty tuple when no
                HTTP request was needed yet.
        Raises:
            HecBatchDeliveryError: An automatic strict batch flush failed.

        Notes:
            Finish a strict sequence with flush_strict(). Do not mix strict and
            legacy post methods on the same queued sequence.
        """

        if self._payload_mode_json and type(payload) is not dict:
            raise TypeError("Strict JSON payloads must be dictionaries.")
        if not self._payload_mode_json and type(payload) is not str:
            raise TypeError("Strict raw payloads must be strings.")

        previous_strict_delivery = self._strict_delivery
        self._strict_delivery = True
        try:
            results = self.post_data(payload)
        finally:
            self._strict_delivery = previous_strict_delivery
        if results is None:
            return tuple()
        return results

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

        strict_results = tuple()
        payload_queued = False

        # Safety check to ensure payload form matches the intended operation mode
        if self._payload_mode_json and type(payload) is not dict:
            self.log.warning("Skipping Payload: set_payload_json_format:%s expected type dict received type %s",self.get_payload_json_format(),str(type(payload)))
            return
        elif not self._payload_mode_json and type(payload) is not str:
            self.log.warning("Skipping Payload: set_payload_json_format:%s expected type str received type %s",self.get_payload_json_format(),str(type(payload)))
            return
            
        # Work with our own top-level dictionary so configured metadata never
        # mutates a caller-owned payload.
        if self._payload_mode_json:
            payload = payload.copy()
            if self._pop_empty_fields:
                payload = {k:v for k,v in payload.items() if not _is_empty_json_value(v)}
        json_format = self.get_payload_json_format()

        if json_format and self._host:
            payload.update({"host":self._host})
        if json_format and self._source:
            payload.update({"source":self._source})
        if json_format and self._sourcetype:
            payload.update({"sourcetype":self._sourcetype})
        if json_format and self._index:
            payload.update({"index":self._index})

        # Measure the exact uncompressed UTF-8 bytes used by the request body.
        payload_length = self._payload_wire_size(payload)
        queued_length = sum(
            self._payload_wire_size(queued_payload)
            for queued_payload in self.payload_queue.elements
        )

        # Move only a non-empty completed batch when the next payload would
        # exceed the limit. An individually oversized event remains intact and
        # is sent alone because HEC events cannot be split safely.
        if (
            not self.payload_queue.is_empty
            and queued_length + payload_length > self.get_post_max_byte_size()
        ):
            # Move batch to post queue.
            self.post_queue.enqueue([self.payload_queue.dequeue() for x in range(self.payload_queue.size)])

            # If self.concurrent_post_limit batches have accumulated post flush them to Splunk.
            if self.post_queue.size >= self.get_concurrent_post_limit():
                self.log.debug("Auto Flush: Posting the Batch.")
                if self._strict_delivery:
                    # Retain the payload that triggered this flush before
                    # strict delivery can propagate a previous batch failure.
                    self.payload_queue.enqueue(payload)
                    payload_queued = True
                    strict_results = asyncio.run(self._post_batch_strict())
                else:
                    asyncio.run(self._post_batch())

        # Add new payload to batch accumulation.
        if not payload_queued:
            self.payload_queue.enqueue(payload)

        if self._strict_delivery:
            return strict_results
