# Public repository security

[Documentation](README.md) · [한국어](ko/security.md)

AI-RM is public. Treat component source and its history as potentially public as well. The private status of `duet` does not justify embedding credentials in it.

## Keep out of tracked files

- Internal addresses and site-specific cluster endpoints.
- Passwords, API tokens, kubeconfig credentials and SSH/TLS private keys.
- URLs containing credentials.
- Unreleased performance figures and project evidence intended for private storage.

| Information | Location |
|---|---|
| Configuration key names | Tracked `cluster.example.env`, with placeholders |
| Actual site settings | Untracked `cluster.local.env` and `deploy/clusters/<name>/` |
| Example hostnames | `<gateway-host>` or RFC 5737 documentation addresses |
| Fake credentials for tests | Clearly fake values; narrowly scoped `.sensitive-allow` only where needed |

## Checks

```bash
python3 tools/check_sensitive.py .
# Or: make check, including fetched component repositories.
```

The scanner checks **Git-tracked/staged text files**, not untracked drafts or all history. Stage intended additions before running the final publication check. GitHub Actions runs the umbrella scan on pushes and PRs. Before changing repository visibility, also review historical branches/tags and previously published assets; a clean current tree is not a history audit.

## If sensitive data was committed

Revoke/rotate an actual exposed credential first. Remove it from current files, then coordinate history cleanup with repository maintainers. History rewriting changes commit IDs and may require force pushing and downstream checkout repair; do not perform it casually. Cached pull-request refs and other copies may require separate cleanup with the hosting provider.
