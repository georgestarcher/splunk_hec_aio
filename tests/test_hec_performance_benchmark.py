import asyncio
import importlib.util
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / ".github" / "scripts" / "hec_performance_benchmark.py"
QUERY_PATH = ROOT / ".github" / "querysplunk" / "hec-performance.yml"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "hec-performance.yml"
DOCUMENTATION_PATH = ROOT / "docs" / "performance-benchmark.md"
IS_REPOSITORY_CHECKOUT = (ROOT / ".git").exists()
REPOSITORY_ASSETS = (HELPER_PATH, QUERY_PATH, WORKFLOW_PATH, DOCUMENTATION_PATH)
MISSING_REPOSITORY_ASSETS = [path for path in REPOSITORY_ASSETS if not path.is_file()]

if IS_REPOSITORY_CHECKOUT and MISSING_REPOSITORY_ASSETS:
    missing = ", ".join(
        str(path.relative_to(ROOT)) for path in MISSING_REPOSITORY_ASSETS
    )
    raise RuntimeError("repository benchmark assets are missing: " + missing)

HELPER_ASSETS_AVAILABLE = HELPER_PATH.is_file() and QUERY_PATH.is_file()
POLICY_ASSETS_AVAILABLE = WORKFLOW_PATH.is_file() and QUERY_PATH.is_file()

if HELPER_ASSETS_AVAILABLE:
    SPEC = importlib.util.spec_from_file_location(
        "hec_performance_benchmark", HELPER_PATH
    )
    if SPEC is None or SPEC.loader is None:
        raise RuntimeError("could not load the performance benchmark helper")
    benchmark = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = benchmark
    SPEC.loader.exec_module(benchmark)
else:
    benchmark = None


