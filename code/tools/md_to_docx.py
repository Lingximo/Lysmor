"""把部署指南的 Markdown 转成 .docx（飞书可直接导入）。

只处理这份文档用到的语法：标题、表格、代码块、列表、段落，
外加在"参考图见 …"那句后面插入星图。
"""
import os
import re

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

import sys
MD = sys.argv[1] if len(sys.argv) > 1 else r"D:\你的数据目录\docs\记忆库部署指南.md"
OUT = sys.argv[2] if len(sys.argv) > 2 else MD.replace(".md", ".docx")
IMG = r"D:\你的数据目录\docs\记忆星图-参考.png"

CJK = "微软雅黑"
MONO = "Consolas"


def set_cjk(run, font=CJK):
    run.font.name = font
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font)


def shade(paragraph, color="F2F4F7"):
    pPr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), color)
    pPr.append(shd)


def inline_runs(paragraph, text):
    """去掉 **bold** / `code` 标记，交替加粗。"""
    text = text.replace("\\|", "|")
    for chunk in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not chunk:
            continue
        if chunk.startswith("**") and chunk.endswith("**"):
            run = paragraph.add_run(chunk[2:-2])
            run.bold = True
        elif chunk.startswith("`") and chunk.endswith("`"):
            run = paragraph.add_run(chunk[1:-1])
            run.font.name = MONO
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(0xB3, 0x2D, 0x2D)
            set_cjk(run, MONO)
            continue
        else:
            run = paragraph.add_run(chunk)
        set_cjk(run)


def add_table(doc, rows):
    if not rows:
        return
    cols = max(len(r) for r in rows)
    table = doc.add_table(rows=0, cols=cols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for idx, row in enumerate(rows):
        cells = table.add_row().cells
        for i in range(cols):
            text = row[i] if i < len(row) else ""
            text = re.sub(r"\*\*|\`", "", text)
            cells[i].text = ""
            para = cells[i].paragraphs[0]
            run = para.add_run(text)
            run.font.size = Pt(9)
            set_cjk(run)
            if idx == 0:
                run.bold = True


def main():
    lines = open(MD, encoding="utf-8").read().splitlines()
    doc = Document()

    style = doc.styles["Normal"]
    style.font.name = CJK
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), CJK)

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped == "<!--IMG-->":
            pic_para = doc.add_paragraph()
            pic_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pic_para.add_run().add_picture(IMG, width=Inches(6.1))
            cap = doc.add_paragraph()
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = cap.add_run("图 1　记忆星图（309 节点 / 942 连线 / 115 原子 / 49 条记忆，内容已打码）")
            run.font.size = Pt(8.5)
            run.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
            set_cjk(run)
            i += 1
            continue
        if stripped.startswith("!["):
            i += 1
            continue
        if not stripped or stripped in ("---", "***", "___"):
            i += 1
            continue

        # 代码块
        if stripped.startswith("```"):
            i += 1
            block = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            for code_line in block:
                para = doc.add_paragraph()
                para.paragraph_format.space_after = Pt(0)
                para.paragraph_format.space_before = Pt(0)
                run = para.add_run(code_line if code_line else " ")
                run.font.name = MONO
                run.font.size = Pt(8.5)
                set_cjk(run, MONO)
                shade(para)
            doc.add_paragraph()
            continue

        # 表格
        if stripped.startswith("|") and stripped.endswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                raw = lines[i].strip().strip("|")
                cells = [c.strip() for c in raw.split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            add_table(doc, rows)
            doc.add_paragraph()
            continue

        # 标题
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            text = re.sub(r"[`*]", "", m.group(2))
            para = doc.add_heading("", level=min(level, 4))
            run = para.add_run(text)
            set_cjk(run)
            run.font.color.rgb = RGBColor(0x1F, 0x2A, 0x37)
            i += 1
            continue

        # 引用
        if stripped.startswith(">"):
            para = doc.add_paragraph()
            para.paragraph_format.left_indent = Inches(0.3)
            inline_runs(para, stripped.lstrip("> ").strip())
            for run in para.runs:
                run.italic = True
                run.font.size = Pt(9.5)
                run.font.color.rgb = RGBColor(0x55, 0x60, 0x6D)
            i += 1
            continue

        # 列表 / 勾选框
        if stripped.startswith(("- ", "* ", "[ ] ")):
            text = re.sub(r"^(-\s|\*\s|\[\s\]\s)", "", stripped)
            para = doc.add_paragraph(style="List Bullet")
            inline_runs(para, text)
            i += 1
            continue

        # 有序列表
        m = re.match(r"^\d+\.\s+(.*)$", stripped)
        if m:
            para = doc.add_paragraph(style="List Number")
            inline_runs(para, m.group(1))
            i += 1
            continue

        # 普通段落
        para = doc.add_paragraph()
        para.paragraph_format.space_after = Pt(4)
        inline_runs(para, stripped)
        if stripped == "<!--IMG-->" and os.path.exists(IMG):
            pic_para = doc.add_paragraph()
            pic_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pic_para.add_run().add_picture(IMG, width=Inches(6.1))
            cap = doc.add_paragraph()
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = cap.add_run("图 1　记忆星图（示例：309 节点 / 942 连线 / 115 原子 / 49 条记忆）")
            run.font.size = Pt(8.5)
            run.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
            set_cjk(run)
        i += 1

    doc.save(OUT)
    print("已生成:", OUT, round(os.path.getsize(OUT) / 1024), "KB")


if __name__ == "__main__":
    main()
