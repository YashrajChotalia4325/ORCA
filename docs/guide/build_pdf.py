"""Build docs/ORCA-Guide.pdf from docs/guide/ORCA-Guide.html.

Two passes with headless Chrome/Edge: the first PDF is used to find the page of
every section heading (via PyMuPDF), the numbers are written into the table of
contents, and the second pass prints the final PDF.

    pip install pymupdf
    python docs/guide/build_pdf.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
SRC = HERE / "ORCA-Guide.html"
OUT = HERE.parent / "ORCA-Guide.pdf"
BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser", "microsoft-edge",
]


def browser() -> str:
    for b in BROWSERS:
        if Path(b).exists() or shutil.which(b):
            return b
    sys.exit("no Chrome / Edge found")


def render(html: Path, pdf: Path) -> None:
    subprocess.run([browser(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--run-all-compositor-stages-before-draw", f"--print-to-pdf={pdf}", html.as_uri()],
                   check=True, capture_output=True, timeout=180)


def heading_pages(pdf: Path, html: str) -> dict[str, int]:
    """Anchor id -> 1-based page, found by searching each heading's text after the contents pages."""
    doc = pymupdf.open(pdf)
    titles = {m.group(1): re.sub(r"<[^>]+>", "", m.group(2)).strip()
              for m in re.finditer(r'id="((?:s\d+)|read|part\d)"[^>]*>(.*?)</(?:h1|h2)>', html, re.S)}
    for m in re.finditer(r'class="part" id="(part\d)">\s*<div class="num">[^<]*</div>\s*<h1 class="part-title">([^<]+)</h1>', html):
        titles[m.group(1)] = m.group(2).strip()
    pages: dict[str, int] = {}
    start = 3  # skip cover + contents
    for key, title in titles.items():
        probe = title[:40].replace("&amp;", "&")
        for i in range(start - 1, doc.page_count):
            blocks = doc[i].get_text("dict")["blocks"]
            hit = any(probe in "".join(s["text"] for s in l["spans"]) and max(s["size"] for s in l["spans"]) >= 14
                      for b in blocks for l in b.get("lines", []))
            if hit:
                pages[key] = i + 1
                break
    return pages


def main() -> None:
    html = SRC.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        first = t / "pass1.pdf"
        render(SRC, first)
        pages = heading_pages(first, html)
        missing = [k for k in re.findall(r'data-t="([^"]+)"', html) if k not in pages]
        if missing:
            print("warning: no page found for", missing)
        filled = re.sub(r'<span class="pg" data-t="([^"]+)"></span>',
                        lambda m: f'<span class="pg" data-t="{m.group(1)}">{pages.get(m.group(1), "")}</span>', html)
        tmp_html = HERE / "_build.html"          # same folder so relative paths keep working
        tmp_html.write_text(filled, encoding="utf-8")
        try:
            render(tmp_html, OUT)
        finally:
            os.remove(tmp_html)
    print(f"wrote {OUT} ({pymupdf.open(OUT).page_count} pages)")


if __name__ == "__main__":
    main()
