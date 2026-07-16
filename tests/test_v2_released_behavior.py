import asyncio
import logging
import unittest
import uuid
from unittest.mock import patch

from splunk_hec_aio.splunk_hec_aio import SplunkHecAio


class TestV2ReleasedBehavior(unittest.TestCase):
    def setUp(self):
        self.event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.event_loop)
        self.addCleanup(self._close_event_loop)

        self.sender = SplunkHecAio("splunk.example", "test-token")
        self.sender.log.setLevel(logging.CRITICAL)
        self.client_session = patch(
            "splunk_hec_aio.splunk_hec_aio.ClientSession",
            side_effect=AssertionError("compatibility tests must not use the network"),
        )
        self.client_session.start()
        self.addCleanup(self.client_session.stop)

    def _close_event_loop(self):
        asyncio.set_event_loop(None)
        self.event_loop.close()

    def test_constructor_and_configuration_defaults(self):
        self.assertEqual(self.sender.host, "splunk.example")
        self.assertEqual(self.sender.token, "test-token")
        self.assertTrue(self.sender.get_https())
        self.assertEqual(self.sender.get_port(), 8088)
        self.assertTrue(self.sender.get_pop_empty_fields())
        self.assertTrue(self.sender.get_payload_json_format())
        self.assertTrue(self.sender.get_verify_tls())
        self.assertEqual(self.sender.get_post_max_byte_size(), 512000)
        self.assertEqual(self.sender.get_concurrent_post_limit(), 10)
        self.assertIsNone(self.sender.get_index())
        self.assertIsNone(self.sender.get_sourcetype())
        self.assertIsNone(self.sender.get_source())
        self.assertIsNone(self.sender.get_host())

    def test_v3_constructor_rejects_invalid_required_values(self):
        # V2.1.2 accidentally checked a method reference instead of the host;
        # issue #8 intentionally corrects both required inputs for v3.
        cases = (
            (None, "test-token", "HOST must be a non-empty string."),
            ("", "test-token", "HOST must be a non-empty string."),
            (" \t", "test-token", "HOST must be a non-empty string."),
            (8088, "test-token", "HOST must be a non-empty string."),
            ("splunk.example", None, "HEC Token must be a non-empty string."),
            ("splunk.example", "", "HEC Token must be a non-empty string."),
            ("splunk.example", " \t", "HEC Token must be a non-empty string."),
            ("splunk.example", 1234, "HEC Token must be a non-empty string."),
        )

        for host, token, message in cases:
            with self.subTest(host=host, token=token):
                with self.assertRaises(ValueError) as raised:
                    SplunkHecAio(host, token)
                self.assertEqual(str(raised.exception), message)

    def test_invalid_setter_values_return_none_and_preserve_values(self):
        cases = (
            (self.sender.set_https, self.sender.get_https, "true"),
            (self.sender.set_port, self.sender.get_port, "8088"),
            (
                self.sender.set_pop_empty_fields,
                self.sender.get_pop_empty_fields,
                "true",
            ),
            (
                self.sender.set_payload_json_format,
                self.sender.get_payload_json_format,
                "true",
            ),
            (self.sender.set_verify_tls, self.sender.get_verify_tls, "true"),
            (
                self.sender.set_post_max_byte_size,
                self.sender.get_post_max_byte_size,
                "4000",
            ),
            (
                self.sender.set_concurrent_post_limit,
                self.sender.get_concurrent_post_limit,
                "10",
            ),
        )

        for setter, getter, invalid_value in cases:
            with self.subTest(setter=setter.__name__):
                before = getter()
                self.assertIsNone(setter(invalid_value))
                self.assertEqual(getter(), before)

    def test_numeric_setters_clamp_released_ranges(self):
        self.assertIsNone(self.sender.set_concurrent_post_limit(100))
        self.assertEqual(self.sender.get_concurrent_post_limit(), 20)
        self.assertIsNone(self.sender.set_post_max_byte_size(1))
        self.assertEqual(self.sender.get_post_max_byte_size(), 4000)
        self.assertIsNone(self.sender.set_post_max_byte_size(1000000))
        self.assertEqual(self.sender.get_post_max_byte_size(), 800000)

    def test_json_endpoint_headers_and_retry_defaults(self):
        channel = uuid.UUID("00000000-0000-0000-0000-000000000001")
        with patch("splunk_hec_aio.splunk_hec_aio.uuid.uuid1", return_value=channel):
            headers = self.sender.splunk_headers

        self.assertEqual(
            self.sender.splunk_post_url,
            "https://splunk.example:8088/services/collector/event",
        )
        self.assertEqual(self.sender.splunk_health_url, self.sender.splunk_post_url)
        self.assertEqual(
            headers,
            {
                "Authorization": "Splunk test-token",
                "Content-Encoding": "gzip",
                "Content-Type": "application/json",
                "User-Agent": "Splunk-hec-sender/1.0 (Python)",
                "X-Splunk-Request-Channel": str(channel),
            },
        )
        self.assertIsNone(self.sender.splunk_params)
        self.assertEqual(
            self.sender.retry_http_status_codes,
            {408, 429, 500, 502, 503, 504},
        )

    def test_raw_mode_endpoint_and_parameters(self):
        channel = uuid.UUID("00000000-0000-0000-0000-000000000002")
        self.sender.set_payload_json_format(False)
        self.sender.set_https(False)
        self.sender.set_index("main")
        self.sender.set_sourcetype("example")
        self.sender.set_source("compatibility-test")
        self.sender.set_host("source-host")

        with patch("splunk_hec_aio.splunk_hec_aio.uuid.uuid1", return_value=channel):
            params = self.sender.splunk_params

        self.assertEqual(
            self.sender.splunk_post_url,
            "http://splunk.example:8088/services/collector/raw",
        )
        self.assertEqual(
            params,
            {
                "channel": str(channel),
                "index": "main",
                "sourcetype": "example",
                "source": "compatibility-test",
                "host": "source-host",
            },
        )

    def test_post_data_success_returns_none_and_queues_json(self):
        payload = {"event": {"count": 1}, "time": "1.0"}

        self.assertIsNone(self.sender.post_data(payload))
        self.assertEqual(self.sender.payload_queue.size, 1)
        self.assertEqual(self.sender.payload_queue.first, payload)

    def test_post_data_preserves_false_values_and_removes_only_empty_values(self):
        # Issue #17 intentionally corrects v2's truthiness-based filtering.
        payload = {
            "event": {"count": 0},
            "zero": 0,
            "zero_float": 0.0,
            "false": False,
            "true": True,
            "empty": "",
            "empty_list": [],
            "empty_tuple": (),
            "empty_dict": {},
            "none": None,
        }

        self.sender.post_data(payload)

        self.assertIsNot(self.sender.payload_queue.first, payload)
        self.assertEqual(
            self.sender.payload_queue.first,
            {
                "event": {"count": 0},
                "zero": 0,
                "zero_float": 0.0,
                "false": False,
                "true": True,
            },
        )
        self.assertEqual(
            payload,
            {
                "event": {"count": 0},
                "zero": 0,
                "zero_float": 0.0,
                "false": False,
                "true": True,
                "empty": "",
                "empty_list": [],
                "empty_tuple": (),
                "empty_dict": {},
                "none": None,
            },
        )

    def test_wrong_payload_type_is_skipped_without_raising(self):
        self.assertIsNone(self.sender.post_data("not-json-mode"))
        self.assertTrue(self.sender.payload_queue.is_empty)

    def test_empty_flush_returns_none_without_network_activity(self):
        with patch.object(self.sender, "_post_batch") as post_batch:
            self.assertIsNone(self.sender.flush())
        post_batch.assert_not_called()

    def test_string_representation_is_side_effect_free_in_v3(self):
        # V2.1.2 called check_connectivity(); issue #9 intentionally removes
        # that network-visible side effect in the v3 development line.
        with patch.object(
            self.sender,
            "check_connectivity",
            side_effect=AssertionError("str() must not check connectivity"),
        ) as connectivity:
            rendered = str(self.sender)

        connectivity.assert_not_called()
        self.assertEqual(
            rendered,
            "Splunk: HOST=splunk.example HTTPS=True Reachable=NotChecked "
            "PopEmptyFields=True PayloadModeJSON=True ConcurrentPostLimit=10",
        )


if __name__ == "__main__":
    unittest.main()
