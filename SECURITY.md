# Security — Irus AI

## Security Controls Implemented
- **Authentication:** hashed passwords (Werkzeug scrypt), generic login errors (no user enumeration), honeypot anti-bot field, username/email/password validation.
- **Session safety:** HttpOnly + SameSite cookies, `SECURE` flag in production, per-user rate limiting (Flask-Limiter).
- **Headers:** `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy` on every response.
- **Least privilege:** Docker image runs as non-root user; multi-stage build; slim base image.
- **Secrets management:** all secrets via environment variables; `.env` gitignored; scanned by Gitleaks in CI.
- **Supply chain:** dependencies audited with pip-audit (OSV); container CVE-scanned with Trivy in CI.
- **Code security:** Bandit SAST + Pytest security tests run on every push.

## Reporting a Vulnerability
Open a private security advisory or email contact@irus.ai. Please do not report vulnerabilities in public issues.