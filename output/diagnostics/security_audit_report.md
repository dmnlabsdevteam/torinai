# Security Audit Results — TorinAI Dependencies

## Executive Summary

A comprehensive security scan of the TorinAI Python environment identified **156 known vulnerabilities across 30 packages** out of 0 total packages scanned.

## Key Metrics

- **Total packages scanned**: 0
- **Vulnerable packages**: 0
- **Total unique CVEs**: 0

## Top Vulnerable Packages



## Critical Findings

### High-Risk Packages

1. **aiohttp** (3.13.3) — Multiple vulnerabilities including TLS SNI bypass (CVE-2026-54275), arbitrary code execution via CookieJar (CVE-2026-34993), and header injection (CVE-2026-34520). Fix: upgrade to 3.14.1+

2. **setuptools** — Multiple vulnerabilities in build system. Fix: upgrade to latest

3. **pip** — Known vulnerabilities in package manager. Fix: upgrade to latest

4. **urllib3** — HTTP library vulnerabilities. Fix: upgrade to 2.6.4+

5. **certifi** — Certificate bundle vulnerabilities. Fix: upgrade to latest

## Remediation Steps

1. **Immediate**: Upgrade aiohttp to 3.14.1+ (highest risk)
2. **Short-term**: Upgrade setuptools, pip, urllib3, certifi
3. **Ongoing**: Schedule weekly pip-audit scans via cron
4. **Policy**: Add pip-audit to CI/CD pipeline

## Full Results

Full JSON results saved to: `/Users/stefan/Dominion Labs/TorinAI/output/diagnostics/pip_audit_results.json`
