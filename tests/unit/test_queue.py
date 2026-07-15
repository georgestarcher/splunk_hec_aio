import json
import unittest

from splunk_hec_aio.splunk_hec_aio import _SplunkQueue


class TestSplunkQueue(unittest.TestCase):
    def test_queue_is_fifo_and_exposes_ends_without_removing_them(self):
        queue = _SplunkQueue()
        first = {"event": "first"}
        second = {"event": "second"}

        queue.enqueue(first)
        queue.enqueue(second)

        self.assertEqual(queue.size, 2)
        self.assertEqual(queue.first, first)
        self.assertEqual(queue.last, second)
        self.assertEqual(queue.dequeue(), first)
        self.assertEqual(queue.dequeue(), second)
        self.assertTrue(queue.is_empty)

    def test_empty_queue_accessors_and_dequeue_return_none(self):
        queue = _SplunkQueue()

        self.assertIsNone(queue.first)
        self.assertIsNone(queue.last)
        self.assertIsNone(queue.dequeue())
        self.assertEqual(queue.byte_size, 0)
        self.assertEqual(str(queue), "[]")

    def test_clear_replaces_all_queued_elements(self):
        queue = _SplunkQueue([{"event": 1}, {"event": 2}])

        queue.clear()

        self.assertTrue(queue.is_empty)
        self.assertEqual(queue.elements, [])

    def test_byte_size_matches_the_released_json_queue_representation(self):
        elements = [{"event": "café"}, {"event": {"count": 2}}]
        queue = _SplunkQueue(elements)

        self.assertEqual(queue.byte_size, len(json.dumps(elements, default=str)))


if __name__ == "__main__":
    unittest.main()
