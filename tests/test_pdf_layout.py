"""Deterministic regressions for real native composite and reading boundaries."""
from collections import Counter
from pathlib import Path
from io import BytesIO

from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from app.services import ingest, locator, render
from app.services.storage import LocalStorage
from app.services.pdf_layout import reorder_native


def test_shared_caption_keeps_both_panels_and_headings(tmp_path):
    path = tmp_path / 'panels.pdf'
    c = canvas.Canvas(str(path), pagesize=(600, 800), invariant=1)
    image = ImageReader(Image.new('RGB', (80, 100), 'blue'))
    c.drawImage(image, 80, 550, 80, 100)
    c.drawImage(image, 330, 530, 80, 120)
    c.drawString(70, 665, 'Scaled Dot-Product Attention')
    c.drawString(325, 665, 'Multi-Head Attention')
    c.drawString(70, 510, 'Figure 2: (left) Scaled Dot-Product Attention. (right) Multi-Head Attention.')
    c.drawString(70, 470, 'Unrelated prose must remain outside the visual support.')
    c.save()
    page = locator.extract_positioned_pdf(path)[0]
    support, = page['soportes']
    assert support['detectada'] is True
    assert 'Figure 2:' in support['pie']
    assert support['bbox'][0] <= 70 and support['bbox'][3] >= 665
    assert support['bbox'][1] > 470
    visual = next(s for s in page['lectura'] if s['tipo'] == 'visual')
    assert 'Multi-Head Attention' in page['texto'][visual['inicio']:visual['fin']]
    assert 'Unrelated prose' in page['texto'][:visual['inicio']]


def test_native_form_vector_keeps_arrows_and_caption(tmp_path):
    path = tmp_path / 'vector.pdf'
    c = canvas.Canvas(str(path), pagesize=(600, 800), invariant=1)
    c.beginForm('residual', 0, 0, 150, 120)
    c.rect(10, 30, 100, 30)
    c.drawString(20, 40, 'weight layer')
    c.line(60, 100, 60, 60)
    c.line(60, 60, 55, 65)
    c.line(60, 60, 65, 65)
    c.endForm()
    c.saveState()
    c.translate(100, 550)
    c.doForm('residual')
    c.restoreState()
    c.drawString(90, 530, 'Figure 2. Residual learning: a building block.')
    c.save()
    page = locator.extract_positioned_pdf(path)[0]
    support, = page['soportes']
    assert support['detectada'] and support['bbox'][3] >= 650
    assert 'Residual learning' in support['pie']
    data = render.crop_page_png(render.render_pdf_page(path, 0), support['bbox'], 600, 800)
    assert Image.open(BytesIO(data)).height > 240


def test_column_continuation_footnote_and_remapped_glyphs(tmp_path):
    path = tmp_path / 'columns.pdf'
    c = canvas.Canvas(str(path), pagesize=(600, 800), invariant=1)
    c.drawString(50, 130, 'in which sigma denotes')
    c.setLineWidth(.5)
    c.line(50, 110, 150, 110)
    c.setFont('Helvetica', 8)
    c.drawString(50, 95, '2This hypothesis, however, is still an open question.')
    c.setFont('Helvetica', 12)
    c.drawString(310, 700, 'ReLU [29]')
    c.save()
    page = locator.extract_positioned_pdf(path)[0]
    assert 'denotes\nReLU [29]' in page['texto']
    assert page['texto'].index('2This hypothesis') > page['texto'].index('ReLU [29]')
    matches, _ = locator.locate_matches(page, '"denotes ReLU"')
    assert len(matches) == 1 and matches[0]['precision'] == 'exacta'
    assert len(matches[0]['rects']) == 2
    note, _ = locator.locate_matches(page, 'hypothesis')
    assert note[0]['precision'] == 'exacta' and note[0]['rects'][0][0] < .5
    assert Counter(page['texto'].replace('\n', '')) == Counter('in which sigma denotes2This hypothesis, however, is still an open question.ReLU [29]')


