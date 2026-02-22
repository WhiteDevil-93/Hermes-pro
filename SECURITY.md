# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 2.x     | :white_check_mark: |
| < 2.0   | :x:                |

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

Please report security vulnerabilities by emailing **security@hermes-project.dev**
or by using [GitHub's private vulnerability reporting](https://github.com/WhiteDevil-93/Hermes-pro/security/advisories/new).

### What to include

- Description of the vulnerability
- Steps to reproduce
- Affected versions
- Potential impact
- Suggested fix (if any)

### Response timeline

| Action                    | SLA            |
|---------------------------|----------------|
| Acknowledge receipt       | 48 hours       |
| Initial triage            | 5 business days|
| Patch for critical issues | 7 days         |
| Patch for high issues     | 30 days        |
| Public disclosure         | 90 days        |

## Security Measures

This project employs the following automated security controls:

- **Dependency auditing** — `pip-audit` runs on every push and PR
- **Secret scanning** — Gitleaks detects leaked credentials
- **Static analysis** — CodeQL and Bandit scan for code vulnerabilities
- **Container scanning** — Trivy scans Docker images for CVEs
- **Dependency review** — PRs are checked for high-severity dependency vulnerabilities
- **License compliance** — GPL-3.0 and AGPL-3.0 dependencies are denied
- **SBOM generation** — CycloneDX bill of materials is published with each release

## Disclosure Policy

We follow [coordinated vulnerability disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure). We ask that you:

1. Allow us reasonable time to fix the issue before public disclosure
2. Make a good-faith effort to avoid data destruction and service disruption
3. Do not access or modify data belonging to other users
