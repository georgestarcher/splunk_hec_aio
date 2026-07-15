# Contributing to splunk_hec_aio

Thank you for helping improve `splunk_hec_aio`. The module has active users, so
changes should be small, testable, and deliberate about backward compatibility.

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
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

On Windows, use `.venv\\Scripts\\python` in place of `.venv/bin/python`.

## Run the compatibility suite

From the repository root, run:

```shell
.venv/bin/python -m unittest discover -s tests -v
```

The compatibility suite must remain deterministic, secret-free, and isolated
from public networks. It must not require a Splunk host or token. The legacy
test module inside the package contains live-network tests and is not the
standard contributor test command.

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