def test_failed_crop_keeps_text_and_original_record(tmp_path, monkeypatch):
    path = tmp_path / 'failed.pdf'
    c = canvas.Canvas(str(path), pagesize=(600, 800), invariant=1)
    c.drawString(50, 700, 'Question Answering Tasks')
    c.save()
    page = locator.extract_positioned_pdf(path)[0]
    monkeypatch.setattr(render, 'crop_page_png', lambda *args: (_ for _ in ()).throw(ValueError('bad crop')))
    records = ingest._crop_figures(path, 1, [{'bbox': [50, 680, 250, 730]}], 'sample', 1,
                                  LocalStorage(tmp_path / 'media'), 150, 600, 800, page_png=render.render_pdf_page(path, 0))
    assert records[0]['estado'] == 'pagina_original'
    assert page['texto'].strip() == 'Question Answering Tasks'
    assert locator.locate_matches(page, '"Question Answering Tasks"')[0][0]['precision'] == 'exacta'


def test_unicode_reorder_preserves_every_glyph_identity():
    text = '🙂A note B'
    positions = [[i, .1 if i < 8 else .6, .9 if 3 <= i <= 6 else .2, .01, .01]
                 for i, char in enumerate(text) if not char.isspace()]
    reordered, mapped, flow = reorder_native(list(text), positions, [], [[50, 110, 150, 111]], 600, 800)
    assert reordered.index('B') < reordered.index('note')
    assert Counter((text[p[0]], *p[1:]) for p in positions) == Counter((reordered[p[0]], *p[1:]) for p in mapped)
    assert [span['tipo'] for span in flow] == ['prosa', 'nota']


def test_independent_native_panels_are_not_united(tmp_path):
    path = tmp_path / 'independent.pdf'
    c = canvas.Canvas(str(path), pagesize=(600, 800), invariant=1)
    image = ImageReader(Image.new('RGB', (80, 100), 'blue'))
    c.drawImage(image, 80, 550, 80, 100)
    c.drawImage(image, 330, 550, 80, 100)
    c.drawString(80, 530, 'Figure 1. Independent left panel.')
    c.drawString(330, 530, 'Figure 2. Independent right panel.')
    c.save()
    supports = locator.extract_positioned_pdf(path)[0]['soportes']
    assert len(supports) == 2
    assert supports[0]['bbox'][2] < supports[1]['bbox'][0]


def test_builder_preserves_native_support_components_and_multirun_caption(tmp_path, monkeypatch):
    path = tmp_path / 'builder.pdf'
    c = canvas.Canvas(str(path), pagesize=(600, 800), invariant=1)
    c.beginForm('block', 0, 0, 200, 100)
    c.rect(10, 20, 120, 40)
    c.drawString(20, 35, '3x3, 64')
    c.endForm()
    c.saveState()
    c.translate(310, 600)
    c.doForm('block')
    c.restoreState()
    c.setFont('Helvetica', 10)
    c.drawString(310, 580, 'Figure 5. A deeper residual function ')
    c.setFont('Helvetica-Oblique', 10)
    c.drawString(468, 580, 'F')
    c.setFont('Helvetica', 10)
    c.drawString(476, 580, ' for ImageNet.')
    c.drawString(310, 568, 'Right: a bottleneck building block.')
    c.drawString(50, 130, 'We have shown that')
    c.drawString(310, 530, 'parameter-free, identity shortcuts help with training.')
    c.save()
    fragments = [{'bbox': [320, 620, 350, 650], 'orden': 1}, {'bbox': [355, 620, 400, 650], 'orden': 2}]
    monkeypatch.setattr(ingest.structure, 'extract_structure', lambda _: {'bloques': {}, 'figuras': {1: fragments}})
    monkeypatch.setattr(ingest.pdf_classify, 'classify_pdf_file', lambda _: {})
    monkeypatch.setattr(ingest.pdf_classify, 'is_text_based', lambda _: True)
    result = ingest._extract_pdf_source([path], 'sample', [], LocalStorage(tmp_path / 'media'))
    page, = result['pages']
    support, = page['figuras']
    assert support['tipo'] == 'soporte_nativo' and support['detectada']
    assert len(support['componentes']) == 2
    assert 'for ImageNet.' in support['pie'] and 'Right: a bottleneck' in support['pie']
    assert support['bbox'][1] < 568
    assert 'We have shown that\nparameter-free' in page['texto']
    assert page['lectura'] and page['posiciones']
    from app.models import Pagina
    serialized = Pagina(numero=1, ref='sample/pagina/1', **{key: page[key] for key in ('texto', 'lectura', 'posiciones', 'figuras')}).model_dump()
    assert serialized['figuras'][0]['componentes'] == [f['bbox'] for f in fragments]
