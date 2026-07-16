import asyncio
import inspect
import json
import math
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web

from splunk_hec_aio.splunk_hec_aio import (
    HecAcknowledgmentError,
    HecAcknowledgmentResult,
    HecDeliveryResult,
    HecResponseError,
    SplunkHecAio,
    _HecAcknowledgmentDelivery,
)


class _AckHecServer:
    def __init__(self):
        self.event_requests = []
        self.ack_requests = []
        self.event_responses = []
        self.event_responder = None
        self.ack_responder = lambda ack_ids: {str(ack_id): True for ack_id in ack_ids}
        self.runner = None
        self.port = None

    async def start(self):
        app = web.Application()
        app.router.add_post("/services/collector/event", self._event)
        app.router.add_post("/services/collector/raw", self._event)
        app.router.add_post("/services/collector/ack", self._ack)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]

    async def close(self):
        if self.runner is not None:
            await self.runner.cleanup()

    async def _event(self, request):
        body = await request.read()
        self.event_requests.append(
            {
                "path": request.path,
                "query": dict(request.query),
                "headers": dict(request.headers),
                "body": body,
            }
        )
        if self.event_responder is None:
            response = self.event_responses.pop(0)
        else:
            response = self.event_responder(request, body)
            if inspect.isawaitable(response):
                response = await response
        return web.json_response(response)

    async def _ack(self, request):
        body = await request.read()
        payload = json.loads(body)
        self.ack_requests.append(
            {
                "headers": dict(request.headers),
                "body": body,
                "ack_ids": payload["acks"],
                "query": dict(request.query),
            }
        )
        response = self.ack_responder(payload["acks"])
        if inspect.isawaitable(response):
            response = await response
        if isinstance(response, web.StreamResponse):
            return response
        return web.json_response({"acks": response})


