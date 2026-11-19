# Security policy

## Reporting
Please report vulnerabilities privately through GitHub's "Report a vulnerability" (Security tab) instead of opening a public issue.

## Scope and design
- The server stores no personal data and has no user accounts.
- Inputs are validated against schemas, and outputs are structured data from upstream sources.
- Upstream text (for example SIMBAD names) is treated as **data, never as instructions**. Tool descriptions are static and reviewed, which guards against tool poisoning.
- Fault-injection controls are disabled in production by an environment flag, and a test verifies it.
- Rate limiting per client IP protects upstream services.
- Dependencies are pinned and scanned in CI.
