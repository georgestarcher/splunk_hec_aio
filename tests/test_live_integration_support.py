import importlib.util
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / ".github" / "scripts" / "live_hec_smoke.py"
SPEC = importlib.util.spec_from_file_location("live_hec_smoke", HELPER_PATH)
live_hec_smoke = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = live_hec_smoke
SPEC.loader.exec_module(live_hec_smoke)


def valid_environment():
    return {
        "SPLUNK_HEC_HOST": "splunk.example.com",
        "SPLUNK_HEC_TOKEN": "hec-token",
        "SPLUNK_HEC_PORT": "443",
        "SPLUNK_HEC_INDEX": "ci_index",
        "SPLUNK_HEC_SOURCE": "github-actions",
        "SPLUNK_HEC_SOURCETYPE": "splunk_hec_aio_ci",
        "SPLUNK_HEC_TEST_ID": "gha-123-1-abc",
        "SPLUNKBASEURL": "https://splunk.example.com:8089",
        "SPLUNKTOKEN": "search-token",
        "SPLUNKAPP": "search",
        "SPLUNKTLSVERIFY": "true",
        "SPLUNKTIMEOUT": "60",
        "GITHUB_REPOSITORY": "owner/repository",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": "0123456789abcdef",
    }


class TestLiveHecSmokeHelper(unittest.TestCase):
    def test_helper_is_executable_from_the_repository_root(self):
        completed = subprocess.run(
            [sys.executable, str(HELPER_PATH), "--help"],
            cwd=str(ROOT),
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("render-query", completed.stdout)

    def test_preflight_accepts_separate_least_privilege_credentials(self):
        self.assertIsNone(live_hec_smoke.validate_preflight(valid_environment()))

    def test_preflight_rejects_reused_ingest_and_search_token(self):
        environment = valid_environment()
        environment["SPLUNKTOKEN"] = environment["SPLUNK_HEC_TOKEN"]

        with self.assertRaisesRegex(
            live_hec_smoke.SmokeTestError, "tokens must be different"
        ):
            live_hec_smoke.validate_preflight(environment)

    def test_preflight_requires_verified_tls_and_https_search_origin(self):
        environment = valid_environment()
        environment["SPLUNKTLSVERIFY"] = "false"
        with self.assertRaisesRegex(live_hec_smoke.SmokeTestError, "must be true"):
            live_hec_smoke.validate_preflight(environment)

        environment = valid_environment()
        environment["SPLUNKBASEURL"] = "http://splunk.example.com:8089/path"
        with self.assertRaisesRegex(live_hec_smoke.SmokeTestError, "HTTPS origin"):
            live_hec_smoke.validate_preflight(environment)

        environment = valid_environment()
        environment["SPLUNKBASEURL"] = "https://splunk.example.com:invalid"
        with self.assertRaisesRegex(live_hec_smoke.SmokeTestError, "invalid port"):
            live_hec_smoke.validate_preflight(environment)

    def test_render_query_replaces_only_validated_placeholders(self):
        environment = valid_environment()
        template = ROOT / ".github" / "querysplunk" / "hec-smoke.yml"
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "rendered.yml"
            live_hec_smoke.render_query(template, output, environment)
            rendered = output.read_text(encoding="utf-8")

            self.assertIn("index=ci_index", rendered)
            self.assertIn("sourcetype=splunk_hec_aio_ci", rendered)
            self.assertIn('ci_test_id="gha-123-1-abc"', rendered)
            self.assertNotIn("__SPLUNK_", rendered)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

    def test_render_query_rejects_search_injection_characters(self):
        environment = valid_environment()
        environment["SPLUNK_HEC_INDEX"] = "ci_index | delete"
        template = ROOT / ".github" / "querysplunk" / "hec-smoke.yml"
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "rendered.yml"
            with self.assertRaisesRegex(
                live_hec_smoke.SmokeTestError, "unsupported characters"
            ):
                live_hec_smoke.render_query(template, output, environment)

    def test_match_count_accepts_zero_and_positive_aggregate_results(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = Path(temporary_directory) / "results.json"
            for expected in (0, 2):
                result.write_text(
                    json.dumps({"results": [{"matched": str(expected)}]}),
                    encoding="utf-8",
                )
                self.assertEqual(live_hec_smoke.match_count(result), expected)

    def test_match_count_rejects_missing_or_malformed_aggregate_results(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = Path(temporary_directory) / "results.json"
            for payload in (
                {"results": []},
                {"results": [{"matched": "many"}]},
                {"results": [{"matched": True}]},
            ):
                result.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(live_hec_smoke.SmokeTestError):
                    live_hec_smoke.match_count(result)

    def test_send_uses_public_class_without_real_network_access(self):
        environment = valid_environment()
        sender = MagicMock()
        with (
            patch.object(
                live_hec_smoke, "SplunkHecAio", return_value=sender
            ) as sender_class,
            patch.object(live_hec_smoke.time, "time", return_value=1.25),
        ):
            live_hec_smoke.send_event(environment)

        sender_class.assert_called_once_with("splunk.example.com", "hec-token")
        sender.set_port.assert_called_once_with(443)
        sender.set_verify_tls.assert_called_once_with(True)
        sender.set_index.assert_called_once_with("ci_index")
        sender.set_source.assert_called_once_with("github-actions")
        sender.set_sourcetype.assert_called_once_with("splunk_hec_aio_ci")
        payload = sender.post_data.call_args.args[0]
        self.assertEqual(payload["time"], "1.25")
        self.assertEqual(payload["event"]["ci_test_id"], "gha-123-1-abc")
        self.assertEqual(payload["event"]["repository"], "owner/repository")
        sender.flush.assert_called_once_with()


class TestLiveIntegrationPolicy(unittest.TestCase):
    def test_workflow_is_manual_protected_and_action_references_are_pinned(self):
        workflow = (ROOT / ".github" / "workflows" / "live-integration.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("  workflow_dispatch:", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotIn("\n  pull_request:", workflow)
        self.assertIn("environment: SPLUNK_INTEGRATION", workflow)
        self.assertIn("deadline_seconds=80", workflow)
        self.assertIn(
            "aac64cf0400a16ac76d2f2e3349d5e093872ba87b20a30bef87b34847532607d",
            workflow,
        )
        for line in workflow.splitlines():
            if "uses: actions/" in line:
                reference = line.split("@", 1)[1].split()[0]
                self.assertRegex(reference, r"^[0-9a-f]{40}$")

    def test_query_template_has_explicit_bounds_and_zero_match_aggregate(self):
        query = (ROOT / ".github" / "querysplunk" / "hec-smoke.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn('earliest_time: "-10m"', query)
        self.assertIn('latest_time: "now"', query)
        self.assertIn("| stats count as matched", query)
        self.assertIn("allow_index_wildcard: false", query)


if __name__ == "__main__":
    unittest.main()
