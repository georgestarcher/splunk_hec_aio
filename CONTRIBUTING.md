# Contributing to splunk_hec_aio

Thank you for helping improve `splunk_hec_aio`. The module has active users, so
changes should be small, testable, and deliberate about backward compatibility.

## Report a security vulnerability

Do not open a public issue, pull request, or discussion for a suspected
vulnerability. Follow the [security policy](SECURITY.md) and use the
[private vulnerability-reporting form](https://github.com/georgestarcher/splunk_hec_aio/security/advisories/new).
Never include real credentials, private endpoints, or sensitive event data.

## Report a bug or request a feature

Use the repository's bug-report or feature-request form. Search open and closed
issues first, provide a minimal reproduction, and select the closest
compatibility classification.

Never include HEC tokens, authorization headers, private hostnames, private
URLs, or sensitive event data in an issue, test, log, or pull request.

## Set up a development environment

Create a virtual environment using a Python version that the project currently
supports. The exact supported range is being established by compatibility
testing; do not infer a new minimum version from development-tool requirements.

```shell
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

On Windows PowerShell, activate the environment with
`.venv\\Scripts\\Activate.ps1` before running the `python` commands.

## Run the compatibility suite

From the repository root with the virtual environment active, run the same
command used by the compatibility CI job:

```shell
PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=error python -m unittest discover -s tests -v
```

In Windows PowerShell, set the two environment variables before running the
same Python command:

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONWARNINGS = "error"
python -m unittest discover -s tests -v
```

The compatibility suite must remain deterministic, secret-free, and isolated
from public networks. It must not require a Splunk host or token. The legacy
test module under `tests/legacy/` contains live-network tests and is not the
standard contributor test command. The required bootstrap job runs on Linux
with Python 3.9. Additional runtime jobs cover Linux on Python 3.13 and macOS
and Windows on both Python 3.9 and 3.13. These evidence-backed Splunk anchors
do not by themselves establish the project's minimum or complete supported
Python range.

## Run the quality suite

The quality tools run on Python 3.13 while checking code against a Python 3.9
syntax target. This keeps current development tooling separate from the v2
runtime floor. Install the pinned quality tools and runtime dependencies in a
dedicated environment:

```shell
python3.13 -m venv .venv-quality
source .venv-quality/bin/activate
python -m pip install -r requirements.txt -r .github/requirements/quality.txt
```

Then run the same secret-free checks used by the **Quality** GitHub Actions
workflow:

```shell
python -m ruff format --check .
python -m ruff check .
python -m mypy
python -m pytest --cov=splunk_hec_aio --cov-branch --cov-report=term-missing --cov-fail-under=70
python -m pip_audit --requirement requirements.txt
git diff --exit-code
```

Static type checking initially covers the live-integration helper and packaging
verification code. Expanding it into the released runtime module needs a
versioned compatibility review; type-only refactoring must not silently change
v2 behavior. The branch-coverage floor is a ratchet, not a substitute for
focused behavior assertions. The quality suite also runs bounded,
deterministic Hypothesis properties from `tests/property/`. That directory is
intentionally not a Python package, so the Python 3.9 unittest compatibility
baseline does not import the modern-only Hypothesis dependency.

## Build and verify distributions

Packaging metadata keeps the runtime requirements separate from the `dev`
extra installed above. Values are declared in `setup.cfg` so older installers
can keep using the compatibility shim; `pyproject.toml` exposes the same values
to modern PEP 517/621 build frontends. Build both supported artifact formats
and validate their metadata from the repository root:

```shell
rm -rf build dist *.egg-info
python -m build
python -m twine check dist/*
python tests/packaging/verify_artifacts.py dist/*
```

The **Packaging** GitHub Actions workflow additionally installs the wheel and
source distribution into separate clean environments, changes to a directory
outside the checkout, and checks the documented nested import and v2.1.1 API
snapshot. Python 3.9 and 3.13 are evidence-backed CI targets; they do not yet
establish the project's minimum or complete supported range.

## Verify a release candidate

Maintainers can run the **Release verification** workflow manually from
`main`. It reuses the complete Compatibility, Quality, and Packaging workflows,
then builds and verifies the exact candidate artifacts under read-only
permissions. The temporary bundle includes the wheel, source distribution,
SHA-256 checksums, and a manifest tying them to a full commit and an allowed v2
compatibility classification.

The workflow is a non-publishing dry run. It has no tag trigger, secret,
environment, GitHub Release write permission, or PyPI path. A separate
**Publish verified GitHub release** workflow consumes a successful retained
bundle only after it matches the current GitHub-verified annotated tag and a
maintainer approves the protected `GITHUB_RELEASE` environment. Follow
[`docs/releasing.md`](docs/releasing.md) for inputs, evidence review, signed-tag
creation, the separate live-integration gate, publication approval, and
recovery rules.

## Run the protected live integration test

Maintainers can run the **Live Splunk integration** workflow manually after a
change reaches `main`. This workflow is separate from pull-request CI and uses
the protected `SPLUNK_INTEGRATION` GitHub environment, which requires approval
before its secrets are released. It must never be enabled for fork pull
requests or changed to use `pull_request_target`.

The environment requires two different, least-privilege credentials:

- `SPLUNK_HEC_TOKEN`, an ingest-only HEC token;
- `SPLUNKTOKEN`, a search-only Splunk REST token.

It also requires secret values `SPLUNK_HEC_HOST` and `SPLUNKBASEURL`, plus
environment variables `SPLUNK_HEC_PORT`, `SPLUNK_HEC_INDEX`,
`SPLUNK_HEC_SOURCE`, `SPLUNK_HEC_SOURCETYPE`, `SPLUNKAPP`,
`SPLUNKTLSVERIFY`, and `SPLUNKTIMEOUT`. TLS verification must be enabled. Do
not copy any of these values into workflow logs, committed files, or issue
reports.

For each run, the workflow sends one event with a unique `ci_test_id` through
the released `SplunkHecAio` interface. It renders the committed
`.github/querysplunk/hec-smoke.yml` template into a temporary file, validates
it with a pinned and checksum-verified querysplunk release, and searches for
the marker for at most 80 seconds. One or more matches succeeds because HEC
retries can result in at-least-once delivery; zero matches fails. Failure
artifacts contain only a bounded status, attempt number, exit code, and match
count—not tokens, endpoints, event bodies, SPL, or raw search results.

## Preserve the v2 contract

Read [`docs/compatibility.md`](docs/compatibility.md) before changing public or
wire-visible behavior. Pull requests must classify the change as one of:

1. no observable behavior change;
2. backward-compatible bug fix;
3. opt-in addition; or
4. breaking change.

Existing imports, public method signatures, defaults, synchronous entry points,
return values, exception behavior, and supported Python versions remain stable
in v2 unless an approved compatibility path says otherwise.

Characterization tests describe what v2.1.1 does, including behavior that may
have a separate corrective issue. Do not silently rewrite a characterization
test to make a proposed implementation pass. An approved behavior change needs
focused before-and-after tests, release notes, and live Splunk verification when
request bytes or endpoint semantics change.

## Prepare a pull request

- Keep one logical change per pull request.
- Link the issue that defines the change and acceptance criteria.
- Complete the pull-request compatibility checklist.
- Add deterministic tests for new or corrected behavior.
- Update documentation and examples when usage changes.
- Keep live HEC/querysplunk verification separate from secret-free tests.
- Confirm that generated files, local environments, credentials, and result
  artifacts are not committed.

Repository-wide formatting, packaging, dependency, or Python-version changes
should not be bundled with an unrelated bug fix.

## Review automated dependency updates

Dependabot checks Python manifests and pinned quality tools each Monday at
09:00 America/Chicago, followed by GitHub Actions at 09:30. Minor and patch
updates are grouped by runtime, quality tooling, and Actions to limit pull
request noise; major updates remain separate for deliberate compatibility
review.

Treat each automated update like any other pull request: inspect upstream
release notes, classify compatibility, require the protected checks, and keep
runtime dependency changes separate from behavior changes. Never merge an
update solely because its version is newer or its initial CI run is green.
