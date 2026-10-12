# Real PWA routing validation — partial evidence

> Relocation note: recorded paths/ports remain historical evidence. Current web
> harnesses live in web `tests/tools/`, web port is 3010 and API port is 8000.
> Real inputs live in API [tests/fixtures](../tests/fixtures/README.md).

This is a production Next routing check through actual browser interactions, not the mocked component fixture. No deployment, remote OCR, production source edits, or data deletion were performed.

## Environment

- Web: `http://localhost:3010`.
- Reader media: local API at `http://localhost:8010`.
- Browser: Chrome DevTools; desktop followed by mobile emulation at 390 × 844.
- The first request failed with `ERR_CONNECTION_REFUSED`. A cancelled operational task subsequently started local services. The retry succeeded; the initial failure is an environment availability observation, not proof of a source defect.

## Actual interactions observed

1. Navigated to `/buscar?q=transformer`: 17 results and working links rendered.
2. Clicked the Attention page 1 **Ver página original** result link.
3. Reader displayed the original, native-glyph precision label and three matches.
4. Clicked **Coincidencia siguiente**: URL acquired `coincidencia=1`; UI displayed match 2 of 3.
5. Reloaded: selection 2 of 3 persisted, original PNG loaded with dimensions 1275 × 1651.
6. Used browser back and forward: navigated between the first and second match URLs.
7. Emulated mobile 390 × 844 and clicked **Página siguiente**.
8. Reader transitioned to page 2, retaining `q=transformer&ver=imagen`, dropping the prior page-specific selection, and displaying match 1 of 5.
9. Page 2 original loaded from its own URL. No horizontal overflow; one principal navigation and one footer.
10. Error/warning console inspection, including preserved navigation messages: no errors or warnings found.

## Not yet validated in this real-routing slice

- Image network failure, retry and subsequent source-change recovery.
- Clipboard permissions, copy/fallback and citation state between pages.
- Filter submission/clear with browser history.
- Keyboard behavior while inputs have focus.
- Invalid pages and API-outage recovery.
- Full route matrix repeated independently on both viewports.

Do not extrapolate these sampled successful flows to universal routing correctness. Complex PDF extraction failures remain documented in `VALIDATION_COMPLEX_PDFS.md` and are not fixed by this browser validation.
