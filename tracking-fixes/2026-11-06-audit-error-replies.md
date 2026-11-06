# 2026-11-06 — The accuracy audit shows a daemon error reply instead of "None"

**Status:** branch `fix/audit-ssl-check-error`.

**Problem**
- On the G11 the audit printed ✗ "S1 wrong.host.badssl.com does not match its name: None".
- Calling `/api/tools/ssl-cert` directly a minute later gave the right answer: `name_match: false` and `verify_errors: ["hostname mismatch"]`.
- The audit's `daemon()` helper turned any HTTP error reply into `{}`. So a failed request (badssl.com unreachable, or the daemon still starting) read as `None`, not as the error it was.

**Fix** (`scripts/remote/deploy-data-accuracy-audit.sh`)
- `daemon()` keeps an error reply's JSON body, and adds `error: "HTTP <code>"` when the body has no `error`.
- The wrong-host check prints `(name_match, error)`. It passes only on `(False, None)`.

**Test:** the helper was run on the G11.
- `wrong.host.badssl.com` gives `(False, None)`.
- An empty host gives `(None, 'Host is required')`.
- shellcheck is clean.

**Lesson:** a check that prints only the field it wants hides the reason that field is missing. Print the error next to it.
