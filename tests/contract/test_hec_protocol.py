import asyncio
import gzip
import json
import logging
import unittest
import uuid
from unittest.mock import AsyncMock, patch, sentinel

from splunk_hec_aio.splunk_hec_aio import SplunkHecAio


class _RecordingResponse:
    def __init__(self, status=200, reason="OK", body='{"text":"Success","code":0}'):
        self.status = status
        self.reason = reason
        self.body = body
        self.text_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def text(self):
        self.text_calls += 1
        return self.body


class _RecordingClientSession:
    def __init__(self):
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.exited = True
        return False


class _RecordingRetryClient:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.closed = False

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.response

    async def close(self):
        self.closed = True


class TestHecProtocol(unittest.TestCase):
    def setUp(self):
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)
        self.addCleanup(self._close_event_loop)

        self.sender = SplunkHecAio("splunk.example", "test-token")
        self.sender.log.setLevel(logging.CRITICAL)
        self.response = _RecordingResponse()
        self.session = _RecordingClientSession()
        self.retry_client = _RecordingRetryClient(self.response)

        patchers = (
            patch(
                "splunk_hec_aio.splunk_hec_aio.ClientSession",
                return_value=self.session,
            ),
            patch(
                "splunk_hec_aio.splunk_hec_aio.RetryClient",
                return_value=self.retry_client,
            ),
            patch(
                "splunk_hec_aio.splunk_hec_aio.JitterRetry",
                return_value=sentinel.retry_options,
            ),
        )
        self.client_session = patchers[0].start()
        self.retry_client_factory = patchers[1].start()
        self.jitter_retry = patchers[2].start()
        for patcher in patchers:
            self.addCleanup(patcher.stop)

    def _close_event_loop(self):
        asyncio.set_event_loop(None)
        self.event_loop.close()

    def _post_batch_through_transport(self, payload_batch):
        async def post():
            work_queue = asyncio.Queue()
            await work_queue.put(payload_batch)
            return await self.sender._http_post_task(
                self.sender.splunk_post_url,
                work_queue,
            )

        return asyncio.run(post())

    def _only_request(self):
        self.assertEqual(len(self.retry_client.requests), 1)
        return self.retry_client.requests[0]

    def test_json_transport_records_exact_v2_gzip_body_and_metadata(self):
        event = {
            "time": "1.25",
            "host": "event-host",
            "source": "protocol-test",
            "sourcetype": "example:json",
            "index": "main",
            "fields": {"region": "us-central"},
            "event": {"message": "hello", "count": 2},
        }
        channel = uuid.UUID("00000000-0000-0000-0000-000000000010")

        with patch(
            "splunk_hec_aio.splunk_hec_aio.uuid.uuid1",
            return_value=channel,
        ):
            result = self._post_batch_through_transport([event])

        url, request = self._only_request()
        decompressed = gzip.decompress(request["data"]).decode("utf-8")

        self.assertEqual(result, (200, "OK"))
        self.assertEqual(
            url,
            "https://splunk.example:8088/services/collector/event",
        )
        self.assertEqual(decompressed, json.dumps([event]))
        self.assertEqual(json.loads(decompressed), [event])
        self.assertEqual(request["verify_ssl"], True)
        self.assertIsNone(request["params"])
        self.assertEqual(
            request["headers"],
            {
                "Authorization": "Splunk test-token",
                "Content-Encoding": "gzip",
                "Content-Type": "application/json",
                "User-Agent": "Splunk-hec-sender/1.0 (Python)",
                "X-Splunk-Request-Channel": str(channel),
            },
        )
        self.assertIs(request["retry_options"], sentinel.retry_options)
        self.assertEqual(self.response.text_calls, 1)
        self.assertTrue(self.session.entered)
        self.assertTrue(self.session.exited)
        self.assertTrue(self.retry_client.closed)

    def test_json_endpoint_records_released_array_framing_gap(self):
        # Issue #17 owns replacing this released JSON-array framing.
        events = [{"event": "first"}, {"event": "second"}]

        self._post_batch_through_transport(events)

        _, request = self._only_request()
        decompressed = gzip.decompress(request["data"]).decode("utf-8")
        intended_framing = "".join(json.dumps(event) for event in events)
        self.assertNotEqual(decompressed, intended_framing)
        self.assertEqual(decompressed, json.dumps(events))

    def test_json_payload_shapes_and_unicode_round_trip_deterministically(self):
        events = [
            {"event": "snowman ☃ and café"},
            {
                "event": {
                    "zero": 0,
                    "false": False,
                    "empty": "",
                    "empty_list": [],
                    "empty_dict": {},
                    "none": None,
                }
            },
            {"event": ["nested", {"message": "日本語"}]},
        ]

        self._post_batch_through_transport(events)

        _, request = self._only_request()
        decompressed = gzip.decompress(request["data"]).decode("utf-8")
        self.assertEqual(decompressed, json.dumps(events))
        self.assertEqual(json.loads(decompressed), events)

    def test_raw_transport_uses_exact_concatenated_body_and_url_parameters(self):
        self.sender.set_payload_json_format(False)
        self.sender.set_https(False)
        self.sender.set_index("main")
        self.sender.set_sourcetype("example:raw")
        self.sender.set_source("protocol-test")
        self.sender.set_host("source-host")
        channel = uuid.UUID("00000000-0000-0000-0000-000000000011")
        payloads = ["first line\n", "second line\n"]

        with patch(
            "splunk_hec_aio.splunk_hec_aio.uuid.uuid1",
            return_value=channel,
        ):
            result = self._post_batch_through_transport(payloads)

        url, request = self._only_request()

        self.assertEqual(result, (200, "OK"))
        self.assertEqual(
            url,
            "http://splunk.example:8088/services/collector/raw",
        )
        self.assertEqual(
            gzip.decompress(request["data"]).decode("utf-8"),
            "".join(payloads),
        )
        self.assertEqual(request["headers"]["Content-Type"], "text/plain")
        self.assertEqual(
            request["params"],
            {
                "channel": str(channel),
                "index": "main",
                "sourcetype": "example:raw",
                "source": "protocol-test",
                "host": "source-host",
            },
        )

    def test_json_metadata_setters_record_released_caller_mutation(self):
        # Issue #17 owns any change to this released mutation behavior.
        self.sender.set_pop_empty_fields(False)
        self.sender.set_index("main")
        self.sender.set_sourcetype("example:json")
        self.sender.set_source("protocol-test")
        self.sender.set_host("source-host")
        payload = {"event": {"message": "hello"}, "time": "1.25"}

        self.sender.post_data(payload)

        self.assertIs(self.sender.payload_queue.first, payload)
        self.assertEqual(
            payload,
            {
                "event": {"message": "hello"},
                "time": "1.25",
                "index": "main",
                "sourcetype": "example:json",
                "source": "protocol-test",
                "host": "source-host",
            },
        )

    def test_retry_policy_is_passed_to_the_transport(self):
        self._post_batch_through_transport([{"event": "retry policy"}])

        self.jitter_retry.assert_called_once_with(
            attempts=3,
            statuses={408, 429, 500, 502, 503, 504},
        )
        self.retry_client_factory.assert_called_once_with(self.session, False)

    def test_http_400_raises_from_the_low_level_transport(self):
        self.response.status = 400
        self.response.reason = "Bad Request"
        self.response.body = '{"text":"Invalid data format","code":6}'

        with self.assertRaises(ValueError):
            self._post_batch_through_transport([{"event": "rejected"}])

        self.assertEqual(self.response.text_calls, 1)
        self.assertTrue(self.session.exited)

    def test_terminal_http_error_records_released_non_raising_behavior(self):
        # Issue #10 owns changing this through an additive result/exception API.
        self.response.status = 401
        self.response.reason = "Unauthorized"
        self.response.body = '{"text":"Token is required","code":2}'

        result = self._post_batch_through_transport([{"event": "rejected"}])

        self.assertEqual(result, (401, "Unauthorized"))
        self.assertEqual(self.response.text_calls, 1)

    def test_timeout_records_released_retry_client_cleanup_gap(self):
        # Issue #12 owns ensuring client cleanup on every exceptional path.
        with patch.object(
            self.retry_client,
            "post",
            side_effect=asyncio.TimeoutError,
        ):
            with self.assertRaises(asyncio.TimeoutError):
                self._post_batch_through_transport([{"event": "timeout"}])

        self.assertTrue(self.session.exited)
        self.assertFalse(self.retry_client.closed)

    def test_ascii_batch_boundaries_preserve_each_event_once(self):
        self.sender.set_pop_empty_fields(False)
        self.sender.set_post_max_byte_size(4000)
        self.sender.set_concurrent_post_limit(2)
        events = [
            {"event": "a" * 2200},
            {"event": "b" * 2200},
            {"event": "c" * 2200},
        ]

        with patch.object(
            self.sender,
            "_post_batch",
            new=AsyncMock(return_value=None),
        ) as post_batch:
            for event in events:
                self.sender.post_data(event)

        self.assertEqual(post_batch.await_count, 1)
        self.assertEqual(self.sender.post_queue.elements, [[events[0]], [events[1]]])
        self.assertEqual(self.sender.payload_queue.elements, [events[2]])

    def test_raw_batch_boundaries_record_released_utf8_accounting_gap(self):
        # Issue #17 owns correcting this character/JSON-based accounting.
        self.sender.set_payload_json_format(False)
        self.sender.set_post_max_byte_size(4000)
        payloads = ["é" * 900, "é" * 900]
        self.assertLessEqual(
            sum(len(payload.encode("utf-8")) for payload in payloads),
            self.sender.get_post_max_byte_size(),
        )

        for payload in payloads:
            self.sender.post_data(payload)

        self.assertEqual(self.sender.post_queue.elements, [[payloads[0]]])
        self.assertEqual(self.sender.payload_queue.elements, [payloads[1]])

    def test_concurrent_batch_dispatch_does_not_lose_or_duplicate_batches(self):
        batches = [
            [{"event": "first"}],
            [{"event": "second"}],
            [{"event": "third"}],
        ]
        for batch in batches:
            self.sender.post_queue.enqueue(batch)
        seen = []

        async def capture_one_batch(url, work_queue):
            self.assertEqual(url, self.sender.splunk_post_url)
            seen.append(await work_queue.get())
            return 200, "OK"

        with patch.object(
            self.sender,
            "_http_post_task",
            new=AsyncMock(side_effect=capture_one_batch),
        ) as post_task:
            asyncio.run(self.sender._post_batch())

        self.assertEqual(post_task.await_count, len(batches))
        self.assertCountEqual(seen, batches)
        self.assertTrue(self.sender.post_queue.is_empty)

    def test_cancellation_propagates_from_concurrent_batch_dispatch(self):
        self.sender.post_queue.enqueue([{"event": "cancelled"}])

        with patch.object(
            self.sender,
            "_http_post_task",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(self.sender._post_batch())


if __name__ == "__main__":
    unittest.main()
