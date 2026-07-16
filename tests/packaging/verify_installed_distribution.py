"""Verify an installed artifact from a working directory outside the checkout."""

import argparse
import ast
import os
import re
from importlib import metadata, util
from pathlib import Path

import splunk_hec_aio.splunk_hec_aio as module
from splunk_hec_aio.splunk_hec_aio import SplunkHecAio


def normalized_requirement(requirement):
    name = re.split(r"[<=>!~; [(]", requirement, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def read_source_version(checkout: Path) -> str:
    path = checkout / "splunk_hec_aio" / "splunk_hec_aio.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    versions = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        ):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            versions.append(node.value.value)
    if len(versions) != 1:
        raise SystemExit("runtime module must define exactly one literal __version__")
    return versions[0]


def parse_arguments(arguments=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version")
    return parser.parse_args(arguments)


def main(arguments=None):
    options = parse_arguments(arguments)
    distribution = metadata.distribution("Splunk-HEC-AIO")
    package_path = Path(module.__file__).resolve()
    checkout = Path(os.environ["SOURCE_CHECKOUT"]).resolve()
    expected_version = options.expected_version or read_source_version(checkout)

    try:
        package_path.relative_to(checkout)
    except ValueError:
        pass
    else:
        raise SystemExit("verification imported the source checkout, not the artifact")

    if module.__version__ != expected_version:
        raise SystemExit("installed module version does not match the candidate")
    if SplunkHecAio.__module__ != "splunk_hec_aio.splunk_hec_aio":
        raise SystemExit("documented nested import identity changed")
    if distribution.metadata["Name"] != "Splunk-HEC-AIO":
        raise SystemExit("installed distribution name changed")
    if distribution.version != expected_version:
        raise SystemExit("installed distribution version does not match the candidate")
    expected_summary = (
        "This is a python class file for use with other python scripts to send "
        "events to a Splunk http event collector."
    )
    if distribution.metadata["Summary"] != expected_summary:
        raise SystemExit("installed distribution summary changed")
    if distribution.metadata["Keywords"] != "splunk hec aio":
        raise SystemExit("installed distribution keywords changed")
    if distribution.metadata["Requires-Python"] != ">=3.9":
        raise SystemExit("installed Requires-Python changed")
    expected_classifiers = {
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: System :: Logging",
    }
    if set(distribution.metadata.get_all("Classifier", [])) != expected_classifiers:
        raise SystemExit("installed classifiers changed")

    runtime_requirements = {
        normalized_requirement(value)
        for value in distribution.requires or ()
        if "extra ==" not in value
    }
    if runtime_requirements != {"aiohttp", "aiohttp-retry"}:
        raise SystemExit("installed runtime requirements changed")
    if set(distribution.metadata.get_all("Provides-Extra", [])) != {"dev"}:
        raise SystemExit("installed development extra changed")
    if util.find_spec("splunk_hec_aio.splunk_hec_aio_test") is not None:
        raise SystemExit("legacy test module was installed")

    installed_paths = {str(path) for path in distribution.files or ()}
    if any(path.startswith("tests/") for path in installed_paths):
        raise SystemExit("tests were installed by the artifact")

    print("Verified installed distribution from {}.".format(package_path))


if __name__ == "__main__":
    main()
