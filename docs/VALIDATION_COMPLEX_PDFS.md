# Complex PDF validation — first slice, 2026-10-11

> Relocation note: recorded paths/results are historical. Current input mapping
> is [tests/fixtures](../tests/fixtures/README.md), API tools are `tests.tools.<name>`.
> No historical evidence, backups or media URLs were moved.

**Result:** original-page renders preserve the inspected diagrams, but complete
figure detection and logical reading order do **not** pass. Rotation/shifted-box
fallback passes the deterministic supported/unsupported cases below.
**source edit=false** (production source). Only this report and local evidence /
scratch fixtures were created. No ingestion, remote OCR/Mistral, deployment,
commits, server changes, agents, or review lifecycle commands.

## Evidence and method

Evidence root **E**: `_media/validation-complex-20261011/` (ignored by `.gitignore`).
Scratch root **S**:
`C:\Users\angua\AppData\Local\Temp\opencode\complex-pdf-validation-20261011\`.
All paths below are relative to E unless stated otherwise. PNGs were opened with
the image-reading tool, including the full pages, contact sheets, representative
full-resolution crops, and all synthetic variants.

Started with `PHASE2_LOCALIZATION.md`, `FIGURE_VISUAL_BEFORE.md` and current
`locator.py`, `render.py`, `structure.py`, and figure helpers in `ingest.py`.
One native extraction and one structure conversion per original; no repeated
large evidence sweep. Selected pages were freshly rendered at 150 DPI and crops
generated with current `_significant_figures` / `_crop_figures` helpers.
The original Attention/BERT/ResNet files still have 15/16/12 pages; SHA-256
identities match the immutable figure-before report. `results.json` preserves
text, boxes, crop records, and hashes; `inventory.json` records actual PDF objects.

## Diagram pass/fail matrix

| Original vs current crops | Complete figure aid | Actual observation |
|---|---|---|
| `attention/original-3.png`, `attention/figuras/3-0.png` | PASS, this sample | One complete raster architecture: inputs, positional encodings, both stacks, arrows and output labels visible. Caption outside crop, correctly associated separately. Record remains `no_verificado`, not globally certified. |
| `attention/original-4.png`, `attention/crops-4.png` | FAIL for complete context | Two panel rasters, now left then right. Internal Q/K/V and h labels present, but both panel headings absent from crops. Shared Figure 2 caption exists in text; only right crop receives it. |
| `attention/original-11.png`, `attention/original-12.png` | N/A | Bibliographies, not diagram pages; zero candidates consistent with visual inspection. |
| `bert/original-3.png`, `bert/crops-3.png` | FAIL, fragmented composite | 14 crops: token tiles and two central BERT strips. Outer task frames, connecting arrows, yellow embeddings and input/context labels do not form a complete aid. `bert/figuras/3-12.png` visibly truncates yellow embedding boxes/labels at its bottom. |
| `bert/original-15.png`, `bert/crops-15.png` | FAIL, fragmented composite | 24 crops cannot reconstruct four task panels. Full-resolution `bert/figuras/15-22.png` cuts embeddings. Task labels and class/span arrows are outside these crops; Figure 4 caption remains in prose. |
| `resnet/original-2.png`, `resnet/original-4.png`, `resnet/original-6.png` | FAIL, vector not detected | Residual shortcut block, three-network comparison, and paired bottleneck blocks visible; zero candidates on all three. PDFium inventory contains paths/text but no image objects on these pages. |
| `resnet/original-3.png` | N/A | Two-column prose/formulas, not a missing diagram. |

BERT's small images are meaningful components, not proven noise. All 38 BERT
records are `no_verificado`: geometric non-overlap does not establish semantic
completeness. Fresh full-page PNGs retain the omitted relationships, titles and
captions. **Original-page meaning preservation passes visually for these pages;
figure-detector completeness fails.** Browser selection/routing is not tested.

## Reading order and missing visible text

Compare each `original-N.png` with the matching `text-N.txt`:

- **ResNet 3 — FAIL, footnote interleaving.** Original left-column bottom
  continues into right-column top: “in which σ denotes ReLU [29]”. Extracted
  lines 38–40 insert “2This hypothesis, however, is still an open question.
  See [28].” between “σ denotes” and “ReLU [29]”. Both texts exist, but the
  sentence is interrupted.
- **ResNet 6 — FAIL, figure/column interleaving.** Left-column bottom “We have
  shown that” continues as “parameter-free, identity shortcuts help with
  training” in the right column. Extracted lines 48–62 insert diagram labels
  (`3x3, 64`, `relu`, `64-d 256-d`) and the Figure 5 caption between them.
  Tables themselves retain row order in this sample: Table 3 includes
  `ResNet-152 21.43 5.71`; Table 4 includes `ResNet-152 19.38 4.49`.
  No table-row/prose interleaving observed here.
- **BERT 3 — sampled prose columns PASS.** Left “There is mini-” connects to
  right “mal difference” as `mini-mal difference`; subsequent architecture
  prose follows. Figure labels are not in a logical panel-reading sequence:
  `Question Paragraph` / `Start/End Span` precede `Pre-training Fine-Tuning`.
- **BERT 15 — visible-label retention FAIL.** Original panel labels
  “Sentence Pair Classification Tasks”, “Single Sentence Classification Tasks”,
  “Question Answering Tasks”, “Single Sentence Tagging Tasks”, “SQuAD v1.1”
  and “CoNLL-2003 NER” are all absent from native `texto`. Checked examples
  are also absent from structure blocks (`edges.json`). Main task paragraphs
  retain column sequence, but line 95 glues the unfinished body to footnote 14:
  `predicted the ma-14Note that...`.
- **Attention 4 — image-only labels absent.** `MatMul`, `SoftMax`, `Mask (opt.)`
  are visible in panel rasters but absent from extracted page text. Heading,
  caption and prose remain. Render access preserves these labels visually,
  not as searchable native text.

Proven mechanisms: `locator.py:97–126` preserves PDFium's native sequence without
logical column/footnote reordering; figure helpers consume converter candidates,
not a reconstruction of vector/composite artwork. The precise representation
causing BERT's absent task labels was not established; no speculative root cause.
Text coverage alone is not a reading-order or semantic-retention verdict.

## Rotation / CropBox / invalid-box matrix

Fixture: deterministic 400×300-point PDF, Helvetica 18, **Grace faith hope** at
(80,180), visible surrounding rectangle. Shifted CropBox: (40,30,360,270).
Fixtures in S; image names `rotate-R-crop-C.png` in E, C=0/1.

| Cases | Result |
|---|---|
| 0°, no shift | PASS: 14 non-space glyph positions, one `exacta` phrase match; 800×600 PNG at 144 DPI. |
| 90° / 180° / 270°, no shift | PASS conservative fallback: phrase retained, zero positions, `sin_localizar`, explicit rotated/shifted warning; 600×800 / 800×600 / 600×800 renders. |
| Shifted crop at 0° / 90° / 180° / 270° | PASS conservative fallback: same phrase retained, zero positions, warning and `pagina_original` crop record; 640×480 / 480×640 / 640×480 / 480×640 PNGs. |
| Seven invalid region boxes | PASS rejection: zero width, reversed, NaN, infinity, boolean, negative origin and out-of-page bound all raise `ValueError`. |
| Four page CropBox edges | OBSERVED, not universal raw-box rejection: zero-width and oversized boxes become effective MediaBox (0,0,400,300), so geometry remains enabled without warning. Reversed coordinates normalize to shifted effective box; negative shifted box clips to MediaBox intersection. These two disable geometry and warn. All four render the phrase (`edge-*.png`). |

The production guards inspect **effective** `get_bbox()` / size / rotation, not
raw CropBox validity. This explains the zero/oversized behavior; `edges.json`
records requested, read-back and effective boxes. No guard was removed.

## Checks, reproduction and limits

From `C:\code\pipeline-OCR`, with parent directories verified:

```powershell
uv run python "C:\Users\angua\AppData\Local\Temp\opencode\complex-pdf-validation-20261011\validate.py"
uv run python "C:\Users\angua\AppData\Local\Temp\opencode\complex-pdf-validation-20261011\checks.py"
uv run python "C:\Users\angua\AppData\Local\Temp\opencode\complex-pdf-validation-20261011\edges.py"
```

First command refuses to overwrite E; a fresh reproduction requires a new
evidence namespace in the scratch script. No scratch script is production code.
`checks.py` ran `uv run pytest --basetemp <S>\pytest-temp`: **95 passed in
22.65s**, zero skipped. `uv run python -m compileall -q app scripts`: **PASS**.
Logs: `tests.log`, `compileall.log`, `checks.json`. Tests explicitly use
`mongodb://127.0.0.1:27017` / `biblioteca_validation_complex_20261011_slice1`,
asserted loopback and different from configured application DB before execution;
test media/bytecode caches are under S. No user data was reingested.

**skill_resolution:** API AGENTS read; requested `pdf`, `playwright-cli`, and
`web-design-guidelines` plus `guidelines.md` read; `cognitive-doc-design` and
`graphify` loaded. No graph build or browser workflow invoked. CodeGraph attempted
first, unavailable because no index; targeted reads used without initialization.

**Blockers/limits:** no execution blocker for this slice. Complete composite/vector
aids, searchable image-only labels and logical footnote/figure separation remain
unresolved. Real production PWA navigation is reserved for the separate task;
no mocked Next Link result is used as routing evidence here.
