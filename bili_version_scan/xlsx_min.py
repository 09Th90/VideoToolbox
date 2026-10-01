# -*- coding: utf-8 -*-
# @version 1.16.4
"""极简 xlsx 写出器（仅用标准库 zipfile），无第三方依赖。

用法：
    w = XlsxWriter()
    w.add_sheet('名字', ['列1','列2'], [[1,'a'], [2,'b']], widths=[10,20])
    w.save('out.xlsx')
"""
import zipfile
import re


def _esc(s):
    s = str(s)
    s = s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
    return ''.join(ch for ch in s if ch >= ' ' or ch in '\t\n')


def _col(n):
    s = ''
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _sheet_name(name):
    name = re.sub(r'[\[\]\*/\\\?:]', '_', name)
    return name[:31]


class XlsxWriter:
    def __init__(self):
        self.sheets = []

    def add_sheet(self, name, headers, rows, widths=None):
        self.sheets.append((_sheet_name(name), list(headers), list(rows), widths))

    def _sheet_xml(self, headers, rows, widths):
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
        if widths:
            out.append('<cols>')
            for i, w in enumerate(widths, 1):
                out.append('<col min="%d" max="%d" width="%s" customWidth="1"/>' % (i, i, w))
            out.append('</cols>')
        out.append('<sheetData>')
        r = 0
        if headers:
            r += 1
            out.append('<row r="%d">' % r)
            for i, h in enumerate(headers, 1):
                out.append('<c r="%s%d" s="1" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
                           % (_col(i), r, _esc(h)))
            out.append('</row>')
        for row in rows:
            r += 1
            out.append('<row r="%d">' % r)
            for i, v in enumerate(row, 1):
                ref = '%s%d' % (_col(i), r)
                if isinstance(v, bool):
                    v = int(v)
                if isinstance(v, (int, float)):
                    out.append('<c r="%s"><v>%s</v></c>' % (ref, v))
                elif v is None or v == '':
                    continue
                else:
                    out.append('<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
                               % (ref, _esc(v)))
            out.append('</row>')
        out.append('</sheetData>')
        out.append('<autoFilter ref="A1:%s%d"/>' % (_col(max(1, len(headers))), max(1, r)))
        out.append('</worksheet>')
        return ''.join(out)

    def save(self, path):
        n = len(self.sheets)
        ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
              '<Default Extension="xml" ContentType="application/xml"/>',
              '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
              '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
        for i in range(1, n + 1):
            ct.append('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % i)
        ct.append('</Types>')

        wb = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
              '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
              'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>']
        rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
        for i, (name, _, _, _) in enumerate(self.sheets, 1):
            wb.append('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (_esc(name), i, i))
            rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i, i))
        wb.append('</sheets></workbook>')
        rels.append('<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>')
        rels.append('</Relationships>')

        styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                  '<fonts count="2"><font><sz val="11"/><name val="\u5fae\u8f6f\u96c5\u9ed1"/></font>'
                  '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="\u5fae\u8f6f\u96c5\u9ed1"/></font></fonts>'
                  '<fills count="3"><fill><patternFill patternType="none"/></fill>'
                  '<fill><patternFill patternType="gray125"/></fill>'
                  '<fill><patternFill patternType="solid"><fgColor rgb="FF305496"/><bgColor indexed="64"/></patternFill></fill></fills>'
                  '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                  '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                  '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                  '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" '
                  'applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf></cellXfs>'
                  '</styleSheet>')

        root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                     '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                     '</Relationships>')

        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('[Content_Types].xml', ''.join(ct))
            z.writestr('_rels/.rels', root_rels)
            z.writestr('xl/workbook.xml', ''.join(wb))
            z.writestr('xl/_rels/workbook.xml.rels', ''.join(rels))
            z.writestr('xl/styles.xml', styles)
            for i, (_, headers, rows, widths) in enumerate(self.sheets, 1):
                z.writestr('xl/worksheets/sheet%d.xml' % i, self._sheet_xml(headers, rows, widths))


if __name__ == '__main__':
    w = XlsxWriter()
    w.add_sheet('测试', ['a', 'b'], [[1, '中文'], [2, 'x&y<z']], widths=[10, 20])
    w.save('_t.xlsx')
    print('ok')
