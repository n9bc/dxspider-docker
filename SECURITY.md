# Security Policy

## Supported Versions

This project is at an early stage. Security fixes are applied to the latest
`main` and the most recent tagged release.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✅        |
| < 0.1   | ❌        |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report privately via GitHub's [private vulnerability reporting][gha]
(Security → Report a vulnerability) on this repository, or contact the
maintainer **[@n9bc](https://github.com/n9bc)** directly. Include:

- A description of the issue and its impact
- Steps to reproduce / a proof of concept
- Affected component (dxspider image, stats-svc, Caddy config, compose)
- Any suggested remediation

You can expect an acknowledgement within a few days and a coordinated
disclosure timeline once the report is triaged.

[gha]: https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability

## Security Posture & Hardening Notes

This stack is designed to run as a **public DX cluster node**. Be aware of the
following by design:

- **Telnet (port 7300) is intentionally public.** The DX cluster protocol is
  unauthenticated plaintext telnet; this is normal for the amateur-radio DX
  cluster network. Do not expose the sysop console this way.
- **The dashboard has no authentication in v1, by design** — it serves
  read-only public spot statistics. Do not place private data behind it.
- **The sysop web console (ttyd → `console.pl`)** is never published to the
  host; it is reachable only through Caddy under `/cluster` and is protected
  by HTTP Basic Auth (`TTYD_USER` / `TTYD_PASSWORD`). **You must change the
  default credentials** before exposing the node to the internet.
- **Change every default password** in `.env` before first public boot:
  `TTYD_PASSWORD`, `POSTGRES_PASSWORD` (and the matching password in
  `DX_DB_DSN`), and `DX_MONITOR_PASSWORD`.
- **Containers run as non-root** (`appuser` in stats-svc, `sysop` in
  dxspider) under `tini` as PID 1.
- **Postgres and stats-svc are not published to the host** — only the Caddy
  ports (80/443) and the DX telnet port (7300) are exposed.
- **TLS** is automatic via Let's Encrypt when `DOMAIN` is set to a real FQDN;
  otherwise Caddy serves plain HTTP for LAN/dev only.
- **Dashboard XSS hardening:** all telnet-sourced values (callsigns, comments,
  modes) rendered into dashboard tables are HTML-escaped before insertion.
- **DXSpider source is SHA-pinned** in the Dockerfile. For production, mirror
  the source to infrastructure you control and override the build args (see
  `docs/configuration.md`).
- Secrets live only in `.env`, which is git-ignored. Never commit a real
  `.env`.
