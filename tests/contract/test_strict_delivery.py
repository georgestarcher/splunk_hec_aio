import asyncio
import gzip
import json
import logging
import unittest
from unittest.mock import AsyncMock, patch, sentinel

from aiohttp import ClientConnectionError

from splunk_hec_aio.splunk_hec_aio import (
    HecBatchDeliveryError,
    HecDeliveryResult,
    HecResponseError,
    HecTransportError,
    SplunkHecAio,
)


class _Response:
    def __init__(self, status=200, reason="OK", body=None):
        self.status = status
        self.reason = reason
        self.body = body or '{"text":"Success","code":0}'
        self.text_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False

    async def text(self):
        self.text_calls += 1
        return self.body


class _Session:
    def __init__(self):
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.exited = True
        return False


class _RetryClient:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.closed = False

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.response

    async def close(self):
        self.closed = True


def result(batch_index, event_count, accepted=True, retryable=False):
    return HecDeliveryResult(
        batch_index=batch_index,
        event_count=event_count,
        http_status=200 if accepted else 400,
        http_reason="OK" if accepted else "Bad Request",
        hec_code=0 if accepted else 6,
        hec_text="Success" if accepted else "Invalid data format",
        invalid_event_number=None if accepted else 0,
        accepted=accepted,
        retryable=retryable,
    )


