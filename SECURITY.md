# Security

AUDEN can control parts of your Windows desktop. Treat it as you would a
power-user automation tool.

## Safety model

- The local HUD server binds to `127.0.0.1` only and requires a per-launch
  random token.
- Destructive tools (`run_command`, `write_file`, `lock_pc`, `type_text`)
  request an explicit approval card in the HUD before running.
- The model can still be wrong. Read the approval details before accepting.
- Commands run with your Windows user privileges. AUDEN does not request
  administrator rights.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use the repository's
private security advisory feature (GitHub: **Security → Advisories → Report a
vulnerability**) and include:

- AUDEN version and Windows version.
- Steps to reproduce.
- The impact you believe is possible.

You should receive an acknowledgement within a few days.

## Scope

In scope:

- Authentication bypass of the local HTTP server.
- Path traversal in the static file server.
- Approval bypass for destructive tools.
- Code execution caused by untrusted model output without approval.

Out of scope:

- Attacks that already require code execution as the same Windows user.
- The model producing incorrect or offensive text.
- Browser extensions or other software on the same machine.

## Hardening tips

- Keep Windows and Edge updated.
- Do not change the server to bind `0.0.0.0` or expose it through a proxy.
- Review the `safety.write_roots` setting in `config.json`; keep it narrow.
- Run AUDEN as a standard user, not an administrator.
