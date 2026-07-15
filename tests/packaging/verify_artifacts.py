"""Verify distribution metadata and file contents without installing it."""

import re
import sys
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import NoReturn

EXPECTED_RUNTIME_MODULES = {
    "splunk_hec_aio/__init__.py",
    "splunk_hec_aio/splunk_hec_aio.py",
}
EXPECTED_RUNTIME_REQUIREMENTS = {"aiohttp", "aiohttp-retry"}
EXPECTED_PROJECT_URLS = {
    "Documentation": "https://github.com/georgestarcher/splunk_hec_aio#readme",
    "Issues": "https://github.com/georgestarcher/splunk_hec_aio/issues",
    "Source": "https://github.com/georgestarcher/splunk_hec_aio",
}
FORBIDDEN_PARTS = {".DS_Store", "__pycache__"}


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def normalized_requirement(requirement):
    name = re.split(r"[<=>!~; [(]", requirement, maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def verify_metadata(metadata, artifact):
    expected = {
        "Name": "Splunk-HEC-AIO",
        "Version": "2.1.1",
        "Summary": (
            "This is a python class file for use with other python scripts to "
            "send events to a Splunk http event collector."
        ),
        "Keywords": "splunk hec aio",
        "Requires-Python": ">3.5",
        "License": "MIT",
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            fail(
                "{}: expected metadata {}={!r}, got {!r}".format(
                    artifact, key, value, metadata.get(key)
                )
            )

    runtime_requirements = {
        normalized_requirement(value)
        for value in metadata.get_all("Requires-Dist", [])
        if "extra ==" not in value
    }
    if runtime_requirements != EXPECTED_RUNTIME_REQUIREMENTS:
        fail(
            "{}: runtime requirements changed: {!r}".format(
                artifact, runtime_requirements
            )
        )

    if set(metadata.get_all("Provides-Extra", [])) != {"dev"}:
        fail("{}: expected only the dev dependency extra".format(artifact))
    dev_requirements = {
        normalized_requirement(value)
        for value in metadata.get_all("Requires-Dist", [])
        if "extra ==" in value
    }
    if dev_requirements != {"build", "twine"}:
        fail("{}: development requirements changed".format(artifact))

    project_urls = dict(
        value.split(", ", 1) for value in metadata.get_all("Project-URL", [])
    )
    if project_urls != EXPECTED_PROJECT_URLS:
        fail("{}: project URLs changed: {!r}".format(artifact, project_urls))


def verify_common_contents(names, artifact):
    for name in names:
        path = PurePosixPath(name)
        if FORBIDDEN_PARTS.intersection(path.parts) or name.endswith((".pyc", ".pyo")):
            fail("{}: generated file included: {}".format(artifact, name))


def verify_wheel(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        metadata_name = next(
            (name for name in names if name.endswith(".dist-info/METADATA")), None
        )
        if metadata_name is None:
            fail("{}: wheel metadata is missing".format(path))
        metadata = BytesParser().parsebytes(archive.read(metadata_name))

    verify_metadata(metadata, path)
    verify_common_contents(names, path)

    runtime_modules = {
        name
        for name in names
        if name.startswith("splunk_hec_aio/") and name.endswith(".py")
    }
    if runtime_modules != EXPECTED_RUNTIME_MODULES:
        fail("{}: unexpected runtime modules: {!r}".format(path, runtime_modules))
    if any(PurePosixPath(name).parts[0] == "tests" for name in names):
        fail("{}: tests must not be installed by the wheel".format(path))


def verify_sdist(path):
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
        roots = {PurePosixPath(name).parts[0] for name in names if name}
        if len(roots) != 1:
            fail("{}: sdist must have one top-level directory".format(path))
        root = next(iter(roots))
        metadata_name = "{}/PKG-INFO".format(root)
        try:
            metadata_file = archive.extractfile(metadata_name)
        except KeyError:
            metadata_file = None
        if metadata_file is None:
            fail("{}: sdist metadata is missing".format(path))
        metadata = BytesParser().parsebytes(metadata_file.read())

    verify_metadata(metadata, path)
    verify_common_contents(names, path)

    required = {
        "{}/LICENSE".format(root),
        "{}/README.md".format(root),
        "{}/pyproject.toml".format(root),
        "{}/setup.cfg".format(root),
        "{}/setup.py".format(root),
        "{}/splunk_hec_aio/__init__.py".format(root),
        "{}/splunk_hec_aio/splunk_hec_aio.py".format(root),
        "{}/tests/fixtures/v2_1_1_public_api.json".format(root),
        "{}/tests/test_v2_public_api.py".format(root),
    }
    missing = required.difference(names)
    if missing:
        fail("{}: required sdist files are missing: {!r}".format(path, missing))
    if "{}/splunk_hec_aio/splunk_hec_aio_test.py".format(root) in names:
        fail("{}: legacy tests remain inside the runtime package".format(path))


def main(arguments):
    artifacts = [Path(argument) for argument in arguments]
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1 or len(artifacts) != 2:
        fail("expected exactly one wheel and one .tar.gz sdist")

    verify_wheel(wheels[0])
    verify_sdist(sdists[0])
    print("Verified wheel and sdist metadata and contents.")


if __name__ == "__main__":
    main(sys.argv[1:])
