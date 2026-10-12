"""Conservative native visual supports and stable, glyph-aligned reading partitions."""
from __future__ import annotations

from app.services.structure import _valid_bbox, is_caption, normalize_bbox


def union_boxes(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def compose_visual_supports(supports, candidates):
    """Keep contained components as evidence; retain every uncovered candidate."""
    remaining, out = list(candidates), []
    for support in supports:
        b = support['bbox']
        contained = [f for f in remaining if b[0] <= f['bbox'][0] and b[1] <= f['bbox'][1]
                     and b[2] >= f['bbox'][2] and b[3] >= f['bbox'][3]]
        out.append({**support, 'componentes': [f['bbox'] for f in contained]})
        remaining = [f for f in remaining if f not in contained]
    return [*out, *remaining]


def native_layout(page, width, height, textpage):
    """Use top-level image/Form boundaries, never child-local coordinates.

    A Form is an actual composite object, not an arbitrary union of nearby ink.
    Invalid native bounds require a full-page support, excluded from detection.
    Only a shared caption can join independent image objects.
    """
    import pypdfium2.raw as raw

    visuals, texts, rules = [], [], []
    for obj in page.get_objects(max_depth=1):
        box = list(obj.get_bounds())
        if obj.type in (raw.FPDF_PAGEOBJ_IMAGE, raw.FPDF_PAGEOBJ_FORM):
            visuals.append((box, obj))
        elif obj.type == raw.FPDF_PAGEOBJ_TEXT and _valid_bbox(box):
            # Object text is used only for semantic association, not page text.
            texts.append((box, obj))
        elif obj.type == raw.FPDF_PAGEOBJ_PATH and _valid_bbox(box):
            if box[3] < height * .25 and box[3]-box[1] <= 2 and width*.07 < box[2]-box[0] < width*.3:
                rules.append(box)
    lines = []
    for box, obj in texts:
        obj.textpage = textpage
        lines.append({'bbox': box, 'texto': obj.extract().replace('\x02', '-')})
    # Font changes split a caption into several real native text objects.
    # Assemble adjacent runs on the same baseline, without joining columns.
    rows = []
    for line in sorted(lines, key=lambda line: (-line['bbox'][3], line['bbox'][0])):
        b = line['bbox']
        row = next((row for row in rows if
            min(b[3], row[0]['bbox'][3])-max(b[1], row[0]['bbox'][1]) > .4*min(b[3]-b[1], row[0]['bbox'][3]-row[0]['bbox'][1])), None)
        if row is not None:
            row.append(line)
        else:
            rows.append([line])
    merged = []
    for row in rows:
        current = None
        for line in sorted(row, key=lambda line: line['bbox'][0]):
            b = line['bbox']
            if current and -2 <= b[0]-current['bbox'][2] <= 18:
                current['bbox'] = union_boxes([current['bbox'], b])
                current['texto'] += line['texto']
            else:
                current = dict(line)
                merged.append(current)
    lines = merged
    captions = [line for line in lines if is_caption(line)]
    supports = []
    for box, obj in visuals:
        valid = _valid_bbox(box) and box[0] >= 0 and box[1] >= 0 and box[2] <= width and box[3] <= height
        if not valid:
            # Recover only a reading partition from real child control points.
            # Stroke/miter bounds are not certified by these points: the visual
            # representation remains the entire original page.
            import ctypes
            points = []
            if obj.type == raw.FPDF_PAGEOBJ_FORM:
                for child in page.get_objects(form=obj, max_depth=2):
                    matrix = child.container.get_matrix() if child.container else obj.get_matrix()
                    if child.type == raw.FPDF_PAGEOBJ_PATH:
                        for index in range(raw.FPDFPath_CountSegments(child)):
                            segment = raw.FPDFPath_GetPathSegment(child, index)
                            x, y = ctypes.c_float(), ctypes.c_float()
                            if raw.FPDFPathSegment_GetPoint(segment, x, y):
                                point = child.get_matrix().multiply(matrix).on_point(x.value, y.value)
                                if 0 <= point[0] <= width and 0 <= point[1] <= height:
                                    points.append(point)
            content_box = [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)] if points else None
            supports.append({'bbox': [0, 0, width, height], 'bbox_contenido': content_box, 'tipo': 'soporte_nativo',
                             'detectada': False, 'precision': 'pagina', 'orden': 0,
                             'advertencia': 'El objeto compuesto tiene límites nativos inválidos. Se conserva la página completa; no se certifica un recorte ni texto buscable de todas sus etiquetas.'})
            continue
        nearby = [c for c in captions if 0 <= box[1]-c['bbox'][3] <= 90
                  and min(box[2], c['bbox'][2]) > max(box[0], c['bbox'][0])
                  and not any(line is not c and c['bbox'][3] < line['bbox'][1] < box[1]
                              and min(box[2], line['bbox'][2]) > max(box[0], line['bbox'][0]) for line in lines)]
        caption = max(nearby, key=lambda c: c['bbox'][3]) if nearby else None
        headings = [line['bbox'] for line in lines if 0 <= line['bbox'][1]-box[3] <= 24
                    and min(box[2], line['bbox'][2]) > max(box[0], line['bbox'][0])
                    and len(line['texto']) < 100]
        boxes = [box, *headings]
        caption_text = None
        if caption:
            # Continue the caption through native lines below it, stopping at
            # the first paragraph-sized vertical gap or unrelated column.
            boxes.append(caption['bbox'])
            caption_text = caption['texto']
            bottom = caption['bbox'][1]
            for line in sorted(lines, key=lambda line: -line['bbox'][3]):
                b = line['bbox']
                if 0 <= bottom-b[3] <= 6 and b[0] >= caption['bbox'][0]-2 and b[2] <= caption['bbox'][2]+2:
                    boxes.append(b)
                    caption_text += '\n' + line['texto']
                    bottom = b[1]
        support = {'bbox': union_boxes(boxes), 'tipo': 'soporte_nativo', 'detectada': True,
                   'precision': 'objeto_compuesto', 'pie': caption_text,
                   '_caption': caption['bbox'] if caption else None}
        shared = next((s for s in supports if caption and s.get('_caption') == caption['bbox']), None)
        if shared:
            shared['bbox'] = union_boxes([shared['bbox'], support['bbox']])
        else:
            supports.append(support)
    for index, support in enumerate(sorted(supports, key=lambda s: (-s['bbox'][3], s['bbox'][0]))):
        support.pop('_caption', None)
        if support['detectada']:
            b = support['bbox']
            support['bbox'] = [max(0, b[0]-3), max(0, b[1]-3), min(width, b[2]+3), min(height, b[3]+3)]
        support['orden'] = index
        support['bbox_norm'] = normalize_bbox(support['bbox'], width, height)
    return supports, rules


