# API verification tools

Run from the API root with `uv run python -m tests.tools.<name>`.
Only `scripts/dev.ps1` and `scripts/create_search_index.py` are operational scripts.
The PWA harness stays in the sibling web repository's `tests/tools/` for npm
resolution. Input mapping: [fixtures](../fixtures/README.md).

| Tools | Role and side effects |
|---|---|
| `seed_test_data`, `make_sample_pdf` | Generate missing fixtures; refuse existing inputs |
| `smoke_local`, `smoke_upload`, `medir_cobertura_bbox` | Ingest/write DB and media; upload smoke may invoke OCR with a configured key |
| `figure_evidence`, `phase2_evidence`, `phase2_compare`, `phase2_inspector_probe` | Local measurements in historical namespaces; refuse existing stage/output |
| `fix_confirmed_pdf_evidence`, `probe_confirmed_pdf` | Dated diagnostics against retained historical baselines |
| `refresh_figure_fixtures`, `refresh_phase2_fixtures` | Update existing loopback DB documents; preserve backups, refuse existing evidence |
| `verify_phase2_local_api` | In-process HTTP read checks using the current stored media URL |
| `check_confirmed_pdf` | Dated isolated harness; pytest DB cleanup and isolated web build; not safe under a no-destructive-DB constraint |

```powershell
uv run pytest
uv run python -m compileall app tests/tools scripts
```

Pytest's session fixture drops its selected test database. For no-destructive-DB
validation override `MONGODB_URI` to a confirmed unused loopback port and report
DB skips. Verify the running dataset separately with GET on API 8000 / web 3010.
Do not run ingestion, refresh or OCR tools for organization validation.

Historical commands `python -m scripts.<name>` remain recorded as executed;
current equivalent: `python -m tests.tools.<name>`. All 15 Python verification
tools moved once, with no duplicate copies or deletions.
