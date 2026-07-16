import asyncio
import inspect
import logging
import unittest
from unittest.mock import AsyncMock, patch

from splunk_hec_aio.splunk_hec_aio import (
    HecBatchDeliveryError,
    HecDeliveryResult,
    HecTransportError,
    SplunkHecAio,
)


def result(batch_index, event_count):
    return HecDeliveryResult(
        batch_index=batch_index,
        event_count=event_count,
        http_status=200,
        http_reason="OK",
        hec_code=0,
        hec_text="Success",
        invalid_event_number=None,
        accepted=True,
        retryable=False,
    )


class TestAsyncPublicApi(unittest.TestCase):
    def setUp(self):
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)
        self.addCleanup(self._close_event_loop)
        self.sender = SplunkHecAio("splunk.example", "test-token")
        self.sender.log.setLevel(logging.CRITICAL)

    def _close_event_loop(self):
        asyncio.set_event_loop(None)
        if not self.event_loop.is_closed():
            self.event_loop.close()

    def test_public_async_entry_points_are_coroutines(self):
        for method_name in (
            "check_connectivity_async",
            "flush_async",
            "flush_strict_async",
            "post_data_async",
            "post_data_strict_async",
        ):
            with self.subTest(method=method_name):
                self.assertTrue(
                    inspect.iscoroutinefunction(getattr(self.sender, method_name))
                )

    def test_async_connectivity_awaits_existing_health_implementation(self):
        async def exercise():
            with patch(
                "splunk_hec_aio.splunk_hec_aio.asyncio.run",
                side_effect=AssertionError("async API started another event loop"),
            ):
                with patch.object(
                    self.sender,
                    "_check_connectivity",
                    new=AsyncMock(return_value=True),
                ) as health_check:
                    self.assertTrue(await self.sender.check_connectivity_async())
                    health_check.assert_awaited_once_with()

        asyncio.run(exercise())

    def test_sender_can_be_created_and_used_inside_running_event_loop(self):
        async def exercise():
            sender = SplunkHecAio("splunk.example", "test-token")
            sender.log.setLevel(logging.CRITICAL)

            with patch(
                "splunk_hec_aio.splunk_hec_aio.asyncio.run",
                side_effect=AssertionError("async API started another event loop"),
            ):
                with patch.object(
                    sender,
                    "_check_connectivity",
                    new=AsyncMock(return_value=True),
                ):
                    self.assertTrue(await sender.check_connectivity_async())

                self.assertIsNone(
                    await sender.post_data_async({"event": "running-loop"})
                )
                with patch.object(
                    sender,
                    "_post_batch",
                    new=AsyncMock(return_value=None),
                ) as post_batch:
                    self.assertIsNone(await sender.flush_async())
                    post_batch.assert_awaited_once_with()

        asyncio.run(exercise())

    def test_compatible_async_auto_flush_and_final_flush(self):
        self.sender.set_pop_empty_fields(False)
        self.sender.set_post_max_byte_size(4000)
        self.sender.set_concurrent_post_limit(1)
        first = {"event": "a" * 2200}
        second = {"event": "b" * 2200}
        delivered = []

        async def deliver_compatible_batches():
            while not self.sender.post_queue.is_empty:
                delivered.append(self.sender.post_queue.dequeue())

        async def exercise():
            with patch(
                "splunk_hec_aio.splunk_hec_aio.asyncio.run",
                side_effect=AssertionError("async API started another event loop"),
            ):
                with patch.object(
                    self.sender,
                    "_post_batch",
                    new=AsyncMock(side_effect=deliver_compatible_batches),
                ) as post_batch:
                    self.assertIsNone(await self.sender.post_data_async(first))
                    self.assertIsNone(await self.sender.post_data_async(second))
                    self.assertEqual(delivered, [[first]])
                    self.assertEqual(self.sender.payload_queue.elements, [second])
                    post_batch.assert_awaited_once_with()

                    self.assertIsNone(await self.sender.flush_async())
                    self.assertEqual(delivered, [[first], [second]])
                    self.assertEqual(post_batch.await_count, 2)

        asyncio.run(exercise())
        self.assertTrue(self.sender.payload_queue.is_empty)
        self.assertTrue(self.sender.post_queue.is_empty)

    def test_compatible_async_cancellation_retains_triggering_payload(self):
        self.sender.set_pop_empty_fields(False)
        self.sender.set_post_max_byte_size(4000)
        self.sender.set_concurrent_post_limit(1)
        first = {"event": "a" * 2200}
        second = {"event": "b" * 2200}

        async def cancel_delivery():
            raise asyncio.CancelledError

        async def exercise():
            self.assertIsNone(await self.sender.post_data_async(first))
            with patch.object(
                self.sender,
                "_post_batch",
                new=AsyncMock(side_effect=cancel_delivery),
            ):
                with self.assertRaises(asyncio.CancelledError):
                    await self.sender.post_data_async(second)

        asyncio.run(exercise())
        self.assertEqual(self.sender.post_queue.elements, [[first]])
        self.assertEqual(self.sender.payload_queue.elements, [second])

    def test_strict_async_auto_flush_and_final_flush_return_results(self):
        self.sender.set_pop_empty_fields(False)
        self.sender.set_post_max_byte_size(4000)
        self.sender.set_concurrent_post_limit(1)
        first = {"event": "a" * 2200}
        second = {"event": "b" * 2200}

        async def deliver(url, batch, batch_index):
            self.assertEqual(url, self.sender.splunk_post_url)
            return result(batch_index, len(batch))

        async def exercise():
            with patch(
                "splunk_hec_aio.splunk_hec_aio.asyncio.run",
                side_effect=AssertionError("async API started another event loop"),
            ):
                with patch.object(
                    self.sender,
                    "_http_post_strict_task",
                    new=AsyncMock(side_effect=deliver),
                ):
                    self.assertEqual(
                        await self.sender.post_data_strict_async(first),
                        tuple(),
                    )
                    automatic = await self.sender.post_data_strict_async(second)
                    final = await self.sender.flush_strict_async()
                    empty = await self.sender.flush_strict_async()

            self.assertEqual([item.batch_index for item in automatic], [0])
            self.assertEqual([item.batch_index for item in final], [1])
            self.assertEqual(empty, tuple())

        asyncio.run(exercise())
        self.assertTrue(self.sender.payload_queue.is_empty)
        self.assertTrue(self.sender.post_queue.is_empty)

    def test_strict_async_failure_propagates_and_retains_all_queued_work(self):
        self.sender.set_pop_empty_fields(False)
        self.sender.set_post_max_byte_size(4000)
        self.sender.set_concurrent_post_limit(1)
        first = {"event": "a" * 2200}
        second = {"event": "b" * 2200}

        async def fail(url, batch, batch_index):
            self.assertEqual(url, self.sender.splunk_post_url)
            raise HecTransportError(
                batch_index,
                len(batch),
                "request timed out",
                True,
            )

        async def recover(url, batch, batch_index):
            self.assertEqual(url, self.sender.splunk_post_url)
            return result(batch_index, len(batch))

        async def exercise():
            self.assertEqual(
                await self.sender.post_data_strict_async(first),
                tuple(),
            )
            with patch.object(
                self.sender,
                "_http_post_strict_task",
                new=AsyncMock(side_effect=fail),
            ):
                with self.assertRaises(HecBatchDeliveryError) as raised:
                    await self.sender.post_data_strict_async(second)

            self.assertTrue(raised.exception.failures[0].retryable)
            self.assertEqual(self.sender.post_queue.elements, [[first]])
            self.assertEqual(self.sender.payload_queue.elements, [second])

            with patch.object(
                self.sender,
                "_http_post_strict_task",
                new=AsyncMock(side_effect=recover),
            ):
                recovered = await self.sender.flush_strict_async()

            self.assertEqual([item.batch_index for item in recovered], [0, 1])

        asyncio.run(exercise())
        self.assertTrue(self.sender.payload_queue.is_empty)
        self.assertTrue(self.sender.post_queue.is_empty)

    def test_async_payload_validation_matches_selected_delivery_mode(self):
        async def exercise():
            self.assertIsNone(await self.sender.post_data_async("not-json"))
            self.assertTrue(self.sender.payload_queue.is_empty)

            with self.assertRaisesRegex(
                TypeError,
                "Strict JSON payloads must be dictionaries",
            ):
                await self.sender.post_data_strict_async("not-json")

            self.sender.set_payload_json_format(False)
            self.assertIsNone(await self.sender.post_data_async({"event": "not-raw"}))
            with self.assertRaisesRegex(
                TypeError,
                "Strict raw payloads must be strings",
            ):
                await self.sender.post_data_strict_async({"event": "not-raw"})

        asyncio.run(exercise())
        self.assertTrue(self.sender.payload_queue.is_empty)


if __name__ == "__main__":
    unittest.main()
