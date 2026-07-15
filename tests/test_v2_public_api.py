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

    def test_public_api_matches_v2_1_1_snapshot(self):
        with FIXTURE.open(encoding="utf-8") as fixture_file:
            expected = json.load(fixture_file)

        self.assertEqual(expected.pop("baseline_version"), "2.1.1")
        self.assertEqual(public_api_snapshot(), expected)

    def test_v3_development_version_is_exposed_from_the_runtime_module(self):
        self.assertEqual(module.__version__, "3.0.0.dev0")


if __name__ == "__main__":
    unittest.main()
