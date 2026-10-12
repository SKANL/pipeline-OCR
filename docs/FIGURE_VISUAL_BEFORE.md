# Figure visual baseline — 2026-10-11

> Relocation note: commands below record the original run. Current API modules
> are `tests.tools.<name>`, and inputs are in `tests/fixtures/real-pdfs/`.
> See [fixture mapping](../tests/fixtures/README.md); historical evidence stays in place.

Captured before changing extraction using `uv run python -m scripts.figure_evidence before`.
Evidence is immutable under `_media/figure-evidence/before/`: `report.json` includes
SHA-256 fixture identities, source/retained blocks, candidate boxes, saved crops and
page dimensions. `*/raw/paper.json` preserves the converter output. No OCR or
database ingestion was used.

## Visual observations (image tool inspection)

| Same fixture / PDF page | Full page and candidate evidence | Observed defect |
| --- | --- | --- |
| BERT 3 | `bert/paginas/3.png`, `bert/candidates-3.png` | Token boxes are valid pieces of the pre-training/fine-tuning diagram. Larger BERT rectangles also omit outer arrows, embeddings and labels. Area is not evidence of noise. |
| BERT 15 | `bert/paginas/15.png`, `bert/candidates-15.png` | Four task panels are composite artwork; token and BERT crops do not reconstruct complete panels. |
| Attention 3 | `attention/paginas/3.png`, `attention/candidates-3.png` | Architecture crop contains the diagram; its caption is separately present on the page. |
| Attention 4 | `attention/paginas/4.png`, `attention/candidates-4.png` | Two panels: converter gives right panel before left. Titles above the panels are outside these crops. |
| Attention 11, 12 | `attention/paginas/11.png`, `attention/paginas/12.png` | Bibliography pages; no candidates and therefore no candidate sheets. No missing diagram observed here. |
| ResNet 2 | `resnet/paginas/2.png` | Residual building-block diagram visible; converter detects no image region. |
| ResNet 3 | `resnet/paginas/3.png` | Prose/formulas; no image candidates. |
| ResNet 4 | `resnet/paginas/4.png` | Tall three-network comparison visible; converter detects no image region. |
| ResNet 6 | `resnet/paginas/6.png` | Two residual-block diagrams and tables visible; converter detects no image region. |

Paths in the table are relative to `_media/figure-evidence/before/`.
Candidate counts are diagnostic inventory only, never a quality score.

## Source-confirmed failure paths

- `_significant_figures` discards every region below 2% without visual classification.
- `_blocks_outside_figures` discards text by center inclusion **before** crop/save,
  so unsuccessful crops can remove searchable content.
- Reader puts all figures after the prose, stretches small crops to full width,
  has no intrinsic crop dimensions/captions or crop error recovery.
- Reader toolbar stores URL-derived view state and failure state locally; soft
  navigation can retain old image failures and lose view intent on a no-image page.
- LocalStorage writes bypass the existing `path()` containment check.

## Conservative repair boundary

Keep every valid small crop and semantic/source order metadata. Do not automatically
merge nearby components: these fixtures do not establish a robust grouping rule.
Do not delete any source text: box containment does not prove text is a diagram label.
Flag overlapping crops as potentially fragmented; show the original page by default
for these and for pages without detected crops. All other crops remain explicitly
unverified and provide original-page access. Rotation and shifted crop/media boxes
must use a guarded original-page fallback rather than a guessed transform.
