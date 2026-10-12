# Canonical local test inputs

All real API/PWA inputs live here; each repository keeps its own test harness.
Inputs were moved byte-for-byte, not regenerated. Corpus directories are ignored
by Git: provision explicitly elsewhere; missing real fixtures must skip explicitly.

| Previous location | Current location | Contents |
|---|---|---|
| `pruebas_reales/` | `tests/fixtures/real-pdfs/` | attention, bert, resnet, with metadata and `paper.pdf` |
| `Bulk_Upload_Texto_Test/` | `tests/fixtures/text-books/` | Three books with metadata and text pages |
| `samples/` | `tests/fixtures/generated-pdfs/` | Existing `texto_digital.pdf` and `escaneado.pdf` |

SHA-256 manifests: `_media/organization-20261011-safe-pass/`.
Generators refuse existing inputs. Do not upload the scanned sample during local
checks: it selects remote OCR. The active reset already has **3 books / 43 pages**.
Moving inputs changes neither DB documents nor `/media/` URLs.
`_media/local-reset-20261011-161334/generated` is active runtime storage.
Historical media, crops, backups and reports retain their recorded paths.
