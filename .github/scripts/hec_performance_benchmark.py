#!/usr/bin/env python3
"""Bounded helpers for the protected Splunk Cloud HEC benchmark."""

import argparse
import asyncio
import json
import logging
import os
import re
import stat
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
for import_path in (REPOSITORY_ROOT, SCRIPT_DIRECTORY):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from live_hec_smoke import (  # noqa: E402
    SmokeTestError,
    load_hec_config,
    validate_preflight,
)

from splunk_hec_aio.splunk_hec_aio import (  # noqa: E402
    HecBatchDeliveryError,
    HecDeliveryResult,
    SplunkHecAio,
)

ALLOWED_EVENT_COUNTS = (100, 1000, 5000, 10000)
ALLOWED_MAX_BATCH_BYTES = (64000, 256000, 512000, 800000)
ALLOWED_CONCURRENCY = (1, 5, 10, 20)
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
QUERY_PLACEHOLDERS = {
    "__SPLUNK_HEC_INDEX__": "SPLUNK_HEC_INDEX",
    "__SPLUNK_HEC_SOURCETYPE__": "SPLUNK_HEC_SOURCETYPE",
    "__SPLUNK_HEC_BENCHMARK_ID__": "SPLUNK_HEC_TEST_ID",
}


class BenchmarkError(ValueError):
    """A safe-to-report benchmark configuration, delivery, or result error."""


@dataclass(frozen=True)
class BenchmarkSettings:
    event_count: int
    max_batch_bytes: int
    concurrency: int


@dataclass(frozen=True)
class BenchmarkSearchMetrics:
    verified: bool
    event_count: int
    distinct_sequence_count: int
    minimum_sequence: int
    maximum_sequence: int
    observed_expected_count: int


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value or value == "UNCONFIGURED":
        raise BenchmarkError("{} is not configured".format(name))
    return value


def _allowlisted_integer(
    environ: Mapping[str, str], name: str, allowed_values: Sequence[int]
) -> int:
    value = _required(environ, name)
    if value not in {str(candidate) for candidate in allowed_values}:
        allowed = ", ".join(str(candidate) for candidate in allowed_values)
        raise BenchmarkError("{} must be one of: {}".format(name, allowed))
    return int(value)


def _safe_identifier(environ: Mapping[str, str], name: str) -> str:
    value = _required(environ, name)
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise BenchmarkError("{} contains unsupported characters".format(name))
    return value


def load_benchmark_settings(environ: Mapping[str, str]) -> BenchmarkSettings:
    """Load only explicit, allowlisted benchmark controls."""

    return BenchmarkSettings(
        event_count=_allowlisted_integer(
            environ,
            "SPLUNK_HEC_BENCHMARK_EVENT_COUNT",
            ALLOWED_EVENT_COUNTS,
        ),
        max_batch_bytes=_allowlisted_integer(
            environ,
            "SPLUNK_HEC_BENCHMARK_MAX_BATCH_BYTES",
            ALLOWED_MAX_BATCH_BYTES,
        ),
        concurrency=_allowlisted_integer(
            environ,
            "SPLUNK_HEC_BENCHMARK_CONCURRENCY",
            ALLOWED_CONCURRENCY,
        ),
    )


def validate_benchmark_preflight(
    environ: Mapping[str, str],
) -> BenchmarkSettings:
    """Validate protected credentials and bounded benchmark controls."""

    validate_preflight(environ)
    return load_benchmark_settings(environ)


def render_benchmark_query(
    template_path: Path,
    output_path: Path,
    environ: Mapping[str, str],
) -> None:
    """Render a bounded aggregate query without loading live credentials."""

    settings = load_benchmark_settings(environ)
    replacements = {
        placeholder: _safe_identifier(environ, variable)
        for placeholder, variable in QUERY_PLACEHOLDERS.items()
    }
    replacements["__SPLUNK_HEC_EXPECTED_COUNT__"] = str(settings.event_count)

    rendered = template_path.read_text(encoding="utf-8")
    for placeholder, replacement in replacements.items():
        if rendered.count(placeholder) != 1:
            raise BenchmarkError(
                "query template must contain {} exactly once".format(placeholder)
            )
        rendered = rendered.replace(placeholder, replacement)
    if "__SPLUNK_HEC_" in rendered:
        raise BenchmarkError("query template contains an unresolved placeholder")
    output_path.write_text(rendered, encoding="utf-8")
    output_path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def build_benchmark_event(
    test_id: str,
    sequence: int,
    expected_count: int,
    environ: Mapping[str, str],
    timestamp: float,
) -> dict[str, Any]:
    """Build one fixed-shape synthetic HEC event."""

    return {
        "time": "{:.3f}".format(timestamp),
        "event": {
            "ci_benchmark_id": test_id,
            "benchmark_sequence": sequence,
            "benchmark_expected_count": expected_count,
            "benchmark_mode": "strict_async",
            "repository": environ.get("GITHUB_REPOSITORY", ""),
            "run_id": environ.get("GITHUB_RUN_ID", ""),
            "run_attempt": environ.get("GITHUB_RUN_ATTEMPT", ""),
            "commit": environ.get("GITHUB_SHA", ""),
            "message": "splunk_hec_aio protected performance benchmark",
        },
    }


