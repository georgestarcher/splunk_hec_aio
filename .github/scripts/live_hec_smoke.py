#!/usr/bin/env python3
"""Safe helpers for the protected live Splunk integration workflow."""

import argparse
import json
import logging
import os
import re
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence
from urllib.parse import urlsplit

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from splunk_hec_aio.splunk_hec_aio import SplunkHecAio  # noqa: E402

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
SOURCE_PATTERN = re.compile(r"^[A-Za-z0-9_.:/-]+$")
PLACEHOLDERS = {
    "__SPLUNK_HEC_INDEX__": "SPLUNK_HEC_INDEX",
    "__SPLUNK_HEC_SOURCETYPE__": "SPLUNK_HEC_SOURCETYPE",
    "__SPLUNK_HEC_TEST_ID__": "SPLUNK_HEC_TEST_ID",
}


class SmokeTestError(ValueError):
    """A safe-to-report live smoke test configuration or result error."""


@dataclass(frozen=True)
class HecConfig:
    host: str
    token: str
    port: int
    index: str
    source: str
    sourcetype: str
    test_id: str


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value or value == "UNCONFIGURED":
        raise SmokeTestError("{} is not configured".format(name))
    return value


def _safe_identifier(environ: Mapping[str, str], name: str) -> str:
    value = _required(environ, name)
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise SmokeTestError("{} contains unsupported characters".format(name))
    return value


def _safe_source(environ: Mapping[str, str]) -> str:
    value = _required(environ, "SPLUNK_HEC_SOURCE")
    if not SOURCE_PATTERN.fullmatch(value):
        raise SmokeTestError("SPLUNK_HEC_SOURCE contains unsupported characters")
    return value


def _hostname(environ: Mapping[str, str]) -> str:
    host = _required(environ, "SPLUNK_HEC_HOST")
    if "://" in host or "/" in host or ":" in host or len(host) > 253:
        raise SmokeTestError(
            "SPLUNK_HEC_HOST must be a hostname without a scheme or port"
        )
    labels = host.split(".")
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not re.fullmatch(r"[A-Za-z0-9-]+", label)
        for label in labels
    ):
        raise SmokeTestError("SPLUNK_HEC_HOST is not a valid hostname")
    return host


def _port(environ: Mapping[str, str]) -> int:
    value = _required(environ, "SPLUNK_HEC_PORT")
    try:
        port = int(value)
    except ValueError as error:
        raise SmokeTestError("SPLUNK_HEC_PORT must be an integer") from error
    if not 1 <= port <= 65535:
        raise SmokeTestError("SPLUNK_HEC_PORT must be between 1 and 65535")
    return port


def _require_tls(environ: Mapping[str, str]) -> None:
    if _required(environ, "SPLUNKTLSVERIFY").lower() != "true":
        raise SmokeTestError("SPLUNKTLSVERIFY must be true for live CI")


def _search_url(environ: Mapping[str, str]) -> str:
    base_url = _required(environ, "SPLUNKBASEURL")
    parsed = urlsplit(base_url)
    try:
        parsed_port = parsed.port
    except ValueError as error:
        raise SmokeTestError("SPLUNKBASEURL has an invalid port") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or (parsed_port is not None and not 1 <= parsed_port <= 65535)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise SmokeTestError(
            "SPLUNKBASEURL must be an HTTPS origin without credentials"
        )
    return base_url


def load_hec_config(environ: Mapping[str, str]) -> HecConfig:
    """Load and validate only the values required by the HEC sender."""

    _require_tls(environ)
    return HecConfig(
        host=_hostname(environ),
        token=_required(environ, "SPLUNK_HEC_TOKEN"),
        port=_port(environ),
        index=_safe_identifier(environ, "SPLUNK_HEC_INDEX"),
        source=_safe_source(environ),
        sourcetype=_safe_identifier(environ, "SPLUNK_HEC_SOURCETYPE"),
        test_id=_safe_identifier(environ, "SPLUNK_HEC_TEST_ID"),
    )


