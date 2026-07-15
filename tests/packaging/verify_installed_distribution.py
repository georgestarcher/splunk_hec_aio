"""Verify an installed artifact from a working directory outside the checkout."""

import os
import re
from importlib import metadata, util
from pathlib import Path

import splunk_hec_aio.splunk_hec_aio as module
from splunk_hec_aio.splunk_hec_aio import SplunkHecAio


def normalized_requirement(requirement):
    name = re.split(r"[<=>!~; [(]", requirement, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def main():
    distribution = metadata.distribution("Splunk-HEC-AIO")
    package_path = Path(module.__file__).resolve()
    checkout = Path(os.environ["SOURCE_CHECKOUT"]).resolve()

    try:
        package_path.relative_to(checkout)
    except ValueError:
        pass
    else:
        raise SystemExit("verification imported the source checkout, not the artifact")

    if module.__version__ != "2.1.1":
        raise SystemExit("installed module version changed")
    if SplunkHecAio.__module__ != "splunk_hec_aio.splunk_hec_aio":
        raise SystemExit("documented nested import identity changed")
    if distribution.metadata["Name"] != "Splunk-HEC-AIO":
        raise SystemExit("installed distribution name changed")
    if distribution.version != "2.1.1":
        raise SystemExit("installed distribution version changed")
    expected_summary = (
        "This is a python class file for use with other python scripts to send "
        "events to a Splunk http event collector."
    )
    if distribution.metadata["Summary"] != expected_summary:
        raise SystemExit("installed distribution summary changed")
    if distribution.metadata["Keywords"] != "splunk hec aio":
        raise SystemExit("installed distribution keywords changed")
    if distribution.metadata["Requires-Python"] != ">3.5":
        raise SystemExit("installed Requires-Python changed")

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