class TestStrictDelivery(unittest.TestCase):
    def setUp(self):
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)
        self.addCleanup(self._close_event_loop)

        self.sender = SplunkHecAio("splunk.example", "test-token")
        self.sender.log.setLevel(logging.CRITICAL)
        self.response = _Response()
        self.session = _Session()
        self.retry_client = _RetryClient(self.response)

        self.session_factory_patcher = patch(
            "splunk_hec_aio.splunk_hec_aio.ClientSession",
            return_value=self.session,
        )
        self.retry_client_factory_patcher = patch(
            "splunk_hec_aio.splunk_hec_aio.RetryClient",
            return_value=self.retry_client,
        )
        self.jitter_retry_patcher = patch(
            "splunk_hec_aio.splunk_hec_aio.JitterRetry",
            return_value=sentinel.retry_options,
        )
        self.session_factory = self.session_factory_patcher.start()
        self.retry_client_factory = self.retry_client_factory_patcher.start()
        self.jitter_retry = self.jitter_retry_patcher.start()
        self.addCleanup(self.session_factory_patcher.stop)
        self.addCleanup(self.retry_client_factory_patcher.stop)
        self.addCleanup(self.jitter_retry_patcher.stop)

    def _close_event_loop(self):
        asyncio.set_event_loop(None)
        if not self.event_loop.is_closed():
            self.event_loop.close()

    def strict_post(self, payload=None, batch_index=0):
        payload = payload or [{"event": "strict"}]
        return asyncio.run(
            self.sender._http_post_strict_task(
                self.sender.splunk_post_url,
                payload,
                batch_index,
            )
        )

    def test_strict_success_returns_structured_result_with_explicit_timeouts(self):
        events = [{"event": "first"}, {"event": "second"}]

        delivery = self.strict_post(events, batch_index=3)

        self.assertEqual(
            delivery,
            HecDeliveryResult(
                batch_index=3,
                event_count=2,
                http_status=200,
                http_reason="OK",
                hec_code=0,
                hec_text="Success",
                invalid_event_number=None,
                accepted=True,
                retryable=False,
            ),
        )
        timeout = self.session_factory.call_args.kwargs["timeout"]
        self.assertEqual(timeout.total, 30.0)
        self.assertEqual(timeout.connect, 10.0)
        self.assertEqual(timeout.sock_read, 30.0)
        self.retry_client_factory.assert_called_once_with(
            self.session,
            raise_for_status=False,
        )
        self.jitter_retry.assert_called_once_with(
            attempts=3,
            statuses={408, 429, 500, 502, 503, 504},
            exceptions={asyncio.TimeoutError, ClientConnectionError},
        )
        self.assertTrue(self.retry_client.closed)
        self.assertEqual(self.response.text_calls, 1)

        _, request = self.retry_client.requests[0]
        body = gzip.decompress(request["data"]).decode("utf-8")
        self.assertEqual(body, "".join(json.dumps(event) for event in events))

    def test_strict_raw_request_preserves_raw_framing_and_parameters(self):
        self.sender.set_payload_json_format(False)
        self.sender.set_index("main")
        self.sender.set_sourcetype("example:raw")
        payloads = ["first\n", "second\n"]

        delivery = self.strict_post(payloads)

        self.assertTrue(delivery.accepted)
        _, request = self.retry_client.requests[0]
        self.assertEqual(
            gzip.decompress(request["data"]).decode("utf-8"),
            "".join(payloads),
        )
        self.assertEqual(request["params"]["index"], "main")
        self.assertEqual(request["params"]["sourcetype"], "example:raw")
        self.assertIn("channel", request["params"])

    def test_documented_http_failures_surface_hec_code_and_retryability(self):
        cases = (
            (400, 6, "Invalid data format", False),
            (401, 2, "Token is required", False),
            (403, 4, "Invalid token", False),
            (404, 99, "Not found", False),
            (413, 99, "Payload too large", False),
            (429, 26, "HEC queue is at capacity", True),
            (500, 8, "Internal server error", True),
            (503, 9, "Server is busy", True),
        )

        for status, code, text, retryable in cases:
            with self.subTest(status=status):
                self.response.status = status
                self.response.reason = "Rejected"
                self.response.body = json.dumps(
                    {
                        "text": text,
                        "code": code,
                        "invalid-event-number": 1,
                    }
                )

                with self.assertRaises(HecResponseError) as raised:
                    self.strict_post([{"event": "one"}, {"event": "two"}])

                failure = raised.exception.result
                self.assertEqual(failure.http_status, status)
                self.assertEqual(failure.hec_code, code)
                self.assertEqual(failure.hec_text, text)
                self.assertEqual(failure.invalid_event_number, 1)
                self.assertEqual(failure.event_count, 2)
                self.assertEqual(failure.retryable, retryable)
                self.assertFalse(failure.accepted)

    def test_http_200_with_failure_code_is_not_apparent_success(self):
        self.response.body = '{"text":"Invalid data format","code":6}'

        with self.assertRaises(HecResponseError) as raised:
            self.strict_post()

        self.assertEqual(raised.exception.result.http_status, 200)
        self.assertEqual(raised.exception.result.hec_code, 6)
        self.assertFalse(raised.exception.result.accepted)

    def test_capacity_warning_codes_are_accepted_without_retry(self):
        for code in (24, 25):
            with self.subTest(code=code):
                self.response.body = json.dumps(
                    {"text": "HEC is approaching capacity", "code": code}
                )
                delivery = self.strict_post()
                self.assertTrue(delivery.accepted)
                self.assertFalse(delivery.retryable)

    def test_response_context_is_bounded_and_token_is_redacted(self):
        self.response.status = 400
        self.response.reason = "Bad Request test-token " + ("r" * 100)
        self.response.body = json.dumps(
            {
                "text": "token=test-token " + ("x" * 400),
                "code": 6,
            }
        )

        with self.assertRaises(HecResponseError) as raised:
            self.strict_post()

        failure = raised.exception.result
        self.assertNotIn("test-token", failure.hec_text)
        self.assertNotIn("test-token", failure.http_reason)
        self.assertNotIn("test-token", str(raised.exception))
        self.assertIn("[REDACTED]", failure.hec_text)
        self.assertLessEqual(len(failure.hec_text), 256)
        self.assertLessEqual(len(failure.http_reason), 80)

    def test_non_json_response_does_not_expose_arbitrary_body(self):
        self.response.status = 502
        self.response.reason = "Bad Gateway"
        self.response.body = "proxy body includes test-token and event contents"

        with self.assertRaises(HecResponseError) as raised:
            self.strict_post()

        failure = raised.exception.result
        self.assertEqual(failure.hec_text, "HEC returned an invalid JSON response")
        self.assertNotIn("test-token", str(raised.exception))
        self.assertNotIn("event contents", str(raised.exception))

    def test_timeout_is_deterministic_retryable_and_closes_client(self):
        with patch.object(
            self.retry_client,
            "post",
            side_effect=asyncio.TimeoutError,
        ):
            with self.assertRaises(HecTransportError) as raised:
                self.strict_post(batch_index=2)

        self.assertEqual(raised.exception.batch_index, 2)
        self.assertEqual(raised.exception.category, "request timed out")
        self.assertTrue(raised.exception.retryable)
        self.assertTrue(self.retry_client.closed)
        self.assertTrue(self.session.exited)

    def test_connection_failure_is_retryable_and_closes_client(self):
        with patch.object(
            self.retry_client,
            "post",
            side_effect=ClientConnectionError("connection refused"),
        ):
            with self.assertRaises(HecTransportError) as raised:
                self.strict_post(batch_index=4)

        self.assertEqual(raised.exception.batch_index, 4)
        self.assertEqual(raised.exception.category, "connection failed")
        self.assertTrue(raised.exception.retryable)
        self.assertNotIn("connection refused", str(raised.exception))
        self.assertTrue(self.retry_client.closed)

    def test_partial_batch_failure_reports_positions_without_payloads(self):
        batches = [
            [{"event": "first-secret"}],
            [{"event": "second-secret"}, {"event": "third-secret"}],
            [{"event": "fourth-secret"}],
        ]
        for batch in batches:
            self.sender.post_queue.enqueue(batch)

        async def deliver(url, batch, batch_index):
            self.assertEqual(url, self.sender.splunk_post_url)
            if batch_index == 1:
                raise HecResponseError(result(1, len(batch), accepted=False))
            return result(batch_index, len(batch))

        with patch.object(
            self.sender,
            "_http_post_strict_task",
            new=AsyncMock(side_effect=deliver),
        ):
            with self.assertRaises(HecBatchDeliveryError) as raised:
                asyncio.run(self.sender._post_batch_strict())

        error = raised.exception
        self.assertEqual([item.batch_index for item in error.results], [0, 2])
        self.assertEqual(len(error.failures), 1)
        failure = error.failures[0]
        self.assertIsInstance(failure, HecResponseError)
        self.assertEqual(failure.result.batch_index, 1)
        self.assertEqual(failure.result.event_count, 2)
        self.assertNotIn("secret", str(error))
        self.assertTrue(self.sender.post_queue.is_empty)

    def test_retryable_partial_failures_requeue_only_failed_batches_in_order(self):
        batches = [
            [{"event": "first-retry"}],
            [{"event": "second-success"}],
            [{"event": "third-retry"}],
        ]
        for batch in batches:
            self.sender.post_queue.enqueue(batch)

        async def deliver(url, batch, batch_index):
            self.assertEqual(url, self.sender.splunk_post_url)
            if batch_index == 0:
                raise HecTransportError(batch_index, len(batch), "timeout", True)
            if batch_index == 2:
                raise HecResponseError(
                    result(
                        batch_index,
                        len(batch),
                        accepted=False,
                        retryable=True,
                    )
                )
            return result(batch_index, len(batch))

        with patch.object(
            self.sender,
            "_http_post_strict_task",
            new=AsyncMock(side_effect=deliver),
        ):
            with self.assertRaises(HecBatchDeliveryError) as raised:
                asyncio.run(self.sender._post_batch_strict())

        self.assertEqual(
            [item.batch_index for item in raised.exception.results],
            [1],
        )
        self.assertEqual(len(raised.exception.failures), 2)
        self.assertEqual(self.sender.post_queue.elements, [batches[0], batches[2]])

    def test_replayed_retryable_batches_respect_concurrency_limit(self):
        self.sender.set_concurrent_post_limit(1)
        batches = [
            [{"event": "first-retry"}],
            [{"event": "second-retry"}],
        ]
        for batch in batches:
            self.sender.post_queue.enqueue(batch)

        async def fail_retryably(url, batch, batch_index):
            self.assertEqual(url, self.sender.splunk_post_url)
            raise HecTransportError(batch_index, len(batch), "timeout", True)

        with patch.object(
            self.sender,
            "_http_post_strict_task",
            new=AsyncMock(side_effect=fail_retryably),
        ):
            with self.assertRaises(HecBatchDeliveryError):
                asyncio.run(self.sender._post_batch_strict())

        self.assertEqual(self.sender.post_queue.elements, batches)
        active = 0
        max_active = 0

        async def deliver(url, batch, batch_index):
            nonlocal active, max_active
            self.assertEqual(url, self.sender.splunk_post_url)
            active += 1
            max_active = max(max_active, active)
            try:
                await asyncio.sleep(0)
                return result(batch_index, len(batch))
            finally:
                active -= 1

        with patch.object(
            self.sender,
            "_http_post_strict_task",
            new=AsyncMock(side_effect=deliver),
        ):
            deliveries = asyncio.run(self.sender._post_batch_strict())

        self.assertEqual([item.batch_index for item in deliveries], [0, 1])
        self.assertEqual(max_active, 1)
        self.assertTrue(self.sender.post_queue.is_empty)

    def test_strict_cancellation_preserves_retryable_batches_and_cancellation(self):
        batches = [
            [{"event": "cancelled"}],
            [{"event": "retryable"}],
            [{"event": "accepted"}],
        ]
        for batch in batches:
            self.sender.post_queue.enqueue(batch)

        async def deliver(url, batch, batch_index):
            self.assertEqual(url, self.sender.splunk_post_url)
            if batch_index == 0:
                raise asyncio.CancelledError
            if batch_index == 1:
                raise HecTransportError(batch_index, len(batch), "timeout", True)
            return result(batch_index, len(batch))

        with patch.object(
            self.sender,
            "_http_post_strict_task",
            new=AsyncMock(side_effect=deliver),
        ):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(self.sender._post_batch_strict())

        self.assertEqual(self.sender.post_queue.elements, batches[:2])

    def test_external_cancellation_preserves_only_unknown_and_retryable_batches(self):
        batches = [
            [{"event": "accepted"}],
            [{"event": "retryable"}],
            [{"event": "unfinished"}],
        ]
        for batch in batches:
            self.sender.post_queue.enqueue(batch)

        async def cancel_delivery():
            unfinished_started = asyncio.Event()

            async def deliver(url, batch, batch_index):
                self.assertEqual(url, self.sender.splunk_post_url)
                if batch_index == 0:
                    return result(batch_index, len(batch))
                if batch_index == 1:
                    raise HecTransportError(
                        batch_index,
                        len(batch),
                        "timeout",
                        True,
                    )
                unfinished_started.set()
                await asyncio.Future()

            with patch.object(
                self.sender,
                "_http_post_strict_task",
                new=AsyncMock(side_effect=deliver),
            ):
                delivery = asyncio.create_task(self.sender._post_batch_strict())
                await unfinished_started.wait()
                await asyncio.sleep(0)
                delivery.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await delivery

        asyncio.run(cancel_delivery())

        self.assertEqual(self.sender.post_queue.elements, batches[1:])

    def test_strict_auto_flush_propagates_failure(self):
        self.sender.set_pop_empty_fields(False)
        self.sender.set_post_max_byte_size(4000)
        self.sender.set_concurrent_post_limit(1)
        first = {"event": "a" * 2200}
        second = {"event": "b" * 2200}
        failure = HecTransportError(0, 1, "request timed out", True)
        aggregate = HecBatchDeliveryError([], [failure])

        self.assertEqual(self.sender.post_data_strict(first), tuple())
        with patch.object(
            self.sender,
            "_http_post_strict_task",
            new=AsyncMock(side_effect=failure),
        ):
            with self.assertRaises(HecBatchDeliveryError) as raised:
                self.sender.post_data_strict(second)

        self.assertEqual(raised.exception.failures, aggregate.failures)
        self.assertFalse(self.sender._strict_delivery)
        self.assertEqual(self.sender.post_queue.elements, [[first]])
        self.assertEqual(self.sender.payload_queue.elements, [second])

        deliveries = self.sender.flush_strict()

        self.assertEqual([item.event_count for item in deliveries], [1, 1])
        self.assertTrue(self.sender.post_queue.is_empty)
        self.assertTrue(self.sender.payload_queue.is_empty)

    def test_strict_auto_flush_retains_triggering_payload_once_after_success(self):
        self.sender.set_pop_empty_fields(False)
        self.sender.set_post_max_byte_size(4000)
        self.sender.set_concurrent_post_limit(1)
        first = {"event": "a" * 2200}
        second = {"event": "b" * 2200}

        self.assertEqual(self.sender.post_data_strict(first), tuple())
        deliveries = self.sender.post_data_strict(second)

        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0].event_count, 1)
        self.assertTrue(self.sender.post_queue.is_empty)
        self.assertEqual(self.sender.payload_queue.elements, [second])

    def test_strict_post_rejects_wrong_payload_type_without_silent_skip(self):
        with self.assertRaisesRegex(
            TypeError,
            "Strict JSON payloads must be dictionaries",
        ):
            self.sender.post_data_strict("not-json")

        self.sender.set_payload_json_format(False)
        with self.assertRaisesRegex(
            TypeError,
            "Strict raw payloads must be strings",
        ):
            self.sender.post_data_strict({"event": "not-raw"})

        self.assertTrue(self.sender.payload_queue.is_empty)
        self.assertFalse(self.sender._strict_delivery)

    def test_strict_flush_returns_results_and_empty_flush_is_empty_tuple(self):
        self.sender.post_data_strict({"event": "queued"})

        deliveries = self.sender.flush_strict()

        self.assertEqual(len(deliveries), 1)
        self.assertTrue(deliveries[0].accepted)
        self.assertTrue(self.sender.payload_queue.is_empty)
        self.assertTrue(self.sender.post_queue.is_empty)
        self.assertEqual(self.sender.flush_strict(), tuple())

    def test_legacy_post_and_flush_do_not_enter_strict_path(self):
        self.sender.set_pop_empty_fields(False)
        self.sender.set_post_max_byte_size(4000)
        self.sender.set_concurrent_post_limit(1)
        first = {"event": "a" * 2200}
        second = {"event": "b" * 2200}

        with patch.object(
            self.sender,
            "_post_batch",
            new=AsyncMock(return_value=None),
        ) as legacy_post:
            with patch.object(
                self.sender,
                "_post_batch_strict",
                new=AsyncMock(
                    side_effect=AssertionError("legacy path must remain non-strict")
                ),
            ) as strict_post:
                self.assertIsNone(self.sender.post_data(first))
                self.assertIsNone(self.sender.post_data(second))

        legacy_post.assert_awaited_once_with()
        strict_post.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
