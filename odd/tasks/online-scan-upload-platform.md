# Online scan & upload platform (API + PWA + pipeline)

## Objective
Make the library fully online: editors scan or upload books from the PWA, the pipeline processes them
reliably on constrained free infrastructure, readers get a better search/read/cite experience, and
pipeline output quality is measured and improved.

## Decided constraints (user, 2026-10-11)
- Stack: PWA on Vercel Hobby; API + pipeline + in-process worker on Render free (Docker);
  MongoDB Atlas free; Cloudflare R2 (SeaweedFS locally, same S3 code) with presigned URLs; Mistral OCR free.
- Render free: 512 MB RAM, 0.1 CPU, sleeps after 15 min idle, ephemeral disk, no workers
  -> Mongo job queue with lease, retries with backoff, per-page checkpoints, idempotency by sha256,
  opendataloader behind a flag.
- Auth: Auth.js + Google in the PWA; API verifies a short-lived signed token; editors list in Mongo.
  Reading stays public.
- Live Mistral OCR authorized ONLY for downloaded public-domain files, max 20 pages per file.
- Test corpus: 5 real public-domain files from the web + 5 synthetic files.
- Engineering concepts only where they solve a problem here (presigned URLs, debounce, throttle,
  idempotency, lease/visibility timeout, backoff, rate limiting, outbox-style job state).

## Workflow
- TDD strict. Runners: `uv run pytest` (API, MONGODB_URI unreachable for unit runs; Mongo/SeaweedFS via docker
  for integration), `npm test` + `npm run lint` + `npx tsc --noEmit` (PWA).
- Git: baseline on main (API 96a28f8, PWA 6adb9d0); work on `dev`, one commit per task, conventional commits,
  no AI attribution. Push/PR are the user's decision.
- Route: delegated direct, one writer per task (writer trigger: 2+ non-trivial files).

## Tasks
### Infra
- [x] I1 Local docker compose (Mongo + SeaweedFS), API Dockerfile (uv + Java) for Render, render.yaml, env docs.
  - Evidence: `docker compose config` OK, `docker build` OK (38s), pytest pass with MONGODB_URI=mongodb://127.0.0.1:1, render.yaml parses.

### API
- [x] A1 S3-compatible storage service (R2/SeaweedFS) replacing local media writes; media served via public/presigned GET.
  - Evidence: RED ImportError S3Storage / pruning + key assertions failing -> GREEN; pytest 108 passed 9 skipped (Mongo off), 117 passed with local Mongo test DB; SeaweedFS roundtrip (presigned PUT+GET) passed. Keys persisted in imagen_url, URLs built at response time; re-ingest prunes stale pages/figures/originals.
- [x] A2 Mongo job queue: lease/visibility timeout, attempts + exponential backoff, per-page checkpoints, sha256 idempotency, in-process worker.
  - Evidence: commit 2b6be56. RED ImportError `app.services.jobs` -> GREEN 11/11 test_jobs (claim/lease, expired-lease reclaim + LeaseLost, backoff -> fallido, permanent errors, crash sweep, sha mismatch, PDF resume skips checkpointed page). Builders gained `first_page`; `_persist` keeps real original keys and prunes last (A1 follow-up).
- [x] A3 Upload flow: presigned PUT, complete -> job, `GET /trabajos/{id}`.
  - Evidence: commit e66d1f8. RED 404 on /uploads -> GREEN 12/12 test_uploads incl. e2e presigned PUT to SeaweedFS + real job on local Mongo (digital PDF, no Mistral). Multipart `/ingest/upload` kept synchronous (ops/local path).
  - Follow-ups (A1 review): commit df43c20 (S3 delete errors logged, S3 redirect test, uv pinned 0.7.10, compose ports on 127.0.0.1).
  - Checks: pytest 122 passed / 22 skipped (MONGODB_URI=mongodb://127.0.0.1:1), 144 passed (local Mongo, DB biblioteca_test dropped); compileall OK.
- [ ] A4 Auth: verify PWA-minted token, editors collection, protect writes (API key kept for ops scripts).
- [ ] A5 Book management: PATCH/DELETE book, reprocess.
- [ ] A6 Rate limiting, upload limits, `/ingest` allowed-root restriction.
- [x] A7 Escape search snippet HTML at the source (security review finding).
  - Evidence: RED 2 snippet escape tests failing -> GREEN; pytest 110 passed 9 skipped (Mongo off), 119 passed with local Mongo test DB. PWA snippetToSafeHtml re-escapes -> visible &amp;lt; / &amp;amp; until a PWA task decodes-or-trusts the API snippet.

### Pipeline quality
- [ ] P1 Corpus: 5 real public-domain + 5 synthetic files with ground truth; CER/WER evaluation harness and baseline report.
- [ ] P2 Text cleanup: de-hyphenation, repeated header/footer removal, ligature/quote normalization.
- [ ] P3 Scan preprocessing (deskew, crop, contrast) before OCR for images.
- [ ] P4 Search relevance improvements on `$text` (phrases, ranking); measure on corpus.

### PWA
- [ ] W1 Auth.js Google login, editor area, server-side API proxy/token minting.
- [ ] W2 Scan/upload: camera capture, multi-image, reorder/remove, metadata, presigned upload with progress/retry, job status polling with backoff.
- [ ] W3 Book management UI (edit metadata, delete, reprocess).
- [ ] W4 UX: fix "Limpiar", title search, library empty state, remembered view mode, match count/navigation, OCR confidence badge, debounced search, throttled reading progress, text size/dark mode, go-to-page, resume reading.
- [ ] W5 Service worker: offline shell + recently read pages.

### Close
- [ ] D1 Docs + deployment guide (Vercel, Render, Atlas, R2, Google OAuth, Mistral); end-to-end verification.

## Progress / evidence
(per task: commit, checks, review outcome)

## Delivery
- Strategy: feature-branch-chain (user, 2026-10-11). Tracker branch `feat/online-platform` (draft/no-merge PR when pushed).
- Child branches, each from the previous: `feat/op-01-infra` (I1), `feat/op-02-storage` (A1, A7), `feat/op-03-jobs` (A2, A3), `feat/op-04-auth` (A4, A5, A6), `feat/op-05-pipeline` (P1–P4), PWA repo `feat/op-06..` (W1–W5), `feat/op-09-docs` (D1).
- Push and PR creation remain the user's decision.