def _approximate_wire_size(
    payload: Mapping[str, Any], index: str, source: str, sourcetype: str
) -> int:
    measured_payload = dict(payload)
    measured_payload.update(
        {
            "index": index,
            "source": source,
            "sourcetype": sourcetype,
        }
    )
    return len(json.dumps(measured_payload, default=str).encode("utf-8"))


def _peak_rss_kib() -> Optional[int]:
    try:
        import resource
    except ImportError:  # pragma: no cover - unavailable on Windows.
        return None

    peak_value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if peak_value is None:  # pragma: no cover - defensive platform stub case.
        return None
    peak = int(peak_value)
    if sys.platform == "darwin":
        return peak // 1024
    return peak


def _strict_failure_summary(error: HecBatchDeliveryError) -> BenchmarkError:
    retryable_failures = sum(
        1 for failure in error.failures if getattr(failure, "retryable", False)
    )
    return BenchmarkError(
        "strict delivery failed: accepted_batches={} failed_batches={} "
        "retryable_failures={}".format(
            len(error.results),
            len(error.failures),
            retryable_failures,
        )
    )


async def execute_benchmark(
    environ: Mapping[str, str], settings: BenchmarkSettings
) -> dict[str, Any]:
    """Send a bounded synthetic event set through the public strict async API."""

    config = load_hec_config(environ)
    logging.basicConfig(level=logging.ERROR)
    sender = SplunkHecAio(config.host, config.token)
    sender.log.setLevel(logging.ERROR)
    sender.set_port(config.port)
    sender.set_verify_tls(True)
    sender.set_index(config.index)
    sender.set_source(config.source)
    sender.set_sourcetype(config.sourcetype)
    sender.set_post_max_byte_size(settings.max_batch_bytes)
    sender.set_concurrent_post_limit(settings.concurrency)

    accepted_results: list[HecDeliveryResult] = []
    approximate_wire_bytes = 0
    sender_started = time.perf_counter()
    try:
        for sequence in range(settings.event_count):
            payload = build_benchmark_event(
                config.test_id,
                sequence,
                settings.event_count,
                environ,
                time.time(),
            )
            approximate_wire_bytes += _approximate_wire_size(
                payload,
                config.index,
                config.source,
                config.sourcetype,
            )
            accepted_results.extend(await sender.post_data_strict_async(payload))
        queue_and_auto_delivery_seconds = time.perf_counter() - sender_started

        flush_started = time.perf_counter()
        accepted_results.extend(await sender.flush_strict_async())
        final_flush_seconds = time.perf_counter() - flush_started
    except HecBatchDeliveryError as error:
        raise _strict_failure_summary(error) from error

    total_sender_seconds = time.perf_counter() - sender_started
    accepted_events = sum(result.event_count for result in accepted_results)
    if any(not result.accepted for result in accepted_results):
        raise BenchmarkError("strict delivery returned an unaccepted batch")
    if accepted_events != settings.event_count:
        raise BenchmarkError(
            "strict delivery accepted {} of {} events".format(
                accepted_events,
                settings.event_count,
            )
        )

    return {
        "mode": "strict_async",
        "event_count": settings.event_count,
        "approximate_wire_bytes": approximate_wire_bytes,
        "max_batch_bytes": settings.max_batch_bytes,
        "concurrency": settings.concurrency,
        "queue_and_auto_delivery_seconds": round(queue_and_auto_delivery_seconds, 6),
        "final_flush_seconds": round(final_flush_seconds, 6),
        "total_sender_seconds": round(total_sender_seconds, 6),
        "events_per_second": round(
            settings.event_count / max(total_sender_seconds, 0.000001), 3
        ),
        "accepted_batches": len(accepted_results),
        "accepted_events": accepted_events,
        "rejected_batches": 0,
        "retryable_failures": 0,
        "peak_rss_kib": _peak_rss_kib(),
    }


def _integer_field(row: Mapping[str, Any], name: str, minimum: int) -> int:
    value = row.get(name)
    if value is None or isinstance(value, bool):
        raise BenchmarkError("querysplunk result has an invalid {}".format(name))
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise BenchmarkError(
            "querysplunk result has an invalid {}".format(name)
        ) from error
    if parsed < minimum:
        raise BenchmarkError("querysplunk result has an invalid {}".format(name))
    return parsed


