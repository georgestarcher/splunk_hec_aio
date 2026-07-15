import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "tests" / "packaging" / "verify_artifacts.py"

SPEC = importlib.util.spec_from_file_location("verify_artifacts", VERIFIER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load the packaging artifact verifier")
verify_artifacts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_artifacts)


class TestPackagingArtifactPolicy(unittest.TestCase):
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