class TestIndexerAcknowledgment(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = _AckHecServer()
        await self.server.start()
        self.sender = SplunkHecAio("127.0.0.1", "test-token")
        self.sender.set_https(False)
        self.sender.set_port(self.server.port)
        self.sender.http_retries = 1

    async def asyncTearDown(self):
        await self.server.close()

    async def test_multiple_batches_use_one_channel_and_stop_polling_true_ids(self):
        self.sender.set_pop_empty_fields(False)
        self.sender.set_post_max_byte_size(4000)
        self.sender.set_concurrent_post_limit(2)
        events = [
            {"event": "a" * 2200},
            {"event": "b" * 2200},
            {"event": "c" * 2200},
        ]

        def event_response(request, body):
            del request
            marker = json.loads(body)["event"][0]
            ack_ids = {"a": 10, "b": 11, "c": 12}
            if marker == "b":
                return {"text": "Success", "code": 0, "ackID": "11"}
            return {"text": "Success", "code": 0, "ackId": ack_ids[marker]}

        self.server.event_responder = event_response
        poll_count = 0

        def acknowledge(ack_ids):
            nonlocal poll_count
            poll_count += 1
            if poll_count == 1:
                return {str(ack_id): ack_id == 10 for ack_id in ack_ids}
            return {str(ack_id): True for ack_id in ack_ids}

        self.server.ack_responder = acknowledge

        self.assertEqual(
            await self.sender.post_data_ack_async(
                events[0], timeout=1, poll_interval=0.01
            ),
            tuple(),
        )
        self.assertEqual(
            await self.sender.post_data_ack_async(
                events[1], timeout=1, poll_interval=0.01
            ),
            tuple(),
        )
        automatic = await self.sender.post_data_ack_async(
            events[2], timeout=1, poll_interval=0.01
        )
        final = await self.sender.flush_ack_async(
            timeout=1,
            poll_interval=0.01,
        )

        self.assertEqual({result.ack_id for result in automatic}, {10, 11})
        self.assertEqual({result.batch_index for result in automatic}, {0, 1})
        self.assertTrue(all(result.acknowledged for result in automatic))
        self.assertEqual(
            final,
            (
                HecAcknowledgmentResult(
                    batch_index=2,
                    event_count=1,
                    ack_id=12,
                    acknowledged=True,
                ),
            ),
        )
        self.assertEqual(
            [request["ack_ids"] for request in self.server.ack_requests],
            [[10, 11], [11], [12]],
        )

        channels = {
            request["headers"]["X-Splunk-Request-Channel"]
            for request in self.server.event_requests + self.server.ack_requests
        }
        self.assertEqual(len(channels), 1)
        self.assertNotIn(
            "Content-Encoding",
            self.server.ack_requests[0]["headers"],
        )
        self.assertTrue(
            all(
                request["query"]["channel"]
                == request["headers"]["X-Splunk-Request-Channel"]
                for request in self.server.ack_requests
            )
        )
        self.assertCountEqual(
            [json.loads(request["body"]) for request in self.server.event_requests],
            events,
        )
        self.assertTrue(
            all(
                request["headers"]["Content-Encoding"] == "gzip"
                for request in self.server.event_requests
            )
        )
        self.assertEqual(self.sender._ack_pending, {})

    async def test_raw_mode_reuses_channel_in_header_and_query(self):
        self.sender.set_payload_json_format(False)
        self.sender.set_index("main")
        self.sender.set_sourcetype("example:raw")
        self.server.event_responses.append(
            {"text": "Success", "code": 0, "ackID": "20"}
        )
        payload = "first\nsecond\n"

        self.assertEqual(
            await self.sender.post_data_ack_async(payload),
            tuple(),
        )
        result = await self.sender.flush_ack_async(
            timeout=1,
            poll_interval=0.01,
        )

        self.assertEqual(result[0].ack_id, 20)
        request = self.server.event_requests[0]
        channel = request["headers"]["X-Splunk-Request-Channel"]
        self.assertEqual(request["path"], "/services/collector/raw")
        self.assertEqual(request["query"]["channel"], channel)
        self.assertEqual(request["query"]["index"], "main")
        self.assertEqual(request["query"]["sourcetype"], "example:raw")
        self.assertEqual(request["body"].decode("utf-8"), payload)
        self.assertEqual(
            self.server.ack_requests[0]["headers"]["X-Splunk-Request-Channel"],
            channel,
        )

    async def test_missing_ack_identifier_is_typed_and_not_polled(self):
        self.server.event_responses.append({"text": "Success", "code": 0})
        await self.sender.post_data_ack_async({"event": "missing"})

        with self.assertRaises(HecAcknowledgmentError) as raised:
            await self.sender.flush_ack_async(
                timeout=1,
                poll_interval=0.01,
            )

        self.assertEqual(raised.exception.results, tuple())
        self.assertEqual(len(raised.exception.failures), 1)
        failure = raised.exception.failures[0]
        self.assertEqual(failure.category, "acknowledgment identifier missing")
        self.assertFalse(failure.retryable)
        self.assertIsNone(failure.ack_id)
        self.assertEqual(self.server.ack_requests, [])
        self.assertEqual(self.sender._ack_pending, {})

    async def test_malformed_status_retains_id_and_next_flush_resumes_without_resend(
        self,
    ):
        self.server.event_responses.append({"text": "Success", "code": 0, "ackId": 21})
        self.server.ack_responder = lambda ack_ids: {
            str(ack_id): "yes" for ack_id in ack_ids
        }
        await self.sender.post_data_ack_async({"event": "resume"})

        with self.assertRaises(HecAcknowledgmentError) as raised:
            await self.sender.flush_ack_async(
                timeout=1,
                poll_interval=0.01,
            )

        self.assertEqual(
            raised.exception.failures[0].category,
            "malformed acknowledgment response",
        )
        self.assertEqual(set(self.sender._ack_pending), {21})
        self.assertEqual(len(self.server.event_requests), 1)

        self.server.ack_responder = lambda ack_ids: {
            str(ack_id): True for ack_id in ack_ids
        }
        resumed = await self.sender.flush_ack_async(
            timeout=1,
            poll_interval=0.01,
        )

        self.assertEqual(resumed[0].ack_id, 21)
        self.assertEqual(len(self.server.event_requests), 1)
        self.assertEqual(
            [request["ack_ids"] for request in self.server.ack_requests],
            [[21], [21]],
        )

    async def test_timeout_reports_mixed_results_and_keeps_only_false_id(self):
        def event_response(request, body):
            del request
            event_name = json.loads(body)["event"]
            ack_id = 30 if event_name == "confirmed" else 31
            return {"text": "Success", "code": 0, "ackId": ack_id}

        self.server.event_responder = event_response
        self.server.ack_responder = lambda ack_ids: {
            str(ack_id): ack_id == 30 for ack_id in ack_ids
        }
        self.sender.post_queue.enqueue([{"event": "confirmed"}])
        self.sender.post_queue.enqueue([{"event": "pending"}])

        with self.assertRaises(HecAcknowledgmentError) as raised:
            await self.sender.flush_ack_async(
                timeout=0.04,
                poll_interval=0.01,
            )

        self.assertEqual([result.ack_id for result in raised.exception.results], [30])
        self.assertEqual(
            [failure.ack_id for failure in raised.exception.failures], [31]
        )
        self.assertEqual(
            raised.exception.failures[0].category,
            "acknowledgment timed out",
        )
        self.assertTrue(raised.exception.failures[0].retryable)
        self.assertEqual(set(self.sender._ack_pending), {31})
        self.assertEqual(self.server.ack_requests[0]["ack_ids"], [30, 31])
        self.assertTrue(
            all(request["ack_ids"] == [31] for request in self.server.ack_requests[1:])
        )

    async def test_poll_cancellation_propagates_and_preserves_pending_id(self):
        self.sender._ack_pending[40] = HecAcknowledgmentResult(
            batch_index=0,
            event_count=1,
            ack_id=40,
            acknowledged=False,
        )

        with patch.object(
            self.sender,
            "_http_ack_status_task",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await self.sender.flush_ack_async(
                    timeout=1,
                    poll_interval=0.01,
                )

        self.assertEqual(set(self.sender._ack_pending), {40})
        with patch.object(
            self.sender,
            "_http_ack_status_task",
            new=AsyncMock(return_value={40: True}),
        ):
            resumed = await self.sender.flush_ack_async(
                timeout=1,
                poll_interval=0.01,
            )
        self.assertEqual(resumed[0].ack_id, 40)
        self.assertEqual(self.sender._ack_pending, {})

    async def test_poll_cancellation_preserves_confirmed_result(self):
        for ack_id in (46, 47):
            self.sender._ack_pending[ack_id] = HecAcknowledgmentResult(
                batch_index=ack_id - 46,
                event_count=1,
                ack_id=ack_id,
                acknowledged=False,
            )

        second_poll_started = asyncio.Event()
        poll_count = 0

        async def acknowledge(ack_ids, channel, request_timeout):
            nonlocal poll_count
            del channel, request_timeout
            poll_count += 1
            if poll_count == 1:
                self.assertEqual(ack_ids, (46, 47))
                return {46: True, 47: False}
            self.assertEqual(ack_ids, (47,))
            second_poll_started.set()
            await asyncio.Future()

        with patch.object(
            self.sender,
            "_http_ack_status_task",
            new=AsyncMock(side_effect=acknowledge),
        ):
            flush = asyncio.create_task(
                self.sender.flush_ack_async(timeout=1, poll_interval=0.001)
            )
            await second_poll_started.wait()
            flush.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await flush

        self.assertEqual(set(self.sender._ack_pending), {47})
        self.assertEqual(
            [result.ack_id for result in self.sender._ack_deferred_results],
            [46],
        )

        with patch.object(
            self.sender,
            "_http_ack_status_task",
            new=AsyncMock(return_value={47: True}),
        ):
            resumed = await self.sender.flush_ack_async(
                timeout=1,
                poll_interval=0.01,
            )

        self.assertEqual([result.ack_id for result in resumed], [46, 47])
        self.assertEqual(self.sender._ack_pending, {})
        self.assertEqual(self.sender._ack_deferred_results, [])

    async def test_poll_cancellation_preserves_known_delivery_failure(self):
        def event_response(request, body):
            del request
            event_name = json.loads(body)["event"]
            if event_name == "accepted":
                return {"text": "Success", "code": 0, "ackId": 42}
            return {"text": "Invalid event", "code": 5}

        self.server.event_responder = event_response
        self.sender.post_queue.enqueue([{"event": "accepted"}])
        self.sender.post_queue.enqueue([{"event": "rejected"}])

        with patch.object(
            self.sender,
            "_http_ack_status_task",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await self.sender.flush_ack_async(
                    timeout=1,
                    poll_interval=0.01,
                )

        self.assertEqual(set(self.sender._ack_pending), {42})
        self.assertEqual(len(self.sender._ack_deferred_failures), 1)
        self.assertEqual(
            self.sender._ack_deferred_failures[0].category,
            "delivery rejected",
        )
        self.assertFalse(self.sender._ack_deferred_failures[0].retryable)

        with patch.object(
            self.sender,
            "_http_ack_status_task",
            new=AsyncMock(return_value={42: True}),
        ):
            with self.assertRaises(HecAcknowledgmentError) as resumed:
                await self.sender.flush_ack_async(
                    timeout=1,
                    poll_interval=0.01,
                )

        self.assertEqual([result.ack_id for result in resumed.exception.results], [42])
        self.assertEqual(len(resumed.exception.failures), 1)
        self.assertEqual(
            resumed.exception.failures[0].category,
            "delivery rejected",
        )
        self.assertEqual(self.sender._ack_pending, {})
        self.assertEqual(self.sender._ack_deferred_failures, [])

    async def test_send_cancellation_preserves_accepted_id_and_unsent_batch(self):
        self.sender.set_concurrent_post_limit(2)
        self.sender.post_queue.enqueue([{"event": "accepted"}])
        self.sender.post_queue.enqueue([{"event": "cancelled"}])
        second_started = asyncio.Event()

        async def deliver(url, batch, batch_index, ack_channel):
            self.assertEqual(url, self.sender.splunk_post_url)
            self.assertEqual(ack_channel, self.sender._ack_channel)
            if batch_index == 0:
                return _HecAcknowledgmentDelivery(
                    delivery=HecDeliveryResult(
                        batch_index=0,
                        event_count=len(batch),
                        http_status=200,
                        http_reason="OK",
                        hec_code=0,
                        hec_text="Success",
                        invalid_event_number=None,
                        accepted=True,
                        retryable=False,
                    ),
                    ack_id=41,
                )
            second_started.set()
            await asyncio.Future()

        with patch.object(
            self.sender,
            "_http_post_strict_task",
            new=AsyncMock(side_effect=deliver),
        ):
            flush = asyncio.create_task(
                self.sender.flush_ack_async(timeout=1, poll_interval=0.01)
            )
            await second_started.wait()
            await asyncio.sleep(0)
            flush.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await flush

        self.assertEqual(set(self.sender._ack_pending), {41})
        self.assertEqual(self.sender.post_queue.size, 1)
        self.assertEqual(
            self.sender.post_queue.elements[0],
            [{"event": "cancelled"}],
        )

    async def test_later_wave_cancellation_preserves_earlier_ack_outcomes(self):
        self.sender.set_concurrent_post_limit(1)
        self.sender.post_queue.enqueue([{"event": "accepted"}])
        self.sender.post_queue.enqueue([{"event": "rejected"}])
        self.sender.post_queue.enqueue([{"event": "cancelled"}])
        third_started = asyncio.Event()

        async def deliver(url, batch, batch_index, ack_channel):
            self.assertEqual(url, self.sender.splunk_post_url)
            self.assertEqual(ack_channel, self.sender._ack_channel)
            if batch_index == 0:
                return _HecAcknowledgmentDelivery(
                    delivery=HecDeliveryResult(
                        batch_index=batch_index,
                        event_count=len(batch),
                        http_status=200,
                        http_reason="OK",
                        hec_code=0,
                        hec_text="Success",
                        invalid_event_number=None,
                        accepted=True,
                        retryable=False,
                    ),
                    ack_id=43,
                )
            if batch_index == 1:
                raise HecResponseError(
                    HecDeliveryResult(
                        batch_index=batch_index,
                        event_count=len(batch),
                        http_status=400,
                        http_reason="Bad Request",
                        hec_code=5,
                        hec_text="Invalid event",
                        invalid_event_number=None,
                        accepted=False,
                        retryable=False,
                    )
                )
            third_started.set()
            await asyncio.Future()

        with patch.object(
            self.sender,
            "_http_post_strict_task",
            new=AsyncMock(side_effect=deliver),
        ):
            flush = asyncio.create_task(
                self.sender.flush_ack_async(timeout=1, poll_interval=0.01)
            )
            await third_started.wait()
            flush.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await flush

        self.assertEqual(set(self.sender._ack_pending), {43})
        self.assertEqual(len(self.sender._ack_deferred_failures), 1)
        self.assertEqual(
            self.sender._ack_deferred_failures[0].category,
            "delivery rejected",
        )
        self.assertEqual(
            self.sender.post_queue.elements,
            [[{"event": "cancelled"}]],
        )

        async def deliver_resumed(url, batch, batch_index, ack_channel):
            self.assertEqual(url, self.sender.splunk_post_url)
            self.assertEqual(batch_index, 2)
            self.assertEqual(ack_channel, self.sender._ack_channel)
            return _HecAcknowledgmentDelivery(
                delivery=HecDeliveryResult(
                    batch_index=batch_index,
                    event_count=len(batch),
                    http_status=200,
                    http_reason="OK",
                    hec_code=0,
                    hec_text="Success",
                    invalid_event_number=None,
                    accepted=True,
                    retryable=False,
                ),
                ack_id=45,
            )

        with (
            patch.object(
                self.sender,
                "_http_post_strict_task",
                new=AsyncMock(side_effect=deliver_resumed),
            ),
            patch.object(
                self.sender,
                "_http_ack_status_task",
                new=AsyncMock(return_value={43: True, 45: True}),
            ),
        ):
            with self.assertRaises(HecAcknowledgmentError) as resumed:
                await self.sender.flush_ack_async(
                    timeout=1,
                    poll_interval=0.01,
                )

        self.assertEqual(
            [result.ack_id for result in resumed.exception.results],
            [43, 45],
        )
        self.assertEqual(len(resumed.exception.failures), 1)
        self.assertEqual(resumed.exception.failures[0].batch_index, 1)
        self.assertEqual(self.sender._ack_pending, {})
        self.assertEqual(self.sender._ack_deferred_failures, [])
        self.assertTrue(self.sender.post_queue.is_empty)

    async def test_polling_controls_are_finite_positive_numbers(self):
        invalid_values = (True, 0, -1, math.inf, math.nan, "1")
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    await self.sender.flush_ack_async(timeout=value)
                with self.assertRaises(ValueError):
                    await self.sender.flush_ack_async(poll_interval=value)

    async def test_ack_id_parser_rejects_duplicate_identifier(self):
        self.server.event_responses.extend(
            [
                {"text": "Success", "code": 0, "ackId": 50},
                {"text": "Success", "code": 0, "ackId": 50},
            ]
        )
        self.sender.post_queue.enqueue([{"event": "first"}])
        self.sender.post_queue.enqueue([{"event": "second"}])

        with self.assertRaises(HecAcknowledgmentError) as raised:
            await self.sender.flush_ack_async(
                timeout=1,
                poll_interval=0.01,
            )

        self.assertEqual([result.ack_id for result in raised.exception.results], [50])
        self.assertEqual(len(raised.exception.failures), 1)
        self.assertEqual(
            raised.exception.failures[0].category,
            "duplicate acknowledgment identifier",
        )
        self.assertEqual(self.sender._ack_pending, {})

    async def test_partial_send_failure_confirms_success_and_retains_retryable_batch(
        self,
    ):
        def event_response(request, body):
            del request
            event_name = json.loads(body)["event"]
            if event_name == "accepted":
                return {"text": "Success", "code": 0, "ackId": 60}
            return {"text": "Server is busy", "code": 9}

        self.server.event_responder = event_response
        self.sender.post_queue.enqueue([{"event": "accepted"}])
        self.sender.post_queue.enqueue([{"event": "retry"}])

        with self.assertRaises(HecAcknowledgmentError) as raised:
            await self.sender.flush_ack_async(
                timeout=1,
                poll_interval=0.01,
            )

        self.assertEqual([result.ack_id for result in raised.exception.results], [60])
        self.assertEqual(len(raised.exception.failures), 1)
        failure = raised.exception.failures[0]
        self.assertEqual(failure.category, "delivery rejected")
        self.assertTrue(failure.retryable)
        self.assertIsNone(failure.ack_id)
        self.assertEqual(self.sender.post_queue.size, 1)
        self.assertEqual(
            self.sender.post_queue.elements[0],
            [{"event": "retry"}],
        )
        self.assertEqual(self.sender._ack_pending, {})

    async def test_ack_event_failure_is_not_retried_automatically(self):
        self.sender.http_retries = 3
        self.server.event_responses.append({"text": "Server is busy", "code": 9})
        await self.sender.post_data_ack_async({"event": "single-attempt"})

        with self.assertRaises(HecAcknowledgmentError) as raised:
            await self.sender.flush_ack_async(
                timeout=1,
                poll_interval=0.01,
            )

        self.assertEqual(len(self.server.event_requests), 1)
        self.assertEqual(self.server.ack_requests, [])
        self.assertEqual(len(raised.exception.failures), 1)
        self.assertTrue(raised.exception.failures[0].retryable)
        self.assertEqual(self.sender.post_queue.size, 1)


if __name__ == "__main__":
    unittest.main()
