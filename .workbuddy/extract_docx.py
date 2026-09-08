#!/usr/bin/env python3
"""Extract text from .docx files using only the stdlib (zipfile + xml)."""
import os
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = [
    r"E:\WORK\左老师设计\开发者交接包\AIOA技术方案.docx",
    r"E:\WORK\左老师设计\开发者交接包\AIOA客户端小程序P0需求规格说明书.docx",
    r"E:\WORK\左老师设计\开发者交接包\AIOA实体分级与PoC验证计划.docx",
    r"E:\WORK\左老师设计\开发者交接包\AI工作台AIOA产品架构概要方案.docx",
]
OUT_DIR = Path(r"C:\Users\刘尖尖\AppData\Local\Temp\aioa_docs")
OUT_DIR.mkdir(parents=True, exist_ok=True)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def qn(tag):
    return W + tag


def para_text(p):
    parts = []
    for t in p.iter(qn("t")):
        parts.append(t.text or "")
    return "".join(parts)


def extract(path):
    out = []
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    body = root.find(qn("body"))
    if body is None:
        return ""
    for el in body:
        tag = el.tag
        if tag == qn("p"):
            txt = para_text(el)
            # detect heading style
            style = el.find(qn("pPr"))
            prefix = ""
            if style is not None:
                ps = style.find(qn("pStyle"))
                if ps is not None:
                    val = ps.get(qn("val"))
                    if val and ("Heading" in val or "Title" in val or "1" in val):
                        prefix = "\n# "
            out.append(prefix + txt)
        elif tag == qn("tbl"):
            out.append("\n[TABLE]")
            for row in el.findall(qn("tr")):
                cells = []
                for cell in row.findall(qn("tc")):
                    ctext = " ".join(para_text(p) for p in cell.findall(qn("p")))
                    cells.append(ctext.strip())
                out.append(" | ".join(cells))
            out.append("[/TABLE]")
    return "\n".join(out)


for src in SRC:
    name = os.path.splitext(os.path.basename(src))[0]
    text = extract(src)
    dst = OUT_DIR / (name + ".txt")
    dst.write_text(text, encoding="utf-8")
    print(f"OK  {name}: {len(text)} chars -> {dst}")
print("DONE")
