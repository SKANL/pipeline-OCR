# Production PWA routing: reproduced defects fixed

> Relocation note: commands/3025 URLs below record historical execution, not the
> current default. Web harnesses now live in web `tests/tools/`; canonical web
> port is 3010, API 8000. API tools use `tests.tools.<name>` and input mapping is
> [here](../tests/fixtures/README.md). Historical evidence remains untouched.

**Final bounded index slice:** three named flows pass on desktop and mobile
(6/6). Real page-1 CTA coverage is now closed for the three snapshot books;
missing-first-page CTA and empty/out-of-range index defects were reproduced and
fixed. See [Final book-index validation](#final-book-index-validation).

11 October 2026. **38 functional browser cases passed (19 per viewport),
12 production regression checks passed, 8 reader helper tests passed, and
102 API tests passed with zero skipped.** Production build, lint and compileall
passed. Ordinary tested routes had no JS chunk failures or hydration mismatch
errors. Deliberate reader API outages produced recoverable React #419 errors;
recovery succeeded, but the outage console is not certified clean.

## Fresh environment and source identity

- Web URLs: `http://127.0.0.1:3025`; real `next start`, Next **16.4.0**,
  React **19.3.0**, normal Turbopack production build.
- API URLs: `http://127.0.0.1:8025`; newly launched current Python source through
  the uv environment, loopback binding, no reload or old service reuse.
- Evidence **E**: `_media/pwa-routing-20261011/` (ignored). Final build copy:
  `E/verified`, build ID **`1AbcwqWRIfOfmtQFuOK89`**. Earlier failed-state
  builds remain in `E/baseline` and `E/final`.
- `E/verified-source.json` records SHA-256 for app/components/lib/scripts;
  `E/checks.json` verifies these against delivered web source and records API
  app hashes. Isolated copy configuration adds only `turbopack.root="C:/code"`
  to resolve its dependency junction. No user environment files were copied
  or edited; API URL/CORS were process-scoped.
- Mongo: `mongodb://127.0.0.1:27017`, fresh database
  **`biblioteca_pwa_routing_20261011_isolated`**, rejected if already present
  before seeding. Three books and seven measured pages only: Attention 4;
  BERT 3/15; ResNet 2/3/4/6. Original numbers are preserved. Metadata is explicit
  fixture bibliographic metadata, not new extraction.
- Page text, positions, reading segments and supports come directly from
  `_media/fix-confirmed-pdf-20261011-delivery/report.json`, SHA-256
  `8e6964904508a4d291530b318d39596da5a76d22f66060619240c48178745adf`.
  Seed verifies each original PDF hash against that report. `MEDIA_ROOT` points
  to the delivery directory: original URLs resolve to `resnet/original-3.png`,
  etc.; support URLs retain `resnet-after/figuras/...`, etc. No media writes,
  database refreshes, ingestion, Java conversion or OCR calls were used.
- API tests used separate `biblioteca_pwa_routing_20261011_tests` and separate
  test media/basetemp; they never cleared the browser fixture database.

## Reproduced defects and bounded fixes

| Defect | Failed real action / root cause | Source fix and regression |
|---|---|---|
| Filter history | Library: submit author `He`, clear, Back gives URL `autor=He` but empty field. Search: submit `hypothesis`, Back to `identity` leaves `hypothesis` in input. Both viewports. `useState(initialProps)` survived soft navigation. | `components/FilterForm.tsx`: keyed inner form by URL-prop snapshot. Actual submit/clear/Back/Forward/reload assertions now pass. Drafts remain local until navigation. |
| Stale citation feedback | Copy APA, choose Chicago: previous text and “copied” message remain. Abort next actual citation request: old successful citation still visible. Both viewports. Result state was never invalidated. | `components/CitePanel.tsx`: clear text/status/message on style change, clear text at request start, disable style selection while loading. Browser regression validates both failures and subsequent actual API requests. |
| Pre-hydration image completion | Reload loaded native original: correct image but no highlight. Intercept original image failure: broken image remains “Cargando imagen…” without retry. Native load/error finished before React handlers attached. | `components/ReaderImage.tsx`: stable callback ref reconciles `complete`/`naturalWidth` at mount. Reload highlights, intercepted failure, actual retry request and page-source recovery pass. |
| Duplicate missing-book chrome | `/libro/no-such-book` showed two site headers and two footers. Root not-found includes chrome while the site layout already supplies it. | `app/(sitio)/libro/[libroId]/not-found.tsx`: segment-local `MessagePage` with functioning library recovery link, no extra chrome. Both viewports now have one navigation/footer. |

Persisted regression source: web `scripts/check-routing-regressions.mjs`.
It accepts a real Playwright page and fixtures on these ports; it does not mock
Next Link, routing or components. Generated CLI function is
`E/regression-browser.js`; actual invocation:
`playwright-cli -s=pwa-routing run-code --filename=<E>/regression-browser.js`.

Rollback boundary: the three component edits, new book not-found file and
regression script form this batch; no extraction/API behavior changes belong
to it. Existing unrelated repository changes were preserved.

## Actual desktop/mobile matrix

Desktop **1440×900** and mobile **390×844**, same Chromium browser; mobile is
viewport emulation, not a physical device or Safari certification. Every row
below was independently exercised in both viewports.
Actual browser: **Headless Chromium 155.0.8059.39** on Windows;
`E/identity-results.json` records the version and user agent.

| Case / concrete URL or action | Desktop | Mobile |
|---|---|---|
| `/` form submits `hypothesis` → `/buscar?q=hypothesis` | Pass | Pass |
| `/biblioteca`: genre Investigación + author He, submit/clear/Back/reload/Forward | Pass | Pass |
| `/buscar?q=hypothesis`: same filters and URL/field history checks | Pass | Pass |
| `/biblioteca` BookCard → `/libro/resnet` index Link → `/libro/resnet/pagina/3` | Pass | Pass |
| Reader 3 `q=%22denotes%20ReLU%22&ver=imagen`: one exact match, two real rectangles; text toggle shows newline-spanning mark | Pass | Pass |
| Reader 3 `q=%22residual%20learning%22`: four matches; next/reload/Back/Forward retain selection 2; page 4 recomputes zero matches | Pass | Pass |
| Search hypothesis → actual original-image result Link: query recomputed, correct native mark, reload | Pass | Pass |
| Image/text toggle then previous/next page links preserve view/query and change original source | Pass | Pass |
| Browser interception aborts original PNG; remove interception, click retry → actual `original-3.png?retry=1` loads | Pass | Pass |
| Original 3 image failure → actual page-next Link → original 4 loads, error clears | Pass | Pass |
| APA/Chicago/MLA: six total real API 200 responses, CORS origin checked, rendered text and actual clipboard equal API | Pass | Pass |
| Deny clipboard write in the actual isolated browser context; selectable citation and honest manual-copy message | Pass | Pass |
| Reader 3 → 4 resets citation/style/feedback; new APA cites page 4 | Pass | Pass |
| Focused citation select arrows stay put; unfocused reader arrow navigates; search input arrows and Enter work | Pass | Pass |
| Invalid page/resource fallbacks and recovery links, statuses distinguished below | Pass | Pass |
| Seven fresh pages: loaded supports/notes; BERT 15 original/fallback and missing vector-label query remain honest | Pass | Pass |
| Owned API stopped: reader boundary shown; API restored, actual Reintentar refetches reader | Pass* | Pass* |
| Owned API stopped: library ErrorNotice; API restored, actual Reintentar refreshes catalog | Pass | Pass |
| Owned API stopped: search ErrorNotice; API restored, actual Reintentar restores hypothesis results | Pass | Pass |

At stable ordinary routes and recovered outage routes: one principal navigation,
one footer, no horizontal overflow. Enabled controls in the exercised paths
performed their stated action. Boundary buttons, index links, recovery links,
match links, toggle, image retry, filters and copy were real interactions.

### Status codes and Next behavior

Both viewports: reader page `0`, `nope`, `999`, missing-book reader and missing
book index render not-found UI with **HTTP 200**; `/no-such-route` returns
**404**. The API itself returns 404 for absent records. HTTP 200 alone therefore
does not establish that a page exists. Installed Next
`dist/docs/01-app/03-api-reference/03-file-conventions/not-found.md` explicitly
documents the streaming 200 distinction.

Installed `error.md` documents **`retry` stable since 16.3**: refetch + rerender.
`reset` clears local boundary state without refetching. Current `app/error.tsx`
already uses the correct `retry` prop, verified through actual outage recovery;
no speculative reset patch was made. Library/search `ErrorNotice` refresh also
works against newly restarted API processes.

**\*Outage console limit:** each deliberately failed reader server render emitted
two recoverable React **#419** errors when recovery ran (four total). Installed
React production source line 7393 and matching development source line 11500
identify this as unfinished server Suspense switching to client rendering,
not an ordinary-route content mismatch. They are preserved in
`outage-after-cli.log` and `outage-recovered-results.json`; they were not hidden
or “fixed” by changing framework code. Search/library recovery had zero captured
page errors. Ordinary matrix had only four intentionally aborted image requests
and two expected unknown-route 404 messages; no chunk 404, page errors or
hydration mismatch were observed there.

## Evidence and exact checks

- `baseline-results.json`, `baseline-trace.zip`, `baseline-*.png`: original
  filter/citation failures. Original invalid-page assertion expected the wrong
  heading; actual “Página no disponible” was correct, not a source defect.
- `matrix-results.json`, `final-matrix-trace.zip`, `after-*.png`: image hydration
  and duplicate-chrome failures before their fixes. Also preserve verifier
  failures caused by URL/render timing, a title Link clicked during keyboard
  setup, permission context targeting and missing interception cleanup.
- `verified-matrix-results.json`: 29/32 passed initially. Remaining three were
  verifier errors: two multiline checks incorrectly expected one `data-target`
  instead of one per rectangle; mobile Forward checked during transient route
  activity before the new form settled. `targeted-results.json` has **3/3**
  actual corrected checks; no source patches followed. Consolidated ordinary
  coverage is **32/32**, not a claim that the earlier attempts never failed.
- `outage-before-results.json`, `outage-recovered-results.json`, search outage
  before/after results and traces: **6/6** functional outage/retry cases.
  First desktop reader retry recovered before the strict console assertion
  stopped the verifier; its click and errors remain in the outage trace/log.
- `regression-verified-results.json`: **12/12** source regression checks.
- `checks.json`: final **38/38** functional cases and source identity.
- `verified-build.log`, `verified-lint.log`: both pass.
- `uv run pytest --basetemp <E>/pytest-temp`: **102 passed, 0 skipped**.
  `uv run python -m compileall -q app scripts`: pass.
- `node --test scripts/test-reader-image.mjs scripts/test-reader-matches.mjs`:
  **8 passed**; existing Node module-type warning remains.
- Screenshots and traces live under ignored E; browser artifacts are preserved,
  including failed attempts. No PDFs or earlier evidence were deleted.
  Generated CLI snapshots/logs are archived in `E/cli-session-artifacts`.

## Explicit limits / blocked coverage

- The original routing batch used only seven measured pages and could not certify
  **Empezar a leer** or whole-book index pagination. The final slice below closes
  real page-1 CTA coverage using existing full snapshots, and tests the 60-item
  pagination boundary with explicitly synthetic stored data. It does not certify
  a real PDF book longer than 60 pages. Original measured-page links and contiguous
  ResNet 2→3→4 navigation remain the earlier evidence.
- BERT 15 is a **whole-page fallback**, not a detected complete figure.
  `"Question Answering Tasks"` remains unsearchable because its labels are
  vector outlines without native Unicode. Five native supports and one fallback
  load in the inspected pages; this adds routing evidence, not universal figure
  or reading-order certification. See `FIX_CONFIRMED_PDF_DEFECTS.md`.
- No physical-mobile, Safari, production deployment, full-catalog validation,
  clipboard cross-browser certification or universally clean outage console.
- Existing services/records were not used to certify this source. Only owned
  isolated API processes were stopped/restarted for outages, and the owned
  isolated Next process was replaced between builds. Readiness was bounded to
  15 seconds. Existing ports/processes, user `.env`, originals and prior evidence
  were preserved. No agents, lifecycle workflow, commits, deployment or live OCR.
  Owned verification servers and the owned browser session were stopped after
  the batch; fixture DB and evidence are retained. URLs above identify the
  tested environment, not currently running services.

**skill_resolution:** both AGENTS and requested validation/fix documents read;
exact requested playwright-cli, web-design-guidelines (including guidelines.md)
and gitnexus-debugging skills loaded before work. CodeGraph attempted first for
both projects, unavailable without indexes; directed fallback, no initialization.
Installed Next docs and implementation checked, supplemented by Context7;
installed React source checked for #419. work-unit-commits read before fixes,
cognitive-doc-design before this report.

## Final book-index validation

11 October 2026. Exactly three named browser checks per viewport, desktop
1440×900 and mobile 390×844 (Chromium viewport emulation). **Baseline 2/6;
after the reproduced source fix 6/6**, zero captured browser page errors.

| Named check | Desktop | Mobile | Evidence boundary |
|---|---|---|---|
| Library BookCard → index → actual **Empezar a leer** → page 1 | Pass | Pass | Attention, BERT and ResNet; original snapshot text matches the real API, original PNG loads. |
| Page-index pagination, out-of-range and empty recovery | Pass | Pass | Explicitly labeled synthetic 61-page book: real Next Link from index 1 (60 entries) to index 2 (entry 61), then actual reader 61. Out-of-range recovery tested on genuine 12-page ResNet and synthetic 61-page book; zero-page synthetic book hides CTA, explains absence and links back to library. |
| Missing-first-page book CTA | Pass | Pass | Derived, explicitly labeled ResNet fixture retains genuine pages 2–12. CTA now opens actual page 2; no invented page 1. |

### Reproduced source fix

Only web `app/(sitio)/libro/[libroId]/page.tsx` changed in this slice:

- CTA previously hardcoded page 1 and reached “Página no disponible” in the
  missing-first fixture. It now uses the lowest actual indexed page, including
  when visiting later index slices; absent indexed pages means no reading CTA.
- Real `/libro/resnet?pagina=999` showed an empty grid with no direct recovery;
  synthetic `/libro/synthetic-pagination?pagina=999` additionally displayed
  “Página 999 de 2”. Shared `EmptyState` now explains the empty/out-of-range
  state and provides a direct first-index or library link. Empty slices omit
  the misleading pagination controls. Baseline zero-page dead CTA also removed.

This route-only edit is the rollback boundary. Browser validation was rerun
against a newly built and restarted isolated production service; no permanent
test suite was added to imply universal coverage.

### Isolated data, hashes and checks

- Evidence **F**: `_media/pwa-index-20261011/` (ignored). Web port **3026**,
  API port **8026**, both loopback; fresh `next start` build ID
  **`O8EUFdlPHGCnCDOKEVYjC`**. Current-source build and lint both pass.
  Isolated build copy uses only the same dependency-junction `turbopack.root`
  adjustment as the earlier environment; user environment files are excluded.
- Guarded fresh DB **`biblioteca_pwa_index_20261011_isolated`** at local Mongo.
  Seed refuses an existing DB. Full `phase2-evidence/after-final/{book}.json`
  snapshots supply **43 genuine pages: 15 Attention + 16 BERT + 12 ResNet**.
  Seven delivery corrections replace their original page numbers with real
  text/geometry/reading segments. Media URLs point to existing files; no media
  generation, extraction, OCR or original re-ingestion occurred.
- `F/seed.json` records SHA-256 of source book snapshots, reports, original PDFs
  and referenced PNGs. Phase2 report SHA-256:
  `41106c2e1f8bd96806933083187757e2e24d71755c7a26f424fc630c9e0416de`;
  corrected report SHA-256:
  `8e6964904508a4d291530b318d39596da5a76d22f66060619240c48178745adf`.
  Final checks revalidate all recorded hashes, page-1 snapshot text/positions and
  the seven stored overlays' text/positions/reading/motor against their sources.
- `baseline-results.json`, `baseline-supplemental.json` and CLI snapshots preserve
  failures; `verified-results.json` and `verified-cli.log` record scoped browser
  passes. `verified-source.json` hashes current app/components/lib/scripts;
  `checks.json` validates both delivered source and build-copy identity and records
  API source hashes. `verified-build.log` and `verified-lint.log` preserve checks.
- Required API checks: **102 passed, zero skipped** (`F/pytest.log`), compileall
  pass (`F/compileall.log`). Tests use separately guarded
  **`biblioteca_pwa_index_20261011_tests`** and isolated media/basetemp, never the
  browser fixture DB or existing user DB. The test DB is removed by pytest's
  existing cleanup; browser fixture DB and evidence are retained.
- Owned API/web processes and browser session stopped after validation. Existing
  services, databases, PDFs and prior evidence were preserved. No agents, review
  lifecycle, deployment, live OCR, extraction edits or commits.

**Final skill_resolution:** both project AGENTS and requested skills
`playwright-cli`, `web-design-guidelines` (full `guidelines.md`) read first;
`gitnexus-debugging`, `work-unit-commits` and `cognitive-doc-design` loaded when
applicable. CodeGraph unavailable without an index; directed reads used with no
initialization. Installed Next Link documentation and Context7 checked. Scope
remains these three flows, not full-catalog, real >60-page PDF, physical-mobile,
Safari, extraction quality or deployment certification.
