"""Offline text recognition and table reconstruction."""
from bisect import bisect_right
from threading import Lock

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

_engine = None
_lock = Lock()


def recognize(image):
    global _engine
    with _lock:
        if _engine is None:
            _engine = RapidOCR(intra_op_num_threads=4, inter_op_num_threads=2)
        result, _ = _engine(image)
    boxes = []
    for points, text, score in result or []:
        p = np.asarray(points)
        boxes.append(dict(x=float(p[:, 0].mean()), y=float(p[:, 1].mean()),
                          left=float(p[:, 0].min()), right=float(p[:, 0].max()),
                          height=float(np.ptp(p[:, 1])), text=text, score=float(score)))
    return boxes


def clusters(values, tolerance=5):
    groups = []
    for value in sorted(values):
        if groups and value - np.mean(groups[-1]) <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [int(round(np.mean(g))) for g in groups]


def grid_lines(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 25, 15)
    h, w = gray.shape
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, w // 25), 1)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(25, h // 25))))
    xs = clusters(np.flatnonzero(np.count_nonzero(vertical, axis=0) > max(35, h * .22)))
    ys = clusters(np.flatnonzero(np.count_nonzero(horizontal, axis=1) > max(45, w * .22)))
    return xs, ys, horizontal, vertical


def reconstruct(image, boxes, mode='auto'):
    xs, ys, horizontal, vertical = grid_lines(image)
    has_grid = len(xs) >= 2 and len(ys) >= 2
    if mode == 'grid' and not has_grid:
        raise ValueError('未找到完整表格线，请裁剪到表格区域，或改用“无边框”模式。')
    if mode != 'plain' and has_grid:
        nr, nc = len(ys) - 1, len(xs) - 1
        if nr * nc > 15000:
            raise ValueError('检测到的表格过大，请裁剪图片后重试。')
        # Missing interior borders join adjacent elementary cells. Only rectangular
        # components become Excel merges; ambiguous shapes stay separate.
        parent = list(range(nr * nc))

        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def join(a, b):
            parent[root(a)] = root(b)

        for r in range(nr):
            for c in range(nc):
                i = r * nc + c
                if c < nc - 1:
                    band = vertical[ys[r]+4:ys[r+1]-3, max(0, xs[c+1]-3):xs[c+1]+4]
                    if band.size and np.mean(np.any(band > 0, axis=1)) < .25:
                        join(i, i+1)
                if r < nr - 1:
                    band = horizontal[max(0, ys[r+1]-3):ys[r+1]+4, xs[c]+4:xs[c+1]-3]
                    if band.size and np.mean(np.any(band > 0, axis=0)) < .25:
                        join(i, i+nc)
        groups = {}
        for i in range(nr * nc):
            groups.setdefault(root(i), []).append(divmod(i, nc))
        anchors, merges = {}, []
        for cells in groups.values():
            r0, c0 = min(r for r, c in cells), min(c for r, c in cells)
            r1, c1 = max(r for r, c in cells), max(c for r, c in cells)
            if len(cells) > 1 and len(cells) == (r1-r0+1)*(c1-c0+1):
                merges.append([r0, c0, r1, c1])
                for cell in cells:
                    anchors[cell] = (r0, c0)
        data = [[''] * nc for _ in range(nr)]
        scores = [[1.] * nc for _ in range(nr)]
        outside = 0
        for b in sorted(boxes, key=lambda b: (round(b['y']/8), b['x'])):
            r, c = bisect_right(ys, b['y'])-1, bisect_right(xs, b['x'])-1
            if not (0 <= r < nr and 0 <= c < nc):
                outside += 1
                continue
            r, c = anchors.get((r, c), (r, c))
            data[r][c] += ('\n' if data[r][c] else '') + b['text']
            scores[r][c] = min(scores[r][c], b['score'])
        note = '按表格线还原行列；简单合并单元格会自动保留。'
        if outside:
            note += f' 表格外有 {outside} 段文字，未放入表格，请对照原图核查。'
        return dict(data=data, scores=scores, merges=merges, method='有边框表格', note=note)

    height = float(np.median([b['height'] for b in boxes])) if boxes else 20
    rows = []
    for b in sorted(boxes, key=lambda b: b['y']):
        if rows and abs(b['y'] - np.mean([x['y'] for x in rows[-1]])) < height * .6:
            rows[-1].append(b)
        else:
            rows.append([b])
    for row in rows:
        row.sort(key=lambda b: b['x'])
    # Use the densest row as column anchors; align sparse rows without shifting blanks.
    reference = max(rows, key=len, default=[])
    centers = [b['x'] for b in reference]
    boundaries = [(a+b)/2 for a, b in zip(centers, centers[1:])]
    data, scores = [], []
    for row in rows:
        values, confidence = [''] * len(centers), [1.] * len(centers)
        for b in row:
            c = bisect_right(boundaries, b['x'])
            values[c] += (' ' if values[c] else '') + b['text']
            confidence[c] = min(confidence[c], b['score'])
        data.append(values)
        scores.append(confidence)
    return dict(data=data, scores=scores, merges=[], method='无边框推断',
                note='根据文字位置推断行列。空白、跨行或复杂排版可能错列，请编辑校对后导出。')
