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
QUERY_PATH = ROOT / ".github" / "querysplunk" / "hec-smoke.yml"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "live-integration.yml"
IS_REPOSITORY_CHECKOUT = (ROOT / ".git").exists()
REPOSITORY_ASSETS = (HELPER_PATH, QUERY_PATH, WORKFLOW_PATH)
MISSING_REPOSITORY_ASSETS = [path for path in REPOSITORY_ASSETS if not path.is_file()]

if IS_REPOSITORY_CHECKOUT and MISSING_REPOSITORY_ASSETS:
    missing = ", ".join(
        str(path.relative_to(ROOT)) for path in MISSING_REPOSITORY_ASSETS
    )
    raise RuntimeError("repository live integration assets are missing: " + missing)

HELPER_ASSETS_AVAILABLE = HELPER_PATH.is_file() and QUERY_PATH.is_file()
POLICY_ASSETS_AVAILABLE = WORKFLOW_PATH.is_file() and QUERY_PATH.is_file()

if HELPER_ASSETS_AVAILABLE:
    SPEC = importlib.util.spec_from_file_location("live_hec_smoke", HELPER_PATH)
    if SPEC is None or SPEC.loader is None:
        raise RuntimeError("could not load the live integration helper")
    live_hec_smoke = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = live_hec_smoke
    SPEC.loader.exec_module(live_hec_smoke)
else:
    live_hec_smoke = None


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


@unittest.skipUnless(
    HELPER_ASSETS_AVAILABLE,
    "repository-only live integration helper assets are unavailable",
)
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
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "rendered.yml"
            live_hec_smoke.render_query(QUERY_PATH, output, environment)
            rendered = output.read_text(encoding="utf-8")

            self.assertIn("index=ci_index", rendered)
            self.assertIn("sourcetype=splunk_hec_aio_ci", rendered)
            self.assertIn('ci_test_id="gha-123-1-abc"', rendered)
            self.assertNotIn("__SPLUNK_", rendered)
            if sys.platform != "win32":
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

    def test_render_query_rejects_search_injection_characters(self):
        environment = valid_environment()
        environment["SPLUNK_HEC_INDEX"] = "ci_index | delete"
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "rendered.yml"
            with self.assertRaisesRegex(
                live_hec_smoke.SmokeTestError, "unsupported characters"
            ):
                live_hec_smoke.render_query(QUERY_PATH, output, environment)

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

    def test_send_flushes_one_event_then_three_positioned_batch_events(self):
        environment = valid_environment()
        sender = MagicMock()
        with (
            patch.object(
                live_hec_smoke, "SplunkHecAio", return_value=sender
            ) as sender_class,
            patch.object(live_hec_smoke.time, "time", return_value=1.25),
        ):
            sender.check_connectivity.return_value = True
            live_hec_smoke.send_single_and_batch(environment)

        sender_class.assert_called_once_with("splunk.example.com", "hec-token")
        sender.set_port.assert_called_once_with(443)
        sender.set_verify_tls.assert_called_once_with(True)
        sender.set_index.assert_called_once_with("ci_index")
        sender.set_source.assert_called_once_with("github-actions")
        sender.set_sourcetype.assert_called_once_with("splunk_hec_aio_ci")
        sender.check_connectivity.assert_called_once_with()
        self.assertEqual(sender.post_data.call_count, 4)
        self.assertEqual(sender.flush.call_count, 2)
        payloads = [call.args[0] for call in sender.post_data.call_args_list]
        self.assertEqual([payload["time"] for payload in payloads], ["1.25"] * 4)
        self.assertEqual(
            [payload["event"]["ci_test_id"] for payload in payloads],
            ["gha-123-1-abc"] * 4,
        )
        self.assertEqual(
            [payload["event"]["send_shape"] for payload in payloads],
            ["single", "batch", "batch", "batch"],
        )
        self.assertEqual(
            [payload["event"]["batch_position"] for payload in payloads],
            [1, 1, 2, 3],
        )
        self.assertEqual(
            [payload["event"]["repository"] for payload in payloads],
            ["owner/repository"] * 4,
        )
        self.assertEqual(
            [entry[0] for entry in sender.method_calls[-7:]],
            [
                "check_connectivity",
                "post_data",
                "flush",
                "post_data",
                "post_data",
                "post_data",
                "flush",
            ],
        )

    def test_send_stops_before_delivery_when_hec_is_unhealthy(self):
        environment = valid_environment()
        sender = MagicMock()
        sender.check_connectivity.return_value = False

        with patch.object(live_hec_smoke, "SplunkHecAio", return_value=sender):
            with self.assertRaisesRegex(
                live_hec_smoke.SmokeTestError,
                "HEC health endpoint did not report healthy",
            ):
                live_hec_smoke.send_single_and_batch(environment)

        sender.check_connectivity.assert_called_once_with()
        sender.post_data.assert_not_called()
        sender.flush.assert_not_called()


@unittest.skipUnless(
    POLICY_ASSETS_AVAILABLE,
    "repository-only live integration policy assets are unavailable",
)
class TestLiveIntegrationPolicy(unittest.TestCase):
    def test_workflow_is_manual_protected_and_action_references_are_pinned(self):
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

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

    def test_query_requires_standalone_event_and_three_batch_positions(self):
        query = QUERY_PATH.read_text(encoding="utf-8")

        self.assertIn('earliest_time: "-10m"', query)
        self.assertIn('latest_time: "now"', query)
        self.assertNotIn("  max_count:", query)
        self.assertIn(
            "stats count as event_count dc(batch_position) as position_count",
            query,
        )
        self.assertIn('send_shape="single" AND event_count >= 1', query)
        self.assertIn('send_shape="batch" AND event_count >= 3', query)
        self.assertIn("shape_count = 2 AND all_verified = 1", query)
        self.assertIn("| stats count as matched", query)
        self.assertIn("    - send_shape", query)
        self.assertIn("    - batch_position", query)
        self.assertIn("allow_index_wildcard: false", query)


if __name__ == "__main__":
    unittest.main()
