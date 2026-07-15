import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "tests" / "packaging" / "verify_artifacts.py"

SPEC = importlib.util.spec_from_file_location("verify_artifacts", VERIFIER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load the packaging artifact verifier")
verify_artifacts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_artifacts)


class TestPackagingArtifactPolicy(unittest.TestCase):
    def test_artifact_version_defaults_to_the_authoritative_runtime_source(self):
        self.assertEqual(verify_artifacts.read_source_version(ROOT), "2.1.2")

    def test_metadata_verification_honors_a_supplied_candidate_version(self):
        metadata = MagicMock()
        values = {
            "Name": "Splunk-HEC-AIO",
            "Version": "2.1.3",
            "Summary": (
                "This is a python class file for use with other python scripts to "
                "send events to a Splunk http event collector."
            ),
            "Keywords": "splunk hec aio",
            "Requires-Python": ">3.5",
            "License": "MIT",
        }
        metadata.get.side_effect = values.get
        metadata.get_all.side_effect = lambda key, default=None: {
            "Requires-Dist": [
                "aiohttp",
                "aiohttp-retry",
                'build; extra == "dev"',
                'twine; extra == "dev"',
            ],
            "Provides-Extra": ["dev"],
            "Project-URL": [
                "Documentation, https://github.com/georgestarcher/splunk_hec_aio#readme",
                "Issues, https://github.com/georgestarcher/splunk_hec_aio/issues",
                "Source, https://github.com/georgestarcher/splunk_hec_aio",
            ],
        }.get(key, default)

        self.assertIsNone(
            verify_artifacts.verify_metadata(metadata, "candidate", "2.1.3")
        )

    def test_common_contents_reject_local_generated_and_credential_files(self):
        forbidden = (
            "project/.venv/bin/python",
            "project/.pytest_cache/state",
            "project/splunkresults.json",
            "project/credentials.json",
            "project/client.key",
        )

        for name in forbidden:
            with self.subTest(name=name):
                with self.assertRaisesRegex(SystemExit, "forbidden"):
                    verify_artifacts.verify_common_contents([name], "candidate")

    def test_common_contents_allow_runtime_and_sdist_test_sources(self):
        names = (
            "project/splunk_hec_aio/splunk_hec_aio.py",
            "project/tests/test_v2_public_api.py",
            "project/LICENSE",
        )

        self.assertIsNone(verify_artifacts.verify_common_contents(names, "candidate"))


if __name__ == "__main__":
    unittest.main()