def validate_preflight(environ: Mapping[str, str]) -> None:
    """Validate both live endpoints without printing their values."""

    hec = load_hec_config(environ)
    search_token = _required(environ, "SPLUNKTOKEN")
    _search_url(environ)
    _safe_identifier(environ, "SPLUNKAPP")
    timeout = _required(environ, "SPLUNKTIMEOUT")
    try:
        timeout_seconds = int(timeout)
    except ValueError as error:
        raise SmokeTestError("SPLUNKTIMEOUT must be an integer") from error
    if not 1 <= timeout_seconds <= 300:
        raise SmokeTestError("SPLUNKTIMEOUT must be between 1 and 300 seconds")
    if hec.token == search_token:
        raise SmokeTestError("HEC ingest and Splunk search tokens must be different")


def render_query(
    template_path: Path, output_path: Path, environ: Mapping[str, str]
) -> None:
    """Render the committed search template using tightly validated identifiers."""

    replacements = {
        placeholder: _safe_identifier(environ, variable)
        for placeholder, variable in PLACEHOLDERS.items()
    }
    rendered = template_path.read_text(encoding="utf-8")
    for placeholder, replacement in replacements.items():
        if rendered.count(placeholder) != 1:
            raise SmokeTestError(
                "query template must contain {} exactly once".format(placeholder)
            )
        rendered = rendered.replace(placeholder, replacement)
    if "__SPLUNK_" in rendered:
        raise SmokeTestError("query template contains an unresolved placeholder")
    output_path.write_text(rendered, encoding="utf-8")
    output_path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def match_count(result_path: Path) -> int:
    """Return querysplunk's aggregate match count without echoing raw results."""

    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SmokeTestError("querysplunk result is not valid JSON") from error
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise SmokeTestError("querysplunk result must contain one aggregate row")
    value = results[0].get("matched") if isinstance(results[0], dict) else None
    if isinstance(value, bool):
        raise SmokeTestError("querysplunk result has an invalid matched count")
    if value is None:
        raise SmokeTestError("querysplunk result has an invalid matched count")
    try:
        count = int(value)
    except (TypeError, ValueError) as error:
        raise SmokeTestError(
            "querysplunk result has an invalid matched count"
        ) from error
    if count < 0:
        raise SmokeTestError("querysplunk result has an invalid matched count")
    return count


def send_single_and_batch(environ: Mapping[str, str]) -> None:
    """Send one standalone event and one three-event batch through the public class."""

    config = load_hec_config(environ)
    logging.basicConfig(level=logging.ERROR)
    sender = SplunkHecAio(config.host, config.token)
    sender.log.setLevel(logging.ERROR)
    sender.set_port(config.port)
    sender.set_verify_tls(True)
    sender.set_index(config.index)
    sender.set_source(config.source)
    sender.set_sourcetype(config.sourcetype)

    common_event = {
        "ci_test_id": config.test_id,
        "repository": environ.get("GITHUB_REPOSITORY", ""),
        "run_id": environ.get("GITHUB_RUN_ID", ""),
        "run_attempt": environ.get("GITHUB_RUN_ATTEMPT", ""),
        "commit": environ.get("GITHUB_SHA", ""),
    }
    single_event = {
        **common_event,
        "send_shape": "single",
        "batch_position": 1,
        "message": "splunk_hec_aio live integration single-event test",
    }
    sender.post_data({"time": str(round(time.time(), 3)), "event": single_event})
    sender.flush()

    for batch_position in range(1, 4):
        event = {
            **common_event,
            "send_shape": "batch",
            "batch_position": batch_position,
            "message": "splunk_hec_aio live integration batch test",
        }
        sender.post_data({"time": str(round(time.time(), 3)), "event": event})
    sender.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight", help="validate protected environment values")
    subparsers.add_parser("send", help="send live single-event and batch checks")
    render = subparsers.add_parser("render-query", help="render the search YAML")
    render.add_argument("template", type=Path)
    render.add_argument("output", type=Path)
    count = subparsers.add_parser("match-count", help="read the aggregate result count")
    count.add_argument("result", type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "preflight":
            validate_preflight(os.environ)
            print("Live integration configuration validated.")
        elif args.command == "send":
            send_single_and_batch(os.environ)
            print("HEC single and batch sends completed; awaiting verification.")
        elif args.command == "render-query":
            render_query(args.template, args.output, os.environ)
            print("Live search configuration rendered.")
        elif args.command == "match-count":
            print(match_count(args.result))
        else:  # pragma: no cover - argparse enforces the command choices.
            raise SmokeTestError("unsupported command")
    except SmokeTestError as error:
        print("ERROR: {}".format(error), file=sys.stderr)
        return 1
    except Exception:
        print("ERROR: live HEC smoke command failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
