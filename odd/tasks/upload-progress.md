# Upload progress and one book per document

## Problem
Uploading 4 PDFs at once produced ONE 82-page book (multi-file uploads are merged; designed for photo scans)
and the editor saw no visible progress, so they could not tell whether processing finished or failed.

## Decisions
- PDF/TXT files in one upload: one book per file, each with its own title (defaults to the file name).
  Image files (scan photos): still one book, pages in the given order.
- User-facing steps (Spanish, non-technical): Subiendo → En espera → Leyendo páginas (n de N) → Preparando la búsqueda → Disponible; failure shows a plain message and the next action.
- "Mis subidas" page lists the editor's recent uploads with their step; job state survives closing the tab.

## Tasks
- [ ] U1 API: job `etapa` field + progress per step; split PDF/TXT uploads into one job per file; `GET /trabajos` (mine, recent) for editors.
- [ ] U2 PWA: per-file titles for multi-document uploads; step tracker on the job page and right after upload; "Mis subidas" list with polling.

## Checks
API: `uv run pytest` + compileall (TDD strict). PWA: lint, typegen+tsc, `npm test`, build; browser check against the running local stack.
