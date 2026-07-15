# Security Policy

## Supported versions

Security fixes are considered for the latest released patch in the maintained
release line.

| Version | Supported |
| --- | --- |
| Latest 2.1.x release | Yes |
| Earlier 2.1.x releases | No |
| 2.0.x and earlier | No |

Older releases and tags remain available for compatibility and reproducibility,
but availability does not mean that a release is receiving security fixes. This
table describes release maintenance, not the complete Python compatibility
range. It will be updated when a new major release line is published.

## Report a vulnerability privately

Do not open a public issue, pull request, or discussion for a suspected security
vulnerability. Use GitHub's private vulnerability-reporting form instead:

[Report a vulnerability privately](https://github.com/georgestarcher/splunk_hec_aio/security/advisories/new)

Provide enough information to reproduce and assess the report when possible:

- the affected `splunk_hec_aio` version and installation method;
- the Python version and operating system;
- the expected security impact and a realistic attack scenario;
- the affected API, payload mode, or HEC interaction;
- a minimal, secret-free proof of concept or clear reproduction steps;
- known mitigations or workarounds; and
- any coordinated-disclosure or credit preferences.

Never include a real HEC token, authorization header, private hostname or URL,
or sensitive event data. Use clearly fake values and redact logs and responses.
If a credential may already have been exposed, revoke or rotate it through its
own provider; do not paste it into the report.

## What to expect

Maintainers will review reports on a best-effort basis; this project does not
promise a response or remediation service-level agreement. A maintainer may ask
for more information, accept the report as a draft security advisory, or close
it with an explanation when it is not a security issue.

When a report is accepted, maintainers and the reporter should coordinate the
fix, release, advisory, and disclosure timing privately. Please avoid public
disclosure until that coordination is complete.

## Maintainer handling

Maintainers should:

1. Review new reports under **Security and quality > Advisories** and keep
   vulnerability details out of public issues and pull requests.
2. Reproduce the report with fake credentials and non-sensitive data, assess
   affected supported versions, and request missing evidence privately.
3. Accept a valid report as a draft advisory. Use a temporary private fork when
   code collaboration is needed before disclosure.
4. Prepare the smallest compatible fix with focused tests, release notes, and
   live HEC verification when request behavior is affected.
5. Coordinate credit, release timing, advisory publication, and any CVE request
   with the reporter.
6. Publish the advisory only when the fix and user guidance are ready, or close
   an invalid report with a private explanation.