def valid_environment():
    return {
        "SPLUNK_HEC_HOST": "splunk.example.com",
        "SPLUNK_HEC_TOKEN": "hec-token",
        "SPLUNK_HEC_PORT": "443",
        "SPLUNK_HEC_INDEX": "ci_index",
        "SPLUNK_HEC_SOURCE": "github-actions-benchmark",
        "SPLUNK_HEC_SOURCETYPE": "splunk_hec_aio_benchmark",
        "SPLUNK_HEC_TEST_ID": "benchmark-123-1-abc",
        "SPLUNK_HEC_BENCHMARK_EVENT_COUNT": "100",
        "SPLUNK_HEC_BENCHMARK_MAX_BATCH_BYTES": "512000",
        "SPLUNK_HEC_BENCHMARK_CONCURRENCY": "10",
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


def aggregate_result(
    *,
    verified,
    event_count,
    distinct_sequence_count,
    minimum_sequence,
    maximum_sequence,
    observed_expected_count,
):
    return {
        "results": [
            {
                "verified": str(verified),
                "event_count": str(event_count),
                "distinct_sequence_count": str(distinct_sequence_count),
                "minimum_sequence": str(minimum_sequence),
                "maximum_sequence": str(maximum_sequence),
                "observed_expected_count": str(observed_expected_count),
            }
        ]
    }


@unittest.skipUnless(
    HELPER_ASSETS_AVAILABLE,
    "repository-only performance benchmark assets are unavailable",
)
class TestHecPerformanceBenchmarkHelper(unittest.TestCase):
    def test_helper_is_executable_from_the_repository_root(self):
        completed = subprocess.run(
            [sys.executable, str(HELPER_PATH), "--help"],
            cwd=str(ROOT),
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("verify-results", completed.stdout)
        self.assertIn("write-summary", completed.stdout)

    def test_preflight_accepts_only_allowlisted_benchmark_controls(self):
        settings = benchmark.validate_benchmark_preflight(valid_environment())

        self.assertEqual(settings.event_count, 100)
        self.assertEqual(settings.max_batch_bytes, 512000)
        self.assertEqual(settings.concurrency, 10)

        for variable, invalid_value in (
            ("SPLUNK_HEC_BENCHMARK_EVENT_COUNT", "10001"),
            ("SPLUNK_HEC_BENCHMARK_MAX_BATCH_BYTES", "512001"),
            ("SPLUNK_HEC_BENCHMARK_CONCURRENCY", "21"),
        ):
            with self.subTest(variable=variable):
                environment = valid_environment()
                environment[variable] = invalid_value
                with self.assertRaisesRegex(benchmark.BenchmarkError, "must be one of"):
                    benchmark.validate_benchmark_preflight(environment)

    def test_render_query_uses_validated_identifiers_and_exact_count(self):
        environment = valid_environment()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "rendered.yml"
            benchmark.render_benchmark_query(QUERY_PATH, output, environment)
            rendered = output.read_text(encoding="utf-8")

            self.assertIn("index=ci_index", rendered)
            self.assertIn("sourcetype=splunk_hec_aio_benchmark", rendered)
            self.assertIn('ci_benchmark_id="benchmark-123-1-abc"', rendered)
            self.assertIn("expected_count=100", rendered)
            self.assertNotIn("__SPLUNK_HEC_", rendered)
            if sys.platform != "win32":
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

    def test_render_query_rejects_search_injection_characters(self):
        environment = valid_environment()
        environment["SPLUNK_HEC_TEST_ID"] = "benchmark | delete"
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "rendered.yml"
            with self.assertRaisesRegex(
                benchmark.BenchmarkError, "unsupported characters"
            ):
                benchmark.render_benchmark_query(QUERY_PATH, output, environment)

    def test_event_generation_is_fixed_shape_and_contains_no_token(self):
        environment = valid_environment()
        payload = benchmark.build_benchmark_event(
            "benchmark-123-1-abc", 7, 100, environment, 1.25
        )

        self.assertEqual(payload["time"], "1.250")
        self.assertEqual(payload["event"]["benchmark_sequence"], 7)
        self.assertEqual(payload["event"]["benchmark_expected_count"], 100)
        self.assertEqual(payload["event"]["benchmark_mode"], "strict_async")
        self.assertNotIn("hec-token", json.dumps(payload))
        self.assertNotIn("search-token", json.dumps(payload))

    def test_exact_search_metrics_detect_missing_and_duplicate_sequences(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = Path(temporary_directory) / "results.json"
            result.write_text(
                json.dumps(
                    aggregate_result(
                        verified=1,
                        event_count=100,
                        distinct_sequence_count=100,
                        minimum_sequence=0,
                        maximum_sequence=99,
                        observed_expected_count=100,
                    )
                ),
                encoding="utf-8",
            )
            metrics = benchmark.read_search_metrics(result, 100)
            self.assertTrue(metrics.verified)

            result.write_text(
                json.dumps(
                    aggregate_result(
                        verified=0,
                        event_count=100,
                        distinct_sequence_count=99,
                        minimum_sequence=0,
                        maximum_sequence=99,
                        observed_expected_count=100,
                    )
                ),
                encoding="utf-8",
            )
            metrics = benchmark.read_search_metrics(result, 100)
            self.assertFalse(metrics.verified)

    def test_search_metrics_reject_a_false_verified_flag(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = Path(temporary_directory) / "results.json"
            result.write_text(
                json.dumps(
                    aggregate_result(
                        verified=1,
                        event_count=99,
                        distinct_sequence_count=99,
                        minimum_sequence=0,
                        maximum_sequence=98,
                        observed_expected_count=100,
                    )
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(benchmark.BenchmarkError, "flag disagrees"):
                benchmark.read_search_metrics(result, 100)

    def test_execute_benchmark_uses_strict_async_without_health_dependency(self):
        environment = valid_environment()
        settings = benchmark.load_benchmark_settings(environment)
        sender = MagicMock()
        sender.post_data_strict_async = AsyncMock(return_value=())
        sender.flush_strict_async = AsyncMock(
            return_value=(
                benchmark.HecDeliveryResult(
                    batch_index=0,
                    event_count=100,
                    http_status=200,
                    http_reason="OK",
                    hec_code=0,
                    hec_text="Success",
                    invalid_event_number=None,
                    accepted=True,
                    retryable=False,
                ),
            )
        )

        with (
            patch.object(benchmark, "SplunkHecAio", return_value=sender),
            patch.object(benchmark.time, "time", return_value=1.25),
            patch.object(
                benchmark.time,
                "perf_counter",
                side_effect=(10.0, 12.0, 12.0, 13.0, 13.5),
            ),
            patch.object(benchmark, "_peak_rss_kib", return_value=12345),
        ):
            metrics = asyncio.run(benchmark.execute_benchmark(environment, settings))

        sender.set_post_max_byte_size.assert_called_once_with(512000)
        sender.set_concurrent_post_limit.assert_called_once_with(10)
        self.assertEqual(sender.post_data_strict_async.await_count, 100)
        sender.flush_strict_async.assert_awaited_once_with()
        sender.check_connectivity.assert_not_called()
        self.assertEqual(metrics["accepted_batches"], 1)
        self.assertEqual(metrics["accepted_events"], 100)
        self.assertEqual(metrics["queue_and_auto_delivery_seconds"], 2.0)
        self.assertEqual(metrics["final_flush_seconds"], 1.0)
        self.assertEqual(metrics["total_sender_seconds"], 3.5)
        self.assertGreater(metrics["approximate_wire_bytes"], 0)

    def test_execute_benchmark_reports_only_sanitized_failure_counts(self):
        environment = valid_environment()
        settings = benchmark.load_benchmark_settings(environment)
        sender = MagicMock()
        failure = MagicMock(retryable=True)
        sender.post_data_strict_async = AsyncMock(
            side_effect=benchmark.HecBatchDeliveryError((), (failure,))
        )

        with patch.object(benchmark, "SplunkHecAio", return_value=sender):
            with self.assertRaisesRegex(
                benchmark.BenchmarkError,
                "accepted_batches=0 failed_batches=1 retryable_failures=1",
            ) as raised:
                asyncio.run(benchmark.execute_benchmark(environment, settings))

        self.assertNotIn("hec-token", str(raised.exception))
        self.assertNotIn("splunk.example.com", str(raised.exception))

    def test_summary_contains_only_aggregate_metrics_and_caveat(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            sender = directory / "sender.json"
            search = directory / "search.json"
            summary = directory / "summary.md"
            benchmark._write_json(
                sender,
                {
                    "mode": "strict_async",
                    "event_count": 100,
                    "approximate_wire_bytes": 25000,
                    "max_batch_bytes": 512000,
                    "concurrency": 10,
                    "queue_and_auto_delivery_seconds": 0.1,
                    "final_flush_seconds": 0.2,
                    "total_sender_seconds": 0.3,
                    "events_per_second": 333.333,
                    "accepted_batches": 1,
                    "accepted_events": 100,
                    "peak_rss_kib": 12345,
                },
            )
            benchmark._write_json(
                search,
                {
                    "verified": True,
                    "event_count": 100,
                    "distinct_sequence_count": 100,
                    "minimum_sequence": 0,
                    "maximum_sequence": 99,
                    "observed_expected_count": 100,
                },
            )
            benchmark.write_summary(sender, search, summary, 12.0)
            rendered = summary.read_text(encoding="utf-8")

        self.assertIn("environment-specific observation", rendered)
        self.assertIn("| Searchable event rows | 100 |", rendered)
        self.assertNotIn("splunk.example.com", rendered)
        self.assertNotIn("benchmark-123", rendered)


@unittest.skipUnless(
    POLICY_ASSETS_AVAILABLE,
    "repository-only performance benchmark policy assets are unavailable",
)
class TestHecPerformanceBenchmarkPolicy(unittest.TestCase):
    def test_workflow_is_manual_protected_bounded_and_pinned(self):
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("  workflow_dispatch:", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotIn("\n  pull_request:", workflow)
        self.assertNotIn("\n  schedule:", workflow)
        self.assertIn("environment: SPLUNK_INTEGRATION", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        for event_count in (100, 1000, 5000, 10000):
            self.assertIn('          - "{}"'.format(event_count), workflow)
        self.assertIn("deadline_seconds=180", workflow)
        self.assertIn("hec_performance_benchmark.py run", workflow)
        self.assertNotIn("check_connectivity", workflow)
        self.assertIn(
            "aac64cf0400a16ac76d2f2e3349d5e093872ba87b20a30bef87b34847532607d",
            workflow,
        )
        for line in workflow.splitlines():
            if "uses: actions/" in line:
                reference = line.split("@", 1)[1].split()[0]
                self.assertRegex(reference, r"^[0-9a-f]{40}$")

    def test_query_is_bounded_read_only_and_requires_exact_sequence_metrics(self):
        query = QUERY_PATH.read_text(encoding="utf-8")

        self.assertIn('schema_version: "1"', query)
        self.assertIn('earliest_time: "-30m"', query)
        self.assertIn('latest_time: "now"', query)
        self.assertIn("max_count: 20000", query)
        self.assertIn("maximum_rows: 1", query)
        self.assertIn("event_count=expected_count", query)
        self.assertIn("distinct_sequence_count=expected_count", query)
        self.assertIn("maximum_sequence=expected_count-1", query)
        self.assertIn("allow_index_wildcard: false", query)
        self.assertNotIn("index=*", query)
        for modifying_command in ("| collect", "| delete", "| outputlookup"):
            self.assertNotIn(modifying_command, query)

    def test_documentation_requires_gradual_stages_and_conservative_results(self):
        documentation = DOCUMENTATION_PATH.read_text(encoding="utf-8")
        normalized = " ".join(documentation.split())

        self.assertIn("Run stages in order", documentation)
        self.assertIn("stop after any", normalized)
        self.assertIn("optionally `10000`", documentation)
        self.assertIn("never calls the HEC health endpoint", normalized)
        self.assertIn("environment-specific observation", normalized)
        self.assertIn("not establish a Splunk Cloud service limit", normalized)
        self.assertIn("raw Splunk results", normalized)


if __name__ == "__main__":
    unittest.main()
