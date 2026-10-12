"""Local object diagnostics for confirmed PDF defects; no OCR or database."""
import json
from pathlib import Path
import pypdfium2 as pdfium
import pypdfium2.raw as raw
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]

def main():
    destination = ROOT / '_media/fix-confirmed-pdf-20261011-delivery'
    for name, numbers in {'bert': [15]}.items():
        with pdfium.PdfDocument(str(ROOT / 'tests/fixtures/real-pdfs' / name / 'paper.pdf')) as doc:
            for number in numbers:
                page = doc[number-1]
                textpage = page.get_textpage()
                objects = []
                for obj in page.get_objects(max_depth=20):
                    box = obj.get_bounds()
                    item = {'type': obj.type, 'bbox': box}
                    if obj.type == raw.FPDF_PAGEOBJ_TEXT:
                        buffer = raw.FPDFTextObj_GetText(obj, textpage, None, 0)
                        import ctypes
                        data = (ctypes.c_ushort * ((buffer+1)//2))()
                        raw.FPDFTextObj_GetText(obj, textpage, data, buffer)
                        item['text'] = bytes(data)[:buffer].decode('utf-16-le').rstrip('\0')
                    objects.append(item)
                if name == 'bert' and number == 15:
                    target = destination / 'bert/path-only-15.png'
                    assert not target.exists()
                    labels = ['Sentence Pair Classification Tasks', 'Single Sentence Classification Tasks',
                              'Question Answering Tasks', 'Single Sentence Tagging Tasks', 'SQuAD v1.1', 'CoNLL-2003 NER']
                    task_objects = [o for o in objects if any(s in o.get('text', '') for s in labels)]
                    # In-memory diagnostic only. Original bytes are never saved.
                    for obj in page.get_objects(max_depth=20):
                        if obj.type == raw.FPDF_PAGEOBJ_TEXT:
                            assert raw.FPDFTextObj_SetTextRenderMode(obj, 3)
                        elif obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                            obj.set_matrix(pdfium.PdfMatrix(0, 0, 0, 0, 0, 0))
                    page.render(scale=150/72).to_pil().save(target)
                    diagnostic = {'native_task_objects': task_objects, 'object_types': dict(Counter(o['type'] for o in objects)),
                                  'missing_labels': labels, 'method': 'All native text made invisible; all image matrices zeroed in memory. Only paths remain visible.',
                                  'original_sha256': __import__('hashlib').sha256((ROOT / 'tests/fixtures/real-pdfs/bert/paper.pdf').read_bytes()).hexdigest()}
                    (destination / 'bert/missing-labels.json').write_text(json.dumps(diagnostic, indent=2), encoding='utf-8')
                    print(json.dumps(diagnostic, indent=2))
                textpage.close()
                page.close()

if __name__ == '__main__':
    main()
