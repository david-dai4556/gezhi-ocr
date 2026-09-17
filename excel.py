"""Small dependency-free OOXML writer. OCR values are always literal text."""
import io
import re
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape


def col(n):
    value = ''
    while n:
        n, rem = divmod(n-1, 26)
        value = chr(65+rem) + value
    return value


def cell(r, c):
    return f'{col(c+1)}{r+1}'


def make_xlsx(data, merges):
    stream = io.BytesIO()
    rows = []
    for r, values in enumerate(data):
        cells = []
        for c, value in enumerate(values):
            text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value))[:32767]
            cells.append(f'<c r="{cell(r,c)}" s="{1 if r == 0 else 2}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>')
        rows.append(f'<row r="{r+1}" ht="{max(28, min(150, 18*max((str(v).count(chr(10))+1 for v in values), default=1)))}" customHeight="1">{"".join(cells)}</row>')
    merge_xml = ''.join(f'<mergeCell ref="{cell(a,b)}:{cell(c,d)}"/>' for a,b,c,d in merges)
    merge_xml = f'<mergeCells count="{len(merges)}">{merge_xml}</mergeCells>' if merges else ''
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    sheet = f'<worksheet xmlns="{ns}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols><col min="1" max="{len(data[0])}" width="22" customWidth="1"/></cols><sheetData>{"".join(rows)}</sheetData>{merge_xml}</worksheet>'
    styles = f'''<styleSheet xmlns="{ns}"><fonts count="2"><font><sz val="11"/><name val="Microsoft YaHei"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Microsoft YaHei"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF126B59"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="2"><border/><border><left style="thin"><color rgb="FFDCE5E1"/></left><right style="thin"><color rgb="FFDCE5E1"/></right><top style="thin"><color rgb="FFDCE5E1"/></top><bottom style="thin"><color rgb="FFDCE5E1"/></bottom></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="49" fontId="1" fillId="2" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf><xf numFmtId="49" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
    files = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        '_rels/.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="识别结果" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': sheet,
        'xl/styles.xml': styles,
    }
    with ZipFile(stream, 'w', ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'+content)
    stream.seek(0)
    return stream
