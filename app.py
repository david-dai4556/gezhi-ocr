import io
import os
import secrets
import warnings
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request, send_file
from PIL import Image, ImageOps, UnidentifiedImageError
from waitress import serve

from excel import make_xlsx
from ocr import recognize, reconstruct

APP_ID = 'local-table-ocr-v1'
TOKEN = secrets.token_urlsafe(32)
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 24 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 25_000_000


@app.before_request
def local_only():
    if request.host.split(':')[0] not in ('127.0.0.1', 'localhost'):
        return jsonify(error='仅允许本机访问'), 403
    if request.method == 'POST' and request.headers.get('X-Local-Token') != TOKEN:
        return jsonify(error='页面已过期，请刷新后重试'), 403


@app.after_request
def headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/')
def index():
    return render_template('index.html', token=TOKEN)


@app.get('/api/health')
def health():
    return jsonify(app=APP_ID)


@app.errorhandler(413)
def too_large(_):
    return jsonify(error='文件过大，请使用小于 24 MB 的图片'), 413


@app.post('/api/recognize')
def process():
    upload = request.files.get('image')
    if not upload:
        return jsonify(error='请先选择一张图片'), 400
    mode = request.form.get('mode', 'auto')
    if mode not in ('auto', 'grid', 'plain'):
        return jsonify(error='无效的识别模式'), 400
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            source = Image.open(io.BytesIO(upload.read()))
            if source.width * source.height > 25_000_000:
                raise ValueError('图片超过 2500 万像素，请缩小后重试。')
            source = ImageOps.exif_transpose(source).convert('RGBA')
            white = Image.new('RGBA', source.size, 'white')
            white.alpha_composite(source)
            source = white.convert('RGB')
        source.thumbnail((2800, 2800))
        if min(source.size) < 25:
            raise ValueError('图片尺寸过小，无法识别表格。')
        image = cv2.cvtColor(np.array(source), cv2.COLOR_RGB2BGR)
        boxes = recognize(image)
        if not boxes:
            raise ValueError('没有识别到文字，请使用清晰、正向的表格图片。')
        result = reconstruct(image, boxes, mode)
        result['count'] = len(boxes)
        return jsonify(result)
    except (ValueError, UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning, OSError) as exc:
        return jsonify(error=str(exc) if isinstance(exc, ValueError) else '图片无法读取或尺寸过大，请换用 PNG / JPG 图片。'), 400
    except Exception:
        app.logger.exception('OCR failed')
        return jsonify(error='识别失败，请重试；如持续失败，可查看程序目录中的 server.log。'), 500


@app.post('/api/export')
def export():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify(error='表格数据无效'), 400
    data, merges = body.get('data'), body.get('merges', [])
    if (not isinstance(data, list) or not data or len(data) > 2000
            or not isinstance(data[0], list) or not 1 <= len(data[0]) <= 200
            or len(data) * len(data[0]) > 50000
            or any(not isinstance(row, list) or len(row) != len(data[0]) for row in data)
            or any(not isinstance(v, str) or len(v) > 32767 for row in data for v in row)):
        return jsonify(error='表格数据无效或过大（最多 2000 行、200 列、5 万格）'), 400
    occupied = set()
    if not isinstance(merges, list):
        return jsonify(error='合并单元格数据无效'), 400
    for merge in merges:
        if not isinstance(merge, list) or len(merge) != 4 or any(type(v) is not int for v in merge):
            return jsonify(error='合并单元格数据无效'), 400
        a, b, c, d = merge
        if not (0 <= a <= c < len(data) and 0 <= b <= d < len(data[0])):
            return jsonify(error='合并单元格范围无效'), 400
        cells = {(r, col) for r in range(a, c+1) for col in range(b, d+1)}
        if cells & occupied or any(data[r][col] for r,col in cells if (r,col) != (a,b)):
            return jsonify(error='合并区域重叠或会覆盖内容，请先取消合并'), 400
        occupied.update(cells)
    return send_file(make_xlsx(data, merges), as_attachment=True,
                     download_name='识别结果.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


if __name__ == '__main__':
    serve(app, host='127.0.0.1', port=int(os.environ.get('LOCAL_OCR_PORT', '18657')), threads=4)
