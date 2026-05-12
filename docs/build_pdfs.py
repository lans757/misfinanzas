"""Convert docs markdown files to PDF using fpdf2 + markdown."""
import markdown
from fpdf import FPDF
from pathlib import Path

DOCS = Path(__file__).parent

FONT_REGULAR = r"C:\Windows\Fonts\calibri.ttf"
FONT_BOLD    = r"C:\Windows\Fonts\calibrib.ttf"
FONT_ITALIC  = r"C:\Windows\Fonts\calibrii.ttf"
FONT_MONO    = r"C:\Windows\Fonts\consola.ttf"   # Consolas


class PDF(FPDF):
    def header(self):
        self.set_font("calibri", style="I", size=8)
        self.set_text_color(150, 150, 160)
        self.cell(0, 8, "MisFinanzas - Documentacion", align="R")
        self.ln(4)

    def footer(self):
        self.set_y(-14)
        self.set_font("calibri", style="I", size=8)
        self.set_text_color(150, 150, 160)
        self.cell(0, 8, f"Pagina {self.page_no()}", align="C")


def build_pdf(md_file: Path, out_file: Path) -> None:
    import re
    raw = md_file.read_text(encoding="utf-8")

    pdf = PDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(left=20, top=18, right=20)
    pdf.set_auto_page_break(auto=True, margin=18)

    # Register fonts
    pdf.add_font("calibri",  style="",  fname=FONT_REGULAR, uni=True)
    pdf.add_font("calibri",  style="B", fname=FONT_BOLD,    uni=True)
    pdf.add_font("calibri",  style="I", fname=FONT_ITALIC,  uni=True)
    pdf.add_font("consolas", style="",  fname=FONT_MONO,    uni=True)

    pdf.add_page()
    pdf.set_font("calibri", size=11)

    page_w = pdf.w - pdf.l_margin - pdf.r_margin
    in_code_block = False
    code_lines    = []

    def flush_code(lines):
        pdf.set_font("consolas", size=9)
        pdf.set_fill_color(244, 244, 248)
        block = "\n".join(lines)
        pdf.multi_cell(page_w, 5, block, border=0, fill=True, ln=True)
        pdf.set_font("calibri", size=11)
        pdf.ln(2)

    def strip_inline(text):
        """Remove inline markdown markers for clean output."""
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # bold
        text = re.sub(r"\*(.+?)\*",     r"\1", text)   # italic
        text = re.sub(r"`(.+?)`",       r"\1", text)   # inline code
        text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text) # links
        return text

    def render_table(rows):
        """Render a markdown table (list of row strings)."""
        parsed = []
        for row in rows:
            cols = [c.strip() for c in row.strip().strip("|").split("|")]
            parsed.append(cols)
        if not parsed:
            return
        # First row = header, second = separator (skip), rest = data
        header = parsed[0] if parsed else []
        data   = [r for r in parsed[2:] if r] if len(parsed) > 2 else []
        n_cols = len(header)
        if n_cols == 0:
            return
        col_w = page_w / n_cols

        pdf.set_font("calibri", style="B", size=10)
        pdf.set_fill_color(45, 58, 140)
        pdf.set_text_color(255, 255, 255)
        for col in header:
            pdf.cell(col_w, 7, strip_inline(col), border=1, fill=True)
        pdf.ln()

        pdf.set_font("calibri", size=10)
        pdf.set_text_color(30, 30, 30)
        for i, row in enumerate(data):
            pdf.set_fill_color(245, 245, 252) if i % 2 == 0 else pdf.set_fill_color(255, 255, 255)
            for ci, col in enumerate(row):
                val = strip_inline(col) if ci < len(row) else ""
                pdf.cell(col_w, 6, val, border=1, fill=True)
            pdf.ln()
        pdf.set_text_color(30, 30, 30)
        pdf.ln(3)

    lines = raw.splitlines()
    i = 0
    table_rows = []
    in_table   = False

    while i < len(lines):
        line = lines[i]

        # ── Code block ────────────────────────────────────────────────
        if line.startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_lines    = []
            else:
                in_code_block = False
                flush_code(code_lines)
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        # ── Table ─────────────────────────────────────────────────────
        if line.startswith("|"):
            if not in_table:
                in_table   = True
                table_rows = []
            table_rows.append(line)
            i += 1
            continue
        elif in_table:
            render_table(table_rows)
            in_table   = False
            table_rows = []

        # ── Horizontal rule ───────────────────────────────────────────
        if re.match(r"^---+$", line.strip()):
            pdf.set_draw_color(200, 200, 210)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + page_w, pdf.get_y())
            pdf.ln(4)
            i += 1
            continue

        # ── Headings ──────────────────────────────────────────────────
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            text  = strip_inline(m.group(2))
            if level == 1:
                pdf.set_font("calibri", style="B", size=20)
                pdf.set_text_color(26, 26, 46)
                pdf.ln(4)
                pdf.multi_cell(page_w, 10, text, ln=True)
                pdf.set_draw_color(45, 58, 140)
                pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + page_w, pdf.get_y())
                pdf.ln(5)
            elif level == 2:
                pdf.set_font("calibri", style="B", size=15)
                pdf.set_text_color(45, 58, 140)
                pdf.ln(5)
                pdf.multi_cell(page_w, 8, text, ln=True)
                pdf.ln(1)
            else:
                pdf.set_font("calibri", style="B", size=12)
                pdf.set_text_color(79, 91, 147)
                pdf.ln(3)
                pdf.multi_cell(page_w, 7, text, ln=True)
            pdf.set_text_color(30, 30, 30)
            pdf.set_font("calibri", size=11)
            i += 1
            continue

        # ── Blockquote ────────────────────────────────────────────────
        if line.startswith("> "):
            text = strip_inline(line[2:])
            pdf.set_font("calibri", style="I", size=10)
            pdf.set_text_color(100, 100, 120)
            pdf.set_fill_color(240, 242, 255)
            pdf.multi_cell(page_w - 6, 5.5, text, border=0, fill=False, ln=True, new_x="LMARGIN")
            pdf.set_text_color(30, 30, 30)
            pdf.set_font("calibri", size=11)
            pdf.ln(2)
            i += 1
            continue

        # ── List item ────────────────────────────────────────────────
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)", line)
        if m:
            indent = len(m.group(1))
            text   = strip_inline(m.group(3))
            bullet = "•" if not m.group(2)[0].isdigit() else m.group(2)
            x_off  = 4 + indent * 4
            pdf.set_x(pdf.l_margin + x_off)
            pdf.set_font("calibri", size=11)
            pdf.cell(5, 5.5, bullet)
            pdf.multi_cell(page_w - x_off - 5, 5.5, text, ln=True, new_x="LMARGIN")
            i += 1
            continue

        # ── Blank line ───────────────────────────────────────────────
        if line.strip() == "":
            pdf.ln(3)
            i += 1
            continue

        # ── Normal paragraph ─────────────────────────────────────────
        text = strip_inline(line)
        pdf.set_font("calibri", size=11)
        pdf.multi_cell(page_w, 5.5, text, ln=True)
        i += 1

    # Flush pending table if file ended mid-table
    if in_table:
        render_table(table_rows)
    if in_code_block:
        flush_code(code_lines)

    pdf.output(str(out_file))
    print(f"  OK  {out_file.name}")


DOCS_LIST = ["architecture.md", "user-guide.md", "dev-setup.md"]

if __name__ == "__main__":
    print("Generando PDFs...")
    for name in DOCS_LIST:
        src = DOCS / name
        dst = DOCS / name.replace(".md", ".pdf")
        if not src.exists():
            print(f"  --  {name} no encontrado")
            continue
        build_pdf(src, dst)
    print("Listo.")
