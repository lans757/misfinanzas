"""Convert docs markdown files to PDF using fpdf2 + markdown."""
import re
import markdown
from fpdf import FPDF, HTMLMixin
from pathlib import Path

DOCS = Path(__file__).parent

TITLES = {
    "architecture.md": "Arquitectura Técnica — MisFinanzas",
    "user-guide.md":   "Guía de Usuario — MisFinanzas",
    "dev-setup.md":    "Developer Setup — MisFinanzas",
}

STYLE = """
<style>
  body  { font-family: Helvetica; font-size: 11pt; color: #1a1a2e; }
  h1    { font-size: 20pt; color: #1a1a2e; margin-bottom: 6pt; }
  h2    { font-size: 15pt; color: #2d3a8c; margin-top: 14pt; margin-bottom: 4pt; }
  h3    { font-size: 12pt; color: #4f5b93; margin-top: 10pt; margin-bottom: 3pt; }
  p     { margin: 4pt 0; line-height: 1.5; }
  ul,ol { margin: 4pt 0 4pt 16pt; }
  li    { margin: 2pt 0; }
  pre   { font-family: Courier; font-size: 9pt; background: #f4f4f8;
          padding: 6pt; border-radius: 3pt; }
  code  { font-family: Courier; font-size: 9pt; background: #f0f0f5; }
  table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 10pt; }
  th    { background: #2d3a8c; color: white; padding: 4pt 6pt; text-align: left; }
  td    { border: 1px solid #ccc; padding: 4pt 6pt; }
  blockquote { border-left: 3px solid #2d3a8c; padding-left: 8pt;
               color: #555; font-style: italic; margin: 6pt 0; }
</style>
"""


class PDF(FPDF, HTMLMixin):
    def header(self):
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 160)
        self.cell(0, 8, "MisFinanzas — Documentación", align="R")
        self.ln(4)

    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 160)
        self.cell(0, 8, f"Página {self.page_no()}", align="C")


def md_to_html(text: str) -> str:
    extensions = ["tables", "fenced_code", "nl2br", "sane_lists"]
    return markdown.markdown(text, extensions=extensions)


def build_pdf(md_file: Path, out_file: Path) -> None:
    raw = md_file.read_text(encoding="utf-8")
    html_body = md_to_html(raw)

    # fpdf2 write_html doesn't support <style> fully — inline basic replacements
    # Strip <style> block we added and handle via font/color settings instead
    html = f"<html><body>{html_body}</body></html>"

    pdf = PDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(left=20, top=18, right=20)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.write_html(html)
    pdf.output(str(out_file))
    print(f"  ✓ {out_file.name}")


if __name__ == "__main__":
    print("Generando PDFs...")
    for md_name in TITLES:
        src = DOCS / md_name
        dst = DOCS / md_name.replace(".md", ".pdf")
        if not src.exists():
            print(f"  ✗ {md_name} no encontrado — saltando")
            continue
        build_pdf(src, dst)
    print("Listo.")
