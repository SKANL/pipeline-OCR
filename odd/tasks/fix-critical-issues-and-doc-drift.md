# Fix critical issues and doc drift (API + PWA)

Objective: fix the confirmed runtime problems found in the 2026-10-11 analysis and align docs with code.
TDD: strict (global CLAUDE.md), runner `uv run pytest` (API), `npm test` (PWA).
Route: delegated direct, one writer per repository (writer trigger: 2+ non-trivial files).
Commits: pending — both repos have all work uncommitted (API has no commits); initial commit is the user's decision.

## API (C:\code\pipeline-OCR)
- [x] A1 Scanned-PDF ingest reads `p.ocr_confianza` on OCR pages (field is `confianza`) — `ingest.py:709-711`; add regression test.
- [x] A2 Default CORS allows only localhost:3000; PWA runs on 3010 — `config.py:31`, test, `.env.example`, docs.
- [x] A3 Async upload endpoint runs sync ingest on the event loop — `upload.py`.
- [x] A4 `/search` 500 until indexes exist — create indexes at startup without failing boot when Mongo is down.
- [x] A5 `POST /ingest` 500 on missing `root` — return 4xx.
- [x] A6 Docs drift: API.md ingest response, README endpoints/env/modules, ARCHITECTURE pruning + pdf_layout, 422 scope, PDFium vs opendataloader wording, PRODUCT_BRIEF search, modelo_libro.json `_id`/fields.

## PWA (C:\code\biblioteca-eclesiastica-web)
- [x] W1 Docs drift: `.env.example` missing/ignored, CORS claim, endpoint table, favicon claim, Node version, AGENTS (CitePanel client fetch, highlightText, ReaderImage), tests/tools README stale commands, duplicated JSDoc.

## Evidence
- A1: tests/test_ingest_ocr.py RED (AttributeError ocr_confianza) -> GREEN after ingest.py:710 uses `p.confianza`.
- A2: config.py:31 + .env.example default adds :3010; tests/test_hygiene.py new CORS 3010 test RED -> GREEN; API.md/README updated.
- A3: upload.py now plain `def` (threadpool, `upload.file.read()`); hygiene upload tests pass; Mongo-backed upload tests skipped (no Mongo).
- A4: main.py lifespan calls ensure_indexes(), logs and continues on failure; tests/test_startup.py RED -> GREEN.
- A5: routers/ingest.py maps FileNotFoundError -> 400; test_ingest_rejects_bad_root RED -> GREEN.
- A6: API.md, README.md, AGENTS.md, ARCHITECTURE.md, PRODUCT_BRIEF.md, modelo_libro.json, .env.example aligned with code.
- W1: PWA docs/.env.example/.gitignore/JSDoc aligned; npm run lint clean, npm test 8/8.
