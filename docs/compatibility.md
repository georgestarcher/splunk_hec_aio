# v2 compatibility contract

`splunk_hec_aio` has active users. The v2 release line therefore treats the
released v2.1.1 behavior as its compatibility baseline while the repository is
modernized.

The characterization tests under `tests/` describe that baseline. They are
deliberately separate from tests that specify corrected or new behavior. A
characterization test is evidence of what v2.1.1 does; it is not necessarily a
claim that the behavior is ideal.

## Protected compatibility surface

Within the v2 release line, maintainers should preserve:

- the distribution and package names;
- the documented import path
  `from splunk_hec_aio.splunk_hec_aio import SplunkHecAio`;
- public class and method names, signatures, positional arguments, keyword
  arguments, and defaults;
- successful-call return values and existing exception behavior;
- existing synchronous entry points;
- default configuration, queueing, batching, retry, and flush behavior;
- request endpoints, headers, parameters, payload shaping, and compression,
  except for an explicitly approved protocol bug fix;
- Python versions that are established as supported by compatibility evidence.

The `python_requires` value currently declares Python versions greater than
3.5. That declaration is not proof that every such version works with current
dependencies. The minimum supported version must be established separately and
must not be raised merely because development tools require a newer Python.
Modern lint, type, audit, and build tools can run in a separate tooling
environment.

## Change classifications

Every pull request that can affect users should select one classification:

1. **No observable behavior change** — tests, documentation, CI, repository
   governance, or an internal refactor that preserves the protected surface.
2. **Backward-compatible bug fix** — an observable correction that keeps public
   entry points usable. It requires focused before-and-after tests and release
   notes.
3. **Opt-in addition** — a new API or mode that is disabled by default and does
   not alter existing callers.
4. **Breaking change** — a removed import, changed signature or default, new
   default exception, higher Python floor, or other incompatible behavior.

Breaking changes are not eligible for a v2 release unless a compatibility shim
preserves existing callers.

## Rules for approved behavior changes

A characterization test may change only when the pull request:

- identifies the exact released behavior being changed;
- links the issue approving the change and its classification;
- adds a test for the intended replacement behavior;
- explains migration impact in release notes;
- uses an opt-in path when that can preserve v2 callers; and
- performs live Splunk verification when request bytes or endpoint semantics
  change.

New async entry points, strict delivery results, and indexer acknowledgment must
remain additive and opt-in in v2. Existing synchronous methods retain their
signatures, defaults, return values, and exception behavior.

## Running the baseline

The compatibility suite uses `unittest` from the Python standard library so it
does not establish a new runtime dependency or Python-version floor:

```shell
python -m unittest discover -s tests -v
```

The suite performs no network requests and needs no Splunk host or token.
