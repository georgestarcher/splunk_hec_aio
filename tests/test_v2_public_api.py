import inspect
import json
import unittest
from pathlib import Path

import splunk_hec_aio.splunk_hec_aio as module
from splunk_hec_aio.splunk_hec_aio import SplunkHecAio

FIXTURE = Path(__file__).parent / "fixtures" / "v2_1_1_public_api.json"


def public_api_snapshot():
    members = {}
    for name, value in inspect.getmembers(SplunkHecAio):
        if name.startswith("_"):
            continue
        if isinstance(value, property):
            members[name] = {"kind": "property"}
        elif inspect.isfunction(value):
            members[name] = {
                "kind": "method",
                "signature": str(inspect.signature(value)),
            }

    return {
        "module": module.__name__,
        "class": SplunkHecAio.__name__,
        "constructor_signature": str(inspect.signature(SplunkHecAio)),
        "members": members,
    }


class TestV2PublicApi(unittest.TestCase):
    def test_documented_nested_import_remains_available(self):
        self.assertIs(module.SplunkHecAio, SplunkHecAio)

    def test_v2_public_api_remains_present_with_approved_v3_additions(self):
        with FIXTURE.open(encoding="utf-8") as fixture_file:
            expected = json.load(fixture_file)

        self.assertEqual(expected.pop("baseline_version"), "2.1.1")
        actual = public_api_snapshot()
        expected_members = expected.pop("members")
        actual_members = actual.pop("members")

        self.assertEqual(actual, expected)
        self.assertEqual(
            {name: actual_members[name] for name in expected_members},
            expected_members,
        )
        self.assertEqual(
            set(actual_members) - set(expected_members),
            {
                "check_connectivity_async",
                "flush_ack",
                "flush_ack_async",
                "flush_async",
                "flush_strict",
                "flush_strict_async",
                "post_data_ack",
                "post_data_ack_async",
                "post_data_async",
                "post_data_strict",
                "post_data_strict_async",
            },
        )

    def test_v3_strict_delivery_types_are_available_from_nested_module(self):
        self.assertTrue(inspect.isclass(module.HecDeliveryResult))
        self.assertTrue(issubclass(module.HecDeliveryError, Exception))
        self.assertTrue(issubclass(module.HecResponseError, module.HecDeliveryError))
        self.assertTrue(issubclass(module.HecTransportError, module.HecDeliveryError))
        self.assertTrue(
            issubclass(module.HecBatchDeliveryError, module.HecDeliveryError)
        )

    def test_v3_acknowledgment_types_are_available_from_nested_module(self):
        self.assertTrue(inspect.isclass(module.HecAcknowledgmentResult))
        self.assertTrue(inspect.isclass(module.HecAcknowledgmentFailure))
        self.assertTrue(
            issubclass(module.HecAcknowledgmentError, module.HecDeliveryError)
        )

    def test_v3_stable_version_is_exposed_from_the_runtime_module(self):
        self.assertEqual(module.__version__, "3.0.0")


if __name__ == "__main__":
    unittest.main()
