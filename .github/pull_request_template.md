## Summary

Describe what changed and why. Link the issue that defines the requested
behavior and acceptance criteria.

Closes #

## Compatibility classification

Select exactly one classification. See `docs/compatibility.md`.

- [ ] No observable behavior change
- [ ] Backward-compatible bug fix
- [ ] Opt-in addition
- [ ] Breaking change intended for a major release

## Compatibility review

- [ ] Existing documented imports remain available.
- [ ] Existing public signatures and defaults remain compatible.
- [ ] Existing synchronous usage remains available.
- [ ] Existing return values and exceptions are unchanged, or the impact is
      explicitly documented and approved.
- [ ] The minimum Python version is unchanged, or the change is explicitly
      documented and approved.
- [ ] Request bytes, endpoints, headers, and retry behavior are unchanged, or
      the change is an isolated protocol fix with before-and-after tests.

Explain any unchecked item:

## Verification

- [ ] `python -m unittest discover -s tests -v` passes.
- [ ] `python -m build` and `python -m twine check dist/*` pass when packaging
      metadata or contents change.
- [ ] Wheel and source-distribution installation tests run outside the checkout
      when packaging metadata or contents change.
- [ ] Tests use mocks or local transports and make no public network requests.
- [ ] No HEC token, authorization header, private hostname, or sensitive event
      data appears in code, fixtures, logs, or artifacts.
- [ ] New or changed behavior has focused tests.
- [ ] Documentation and examples were updated when user-facing behavior changed.
- [ ] Behavior-visible changes include release notes or changelog guidance.

List additional commands, platforms, or live integration checks performed:

## User impact

Describe migration steps, operational impact, and possible retry or duplicate
delivery effects. Write `None` for a behavior-neutral change.