def read_search_metrics(
    result_path: Path, expected_count: int
) -> BenchmarkSearchMetrics:
    """Read only the committed query's aggregate verification fields."""

    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BenchmarkError("querysplunk result is not valid JSON") from error
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise BenchmarkError("querysplunk result must contain one aggregate row")
    row = results[0]
    if not isinstance(row, dict):
        raise BenchmarkError("querysplunk result must contain one aggregate row")

    reported_verified = _integer_field(row, "verified", 0)
    if reported_verified not in (0, 1):
        raise BenchmarkError("querysplunk result has an invalid verified flag")
    event_count = _integer_field(row, "event_count", 0)
    distinct_sequence_count = _integer_field(row, "distinct_sequence_count", 0)
    minimum_sequence = _integer_field(row, "minimum_sequence", -1)
    maximum_sequence = _integer_field(row, "maximum_sequence", -1)
    observed_expected_count = _integer_field(row, "observed_expected_count", -1)
    verified = (
        event_count == expected_count
        and distinct_sequence_count == expected_count
        and minimum_sequence == 0
        and maximum_sequence == expected_count - 1
        and observed_expected_count == expected_count
    )
    if reported_verified != int(verified):
        raise BenchmarkError("querysplunk verification flag disagrees with counts")

    return BenchmarkSearchMetrics(
        verified=verified,
        event_count=event_count,
        distinct_sequence_count=distinct_sequence_count,
        minimum_sequence=minimum_sequence,
        maximum_sequence=maximum_sequence,
        observed_expected_count=observed_expected_count,
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _read_metrics(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BenchmarkError("benchmark metrics file is invalid") from error
    if not isinstance(payload, dict):
        raise BenchmarkError("benchmark metrics file is invalid")
    return payload


def write_summary(
    sender_path: Path,
    search_path: Path,
    output_path: Path,
    indexing_lag_seconds: Optional[float],
) -> None:
    """Append sanitized aggregate benchmark metrics to the job summary."""

    sender = _read_metrics(sender_path)
    search = _read_metrics(search_path)
    rows = (
        ("Mode", sender.get("mode")),
        ("Events requested", sender.get("event_count")),
        ("Approximate uncompressed event bytes", sender.get("approximate_wire_bytes")),
        ("Maximum batch bytes", sender.get("max_batch_bytes")),
        ("Concurrency", sender.get("concurrency")),
        (
            "Queue and automatic-delivery seconds",
            sender.get("queue_and_auto_delivery_seconds"),
        ),
        ("Final flush seconds", sender.get("final_flush_seconds")),
        ("Total sender seconds", sender.get("total_sender_seconds")),
        ("Sender events per second", sender.get("events_per_second")),
        ("Accepted batches", sender.get("accepted_batches")),
        ("Accepted events", sender.get("accepted_events")),
        ("Peak RSS KiB", sender.get("peak_rss_kib")),
        ("Searchable event rows", search.get("event_count")),
        ("Distinct sequences", search.get("distinct_sequence_count")),
        ("Minimum sequence", search.get("minimum_sequence")),
        ("Maximum sequence", search.get("maximum_sequence")),
        ("Search indexing lag seconds", indexing_lag_seconds),
    )
    lines = [
        "## Protected HEC performance benchmark",
        "",
        "> This is an environment-specific observation of the configured runner, "
        "network path, event shape, batching, concurrency, and Splunk Cloud tenant. "
        "It is not a Splunk Cloud capacity limit or a library throughput guarantee.",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    lines.extend("| {} | {} |".format(label, value) for label, value in rows)
    with output_path.open("a", encoding="utf-8") as summary:
        summary.write("\n".join(lines) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight", help="validate protected benchmark inputs")
    render = subparsers.add_parser("render-query", help="render the aggregate search")
    render.add_argument("template", type=Path)
    render.add_argument("output", type=Path)
    run = subparsers.add_parser("run", help="send the bounded strict async workload")
    run.add_argument("metrics", type=Path)
    verify = subparsers.add_parser(
        "verify-results", help="verify aggregate querysplunk results"
    )
    verify.add_argument("result", type=Path)
    verify.add_argument("metrics", type=Path)
    summary = subparsers.add_parser("write-summary", help="write sanitized metrics")
    summary.add_argument("sender_metrics", type=Path)
    summary.add_argument("search_metrics", type=Path)
    summary.add_argument("output", type=Path)
    summary.add_argument("--indexing-lag-seconds", type=float)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "preflight":
            validate_benchmark_preflight(os.environ)
            print("Protected benchmark configuration validated.")
        elif args.command == "render-query":
            render_benchmark_query(args.template, args.output, os.environ)
            print("Protected benchmark search configuration rendered.")
        elif args.command == "run":
            settings = load_benchmark_settings(os.environ)
            sender_metrics = asyncio.run(execute_benchmark(os.environ, settings))
            _write_json(args.metrics, sender_metrics)
            print("HEC benchmark send completed; awaiting search verification.")
        elif args.command == "verify-results":
            settings = load_benchmark_settings(os.environ)
            search_metrics = read_search_metrics(args.result, settings.event_count)
            _write_json(args.metrics, asdict(search_metrics))
            if not search_metrics.verified:
                return 2
            print("Exact searchable event and sequence counts verified.")
        elif args.command == "write-summary":
            write_summary(
                args.sender_metrics,
                args.search_metrics,
                args.output,
                args.indexing_lag_seconds,
            )
        else:  # pragma: no cover - argparse enforces the command choices.
            raise BenchmarkError("unsupported command")
    except (BenchmarkError, SmokeTestError) as error:
        print("ERROR: {}".format(error), file=sys.stderr)
        return 1
    except Exception:
        print("ERROR: HEC performance benchmark command failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
