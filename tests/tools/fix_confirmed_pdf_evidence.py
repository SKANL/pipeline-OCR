"""Reproduce named failures and capture corrected local artifacts, without DB/OCR."""
import hashlib
import json
from collections import Counter
from pathlib import Path
from unittest.mock import patch
from app.services import ingest, locator, pdf_layout, render
from app.services.storage import LocalStorage

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / '_media' / 'fix-confirmed-pdf-20261011-delivery'

def main():
    assert not DEST.exists(), 'Refuse overwrite of evidence'
    baseline = json.loads((ROOT / '_media/validation-complex-20261011/results.json').read_text(encoding='utf-8'))
    DEST.mkdir()
    report = {}
    for name, numbers in {'attention': [4], 'bert': [3, 15], 'resnet': [2, 3, 4, 6]}.items():
        path = ROOT / 'tests/fixtures/real-pdfs' / name / 'paper.pdf'
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == baseline[name]['sha256']
        with patch.object(pdf_layout, 'reorder_native', lambda chars, positions, *args: (''.join(chars), positions, [])):
            before = locator.extract_positioned_pdf(path)
        after = locator.extract_positioned_pdf(path)
        report[name] = {'sha256': digest, 'pages': {}}
        for number in numbers:
            prior = baseline[name]['pages'][str(number)]
            assert before[number-1]['texto'] == prior['native']['texto']
            assert Counter(before[number-1]['texto']) <= Counter(after[number-1]['texto'])
            assert Counter((before[number-1]['texto'][p[0]], *p[1:]) for p in before[number-1]['posiciones']) == Counter((after[number-1]['texto'][p[0]], *p[1:]) for p in after[number-1]['posiciones'])
            data = render.render_pdf_page(path, number-1)
            directory = DEST / name
            directory.mkdir(exist_ok=True)
            (directory / f'original-{number}.png').write_bytes(data)
            (directory / f'before-{number}.txt').write_text(before[number-1]['texto'], encoding='utf-8')
            (directory / f'after-{number}.txt').write_text(after[number-1]['texto'], encoding='utf-8')
            width, height = render.pdf_page_geometry(path, number-1)
            candidates = [{'bbox': c['bbox'], 'orden': c.get('orden')} for c in prior['crops']]
            before_crops = ingest._crop_figures(path, number, candidates, name+'-before', number,
                LocalStorage(DEST), 150, width, height, page_png=data, blocks=prior['blocks'])
            supports = pdf_layout.compose_visual_supports(after[number-1]['soportes'], candidates)
            crops = ingest._crop_figures(path, number, supports, name+'-after', number,
                LocalStorage(DEST), 150, width, height, page_png=data, blocks=prior['blocks'])
            record = {'before_count': len(before_crops), 'after_detected': sum(c.get('detectada') is True for c in crops),
                      'after_count': len(crops), 'uncovered_candidates': sum(c.get('tipo') != 'soporte_nativo' for c in crops),
                      'fallbacks': sum(c.get('detectada') is False for c in crops), 'crops': crops,
                      'after': after[number-1]}
            queries = {('resnet', 3): ['"denotes ReLU"', 'hypothesis'],
                       ('resnet', 6): ['"We have shown that parameter-free"', '"ResNet-152 21.43 5.71"', '"ResNet-152 19.38 4.49"'],
                       ('bert', 15): ['"Question Answering Tasks"', '"SQuAD v1.1"', '"CoNLL-2003 NER"', '"Note that"']}.get((name, number), [])
            record['queries'] = {q: locator.locate_matches(after[number-1], q)[0] for q in queries}
            for q, hits in record['queries'].items():
                if (name, number) != ('bert', 15) or q == '"Note that"':
                    assert hits and all(hit['precision'] == 'exacta' for hit in hits), q
                else:
                    assert not hits, q
            report[name]['pages'][number] = record
            print(name, number, 'before', len(before_crops), 'after', record['after_detected'], 'fallbacks', record['fallbacks'],
                  'uncovered', record['uncovered_candidates'], 'components', [len(c.get('componentes', [])) for c in crops],
                  'flow', after[number-1]['lectura'])
        assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    text3 = report['resnet']['pages'][3]['after']['texto']
    text6 = report['resnet']['pages'][6]['after']['texto']
    (DEST / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    assert 'denotes\nReLU' in text3
    assert 'We have shown that\nparameter-free' in text6
    assert 'ma-14Note' not in report['bert']['pages'][15]['after']['texto']
    # Reading evidence is rendered directly from measured strings/ranges, not
    # a mock browser or a reconstruction of the original page.
    from PIL import Image, ImageDraw, ImageFont
    import textwrap
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 20)
    for name, number, anchor in [('resnet', 3, 'in which'), ('resnet', 6, 'We have shown that'), ('bert', 15, 'GLUE submission')]:
        image = Image.new('RGB', (1250, 780), 'white')
        draw = ImageDraw.Draw(image)
        for column, stage in enumerate(('before', 'after')):
            text = (DEST / name / f'{stage}-{number}.txt').read_text(encoding='utf-8')
            start = text.index(anchor)
            excerpt = text[start:start+550]
            if stage == 'after':
                page = report[name]['pages'][number]['after']
                span = next(span for span in page['lectura'] if span['inicio'] <= start < span['fin'])
                excerpt = text[start:min(start+550, span['fin'])]
            x, y = 20+column*625, 20
            draw.text((x, y), f'{name} {number} — {stage}: texto nativo', fill='black', font=font)
            y += 45
            for line in excerpt.splitlines():
                for wrapped in textwrap.wrap(line, width=54) or ['']:
                    draw.text((x, y), wrapped, fill='black', font=font)
                    y += 28
            if stage == 'after':
                page = report[name]['pages'][number]['after']
                note = next(span for span in page['lectura'] if span['tipo'] == 'nota')
                draw.text((x, 600), 'Notas al pie (sección independiente):', fill='black', font=font)
                for i, line in enumerate(textwrap.wrap(page['texto'][note['inicio']:note['fin']].replace('\n', ' '), width=54)[:4]):
                    draw.text((x, 635+i*28), line, fill='black', font=font)
        image.save(DEST / name / f'reading-{number}.png')
    print('PASS baseline reproduction, unchanged originals, named reading continuations', DEST)

if __name__ == '__main__':
    main()