def reorder_native(chars, positions, supports, rules, width, height):
    """Stable partition of native character indices, with matching glyph remap.

    PDFium's body sequence is retained. Native footnote rules isolate notes;
    native composite geometry isolates labels/captions. No character sorting,
    interpolation, dehyphenation, or second text extraction is performed.
    """
    boxes = {int(p[0]): p[1:] for p in positions}
    groups = {'prosa': [], 'visual': [], 'nota': []}
    current = 'prosa'
    for index, char in enumerate(chars):
        box = boxes.get(index)
        if box:
            x, y, w, h = box
            cx, cy = (x+w/2)*width, (1-y-h/2)*height
            current = 'prosa'
            for rule in rules:
                # Footnote rules mark a column, not the neighboring body.
                column = 0 if rule[0] < width/2 else 1
                if cy < rule[1] and int(cx >= width/2) == column:
                    current = 'nota'
            if any((b := s['bbox'] if s['detectada'] else s.get('bbox_contenido')) and b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for s in supports):
                current = 'visual'
        groups[current].append(index)
    if not groups['visual'] and not groups['nota']:
        return ''.join(chars), positions, []
    text, remapped, flow = [], [], []
    for kind, indices in groups.items():
        if not indices:
            continue
        if text:
            text.extend('\n\n')
        start = len(text)
        for old in indices:
            new = len(text)
            text.append(chars[old])
            if old in boxes:
                remapped.append([new, *boxes[old]])
        flow.append({'inicio': start, 'fin': len(text), 'tipo': kind})
    return ''.join(text), remapped, flow
