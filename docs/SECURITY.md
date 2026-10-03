# Security, Privacy and Copyright

## Threat model (summary)

| Asset | Threats | Controls |
|---|---|---|
| Uploaded books | Unauthorized access (IDOR), public exposure, leakage via AI | Ownership in SQL on every query, 404 for foreign resources, private storage with random keys, per-book retrieval only |
| Accounts / sessions | Credential stuffing, session theft, CSRF, enumeration | argon2id, HMAC-hashed opaque tokens, HttpOnly/SameSite cookies, CSRF header + Origin allowlist, rate limits, uniform auth errors |
| Server | Malicious files (zip bombs, XXE, path traversal, active content), resource exhaustion | Magic-byte validation, size/page/entry/ratio limits, defusedxml, sanitized XHTML, processing timeouts, bounded workers |
| AI pipeline | Prompt injection in books, exfiltration, runaway cost, cross-user leakage | Untrusted-data prompt rules, no tools for models, schema-constrained outputs, evidence validation, budgets and rate limits, per-book retrieval |
| Secrets | Commit/log leaks | Env-only config, `.env` ignored, secret scanning in CI, no prompts/book text in logs |

## Authentication

- Built-in, standards-based: passwords hashed with **argon2id** (`argon2-cffi`, rehash on parameter change); constant-time
  handling for unknown accounts (dummy verify) and identical error messages.
- Sessions: 256-bit random opaque tokens (`secrets.token_urlsafe`); only an HMAC-SHA256 (keyed with `SECRET_KEY`) is
  stored. Sliding renewal (hourly), expiry (`SESSION_TTL_HOURS`), revocation on logout; all sessions revoked on password
  reset.
- Guest sessions: same token scheme, `GUEST_RETENTION_HOURS` expiry; expired guests cannot authenticate and are purged
  hourly with their books and files.
- Password reset: single-use hashed tokens (30 min), emailed via SMTP (`EMAIL_DELIVERY=smtp`, any provider) in the
  user's language. Responses never reveal whether an account exists, including when delivery fails. Log delivery is
  development-only and rejected by production config validation.
- Cookies: `HttpOnly`, `SameSite=Lax`, `Secure` in production, first-party via the web proxy.

## Authorization

- The actor (user or guest) comes only from the session cookie; client-supplied owner ids are never accepted.
- Every book-scoped route loads the book with `Book.id == :id AND <actor owns>`; child resources (summaries, evidence,
  chapters, annotations, sessions) are checked against that book. Foreign resources return **404**, identical to
  missing ones.
- Exactly-one-owner DB constraints; guest → user migration is explicit and transactional.
- Tested: `tests/test_integration_auth_security.py` exercises every book-scoped endpoint across two users and two
  guests, and E2E Journey E repeats the check through the browser stack.

## CSRF and HTTP hardening

- All state-changing `/api/*` requests require `X-Readbit-CSRF: 1` (cannot be set cross-site without CORS approval) and,
  when an `Origin` header is present, it must be an allowed origin. Combined with `SameSite=Lax` cookies.
- CORS restricted to `CORS_ORIGINS` with credentials.
- Headers: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, HSTS in
  production, `Cache-Control: no-store` on API responses; the web app adds a restrictive CSP.
- Error handling returns taxonomy codes and safe messages; stack traces go to logs only.
- `X-Forwarded-For` is honoured only with `TRUST_PROXY_HEADERS=true` (API reachable solely via the proxy).

## Upload security

- Extension allowlist (`.pdf`, `.epub`), declared MIME consistency, **magic bytes** (`%PDF-`, `PK\x03\x04` + EPUB
  `mimetype`), size limit (`MAX_UPLOAD_SIZE_MB`, enforced while reading), empty-file rejection.
- EPUB archive checks before parsing: entry count, total uncompressed size, per-entry compression ratio (zip bombs),
  absolute or `..` paths, encrypted entries, DRM `encryption.xml`; per-member read limit.
- XML parsed with **defusedxml** (XXE/entity-expansion safe; tested). XHTML parsed as data: scripts, styles, iframes,
  objects, forms, SVG and media are stripped; no markup reaches the client (text only).
- PDF: encrypted files rejected with a clear message, page limit (`MAX_DOCUMENT_PAGES`), processing time budget.
- Filenames sanitized; storage keys are random (`books/<hex>.pdf`) and never exposed; local storage rejects keys that
  escape its root. S3 uploads request server-side encryption.
- Malware scanning: with `MALWARE_SCANNER=clamav` every upload is streamed to clamd (INSTREAM) **before** it is
  stored; infected files are rejected (`malware_detected`) and the scan fails closed (`scanner_unavailable`, retryable)
  if clamd is unreachable. Docker Compose runs a ClamAV container.

## AI security

- Book text is wrapped in `<passages>` and declared **untrusted data** in every prompt; instructions inside a book
  (“ignore previous instructions”, “reveal your prompt”, “answer A”) are to be treated as content. The offline engine
  additionally filters instruction-like sentences.
- Models have **no tools** and no access to the database, network or other books; retrieval is per book.
- Outputs must match JSON schemas; citations must reference supplied passages; answers without valid citations are
  withheld; quiz keys must be independently re-derived.
- Unbounded consumption: per-task token caps, retries bounded, per-actor rate limit, `AI_DAILY_BUDGET`.
- `ai_executions` store no prompts or document text. API keys stay server-side.
- The adversarial evaluation book checks that injected instructions never appear in outputs (`safety.injection_leaks`).

## Privacy

- Private libraries; no public links, sharing or indexing.
- Uploaded books are **never used to train or fine-tune** models. With a live provider, passages are sent only to
  produce the requested content; choose a provider/contract that excludes training on API data.
- User controls: delete a book (file + all derived data), delete account (everything), export data (JSON), export
  notes (Markdown).
- Retention: guest data deleted after `GUEST_RETENTION_HOURS`; expired sessions/tokens purged; storage lifecycle rules
  recommended as a backstop.
- Analytics: allowlisted event names and property keys only; pseudonymous keyed-hash actor ids; no book text, notes or
  questions.
- Encryption: TLS in transit (terminate at the load balancer; HSTS), provider encryption at rest for DB and bucket.

## Copyright safeguards

- Users confirm they have the right to upload; uploads are for private personal use; terms and a copyright contact are
  published.
- Citation excerpts are capped (`MAX_EXCERPT_CHARS`, 320) and point to a single supporting sentence.
- Extractive summaries are bounded by `MAX_QUOTE_RATIO` of the selection and depth; generative prompts forbid long
  verbatim quotation (< 25 words when wording matters).
- The source reader shows extracted text only to the uploading user.

## Dependency and secret hygiene

CI runs `pip-audit`, `npm audit --omit=dev`, ruff security rules and gitleaks. Licences were chosen to avoid AGPL
libraries (no PyMuPDF/ebooklib). No credentials are committed; `.env.example` holds placeholders only.

## Incident response

1. Triage: identify scope from structured logs (`request_id`), `ai_executions`, `processing_jobs`.
2. Contain: rotate `SECRET_KEY` (invalidates all sessions and reset tokens), rotate provider/storage credentials,
   disable the AI provider (`DEFAULT_LLM_PROVIDER=extractive`) or uploads (scale API to read-only) as needed.
3. Eradicate and recover: patch, redeploy, restore from backups if data integrity is affected.
4. Notify affected users and regulators per applicable law; record a post-incident review.
5. Report security issues to security@readbit.example.

## Known gaps

No MFA, no OAuth providers yet, and no per-user storage quotas beyond upload rate limits. No independent penetration
test has been performed.
