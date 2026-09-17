"""Integration and reconstruction checks, with an actual Chinese OCR fixture."""
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app import app, TOKEN
from excel import make_xlsx
from ocr import reconstruct

OUT = Path(__file__).parent / 'test-output'
OUT.mkdir(exist_ok=True)


def fixture():
    image = Image.new('RGB', (1000, 390), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 30)
    xs, ys = [40, 350, 650, 960], [40, 115, 190, 265, 340]
    for x in xs:
        draw.line((x, 40, x, 340), fill='black', width=3)
    for y in ys:
        draw.line((40, y, 960, y), fill='black', width=3)
    rows = [['姓名', '部门', '编号'], ['张三', '教务处', '00123'],
            ['李四', '财务处', '00456'], ['王五', '学生处', '00789']]
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            draw.text((xs[c]+28, ys[r]+18), text, font=font, fill='black')
    image.save(OUT/'中文表格示例.png')
    stream = io.BytesIO(); image.save(stream, format='PNG'); stream.seek(0)
    return stream, rows


class Integration(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.headers = {'X-Local-Token': TOKEN}

    def test_chinese_ocr_and_export(self):
        stream, expected = fixture()
        response = self.client.post('/api/recognize', data={'image': (stream, '表格.png'), 'mode': 'auto'}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        result = response.get_json()
        (OUT/'ocr-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        self.assertEqual(result['data'], expected)
        self.assertEqual(result['merges'], [])
        result['data'][1][1] = '已人工校对'
        export = self.client.post('/api/export', json=result, headers=self.headers)
        self.assertEqual(export.status_code, 200)
        (OUT/'示例识别结果.xlsx').write_bytes(export.data)
        with ZipFile(io.BytesIO(export.data)) as archive:
            for path in archive.namelist():
                ET.fromstring(archive.read(path))
            xml = archive.read('xl/worksheets/sheet1.xml').decode()
            self.assertIn('00123', xml)
            self.assertIn('已人工校对', xml)
            self.assertNotIn('<f>', xml)

    def test_validation(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.post('/api/export', json={}).status_code, 403)
        self.assertEqual(self.client.get('/', headers={'Host': 'external.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/export', json={'data': [['a'], []]}, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post('/api/export', json={'data': [['a', 'b']], 'merges': [[0, 0, 0, 1]]}, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post('/api/recognize', data={'image': (io.BytesIO(b'not an image'), 'x.png')}, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post('/api/export', json={'data': [['x']], 'merges': [[0,0,1,1]]}, headers=self.headers).status_code, 400)

    def test_literal_text(self):
        with ZipFile(make_xlsx([['=SUM(1,2)', '00123', '12345678901234567890', '<&']], [])) as archive:
            xml = archive.read('xl/worksheets/sheet1.xml').decode()
            self.assertIn('=SUM(1,2)', xml)
            self.assertIn('&lt;&amp;', xml)
            self.assertNotIn('<f>', xml)
            ET.fromstring(xml)

    def test_merged_grid_and_multiline(self):
        image = np.full((330, 640, 3), 255, np.uint8)
        for y in [20, 110, 200, 290]:
            cv2.line(image, (20,y), (620,y), (0,0,0), 2)
        for x in [20,620]:
            cv2.line(image, (x,20), (x,290), (0,0,0), 2)
        cv2.line(image, (320,110), (320,290), (0,0,0), 2)
        boxes = [dict(x=320,y=65,left=260,right=380,height=25,text='合并标题',score=.99),
                 dict(x=100,y=140,left=60,right=140,height=20,text='第一行',score=.99),
                 dict(x=100,y=170,left=60,right=140,height=20,text='第二行',score=.7)]
        result = reconstruct(image, boxes)
        self.assertEqual(result['merges'], [[0,0,0,1]])
        self.assertEqual(result['data'][0], ['合并标题', ''])
        self.assertEqual(result['data'][1][0], '第一行\n第二行')

    def test_borderless_blanks(self):
        image = np.full((300, 600, 3),255,np.uint8)
        boxes = [dict(x=x,y=y,left=x-15,right=x+15,height=20,text=t,score=.99)
                 for x,y,t in [(100,50,'A'),(300,50,'B'),(500,50,'C'),(100,110,'1'),(500,110,'3')]]
        result = reconstruct(image,boxes,'plain')
        self.assertEqual(result['data'], [['A','B','C'],['1','','3']])


if __name__ == '__main__':
    unittest.main(verbosity=2)
