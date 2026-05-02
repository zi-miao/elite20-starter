#!/usr/bin/env python3
"""
Stage 0: PDF → Markdown dispatcher.

Tries converters in priority order and returns (markdown_path, resampled_pdf_path).

Priority (auto):
  1. source-text-to-markdown skill (if callable from this env)
  2. markitdown                    (pip install markitdown)
  3. pandoc                        (system binary)
  4. olmocr                        (vision OCR fallback for scanned / math-heavy)

The user can force a specific converter via --converter.

Usage:
    python pdf_to_markdown.py --pdf paper.pdf --out ./work [--converter markitdown]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


# --------------------------------------------------------------------------- #
# Domain model: a converter is a function (pdf_in, md_out_dir) -> md_out_path
# Each converter is responsible for knowing whether it's available on the
# current machine; unavailable converters return None from `available()`.
# --------------------------------------------------------------------------- #
@dataclass
class Converter:
    name: str
    available: Callable[[], bool]
    convert: Callable[[Path, Path], Path]
    notes: str = ""


def _have_binary(name: str) -> bool:
    return shutil.which(name) is not None


def _have_python_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Converter: markitdown (Microsoft)
# --------------------------------------------------------------------------- #
def _convert_markitdown(pdf: Path, out_dir: Path) -> Path:
    from markitdown import MarkItDown  # type: ignore

    md_path = out_dir / (pdf.stem + ".md")
    md = MarkItDown()
    result = md.convert(str(pdf))
    md_path.write_text(result.text_content, encoding="utf-8")
    return md_path


# --------------------------------------------------------------------------- #
# Converter: pandoc
# --------------------------------------------------------------------------- #
def _convert_pandoc(pdf: Path, out_dir: Path) -> Path:
    md_path = out_dir / (pdf.stem + ".md")
    # Pandoc cannot read PDF directly in all distros; prefer pdftotext -> pandoc
    # to get text, or pandoc-pdf reader if available. Try pandoc first, fall
    # back to pdftotext + wrap as markdown.
    try:
        subprocess.run(
            ["pandoc", str(pdf), "-o", str(md_path), "--to=gfm"],
            check=True,
            capture_output=True,
        )
        return md_path
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    if _have_binary("pdftotext"):
        txt_path = out_dir / (pdf.stem + ".txt")
        subprocess.run(
            ["pdftotext", "-layout", str(pdf), str(txt_path)], check=True
        )
        md_path.write_text(
            f"# {pdf.stem}\n\n" + txt_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return md_path

    raise RuntimeError("pandoc-with-pdf-reader and pdftotext both unavailable")


# --------------------------------------------------------------------------- #
# Converter: source-text-to-markdown (companion skill)
# --------------------------------------------------------------------------- #
def _convert_source_text_to_markdown(pdf: Path, out_dir: Path) -> Path:
    skill_root = Path("/mnt/skills/user/source-text-to-markdown")
    # Prefer scripts/ingest.py (actual name), then any other .py entry point.
    skill_script = skill_root / "scripts" / "ingest.py"
    if not skill_script.exists():
        candidates = list(skill_root.rglob("ingest.py")) or list(
            skill_root.rglob("*.py")
        )
        if not candidates:
            raise FileNotFoundError("source-text-to-markdown skill not installed")
        skill_script = candidates[0]
    md_path = out_dir / (pdf.stem + ".md")
    media_dir = out_dir / (pdf.stem + "_media")
    # ingest.py uses a positional `input` and `-o` for output
    subprocess.run(
        [
            sys.executable, str(skill_script),
            str(pdf),
            "-o", str(md_path),
            "--media-dir", str(media_dir),
        ],
        check=True,
    )
    return md_path


# --------------------------------------------------------------------------- #
# Converter: olmocr (vision OCR fallback, heavyweight)
# --------------------------------------------------------------------------- #
def _convert_olmocr(pdf: Path, out_dir: Path) -> Path:
    # olmocr is invoked as a module; assumes GPU available for real papers.
    md_path = out_dir / (pdf.stem + ".md")
    subprocess.run(
        [sys.executable, "-m", "olmocr.pipeline", str(pdf), "--output", str(md_path)],
        check=True,
    )
    return md_path


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
CONVERTERS: list[Converter] = [
    Converter(
        name="source-text-to-markdown",
        available=lambda: Path("/mnt/skills/user/source-text-to-markdown").exists(),
        convert=_convert_source_text_to_markdown,
        notes="Preferred: wraps pandoc + YAML front matter + language detection",
    ),
    Converter(
        name="markitdown",
        available=lambda: _have_python_module("markitdown"),
        convert=_convert_markitdown,
        notes="Fast, good for well-structured PDFs. `pip install markitdown`",
    ),
    Converter(
        name="pandoc",
        available=lambda: _have_binary("pandoc") or _have_binary("pdftotext"),
        convert=_convert_pandoc,
        notes="Generic fallback via pandoc or pdftotext",
    ),
    Converter(
        name="olmocr",
        available=lambda: _have_python_module("olmocr"),
        convert=_convert_olmocr,
        notes="Heavy; best for scanned / math-heavy / complex-layout PDFs",
    ),
]


def _resample_pdf(pdf_in: Path, pdf_out: Path, dpi: int = 250) -> Path:
    """Resample PDF pages to target DPI for vision grounding in later stages."""
    # Try ghostscript; fall back to identity copy.
    if _have_binary("gs"):
        subprocess.run(
            [
                "gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
                "-dPDFSETTINGS=/printer",
                f"-dColorImageResolution={dpi}",
                f"-dGrayImageResolution={dpi}",
                f"-dMonoImageResolution={dpi}",
                "-dNOPAUSE", "-dQUIET", "-dBATCH",
                f"-sOutputFile={pdf_out}", str(pdf_in),
            ],
            check=True,
        )
    else:
        shutil.copy(pdf_in, pdf_out)
    return pdf_out


def convert(
    pdf: Path, out_dir: Path, force: str | None = None
) -> tuple[Path, Path]:
    """Run Stage 0 and return (markdown_path, resampled_pdf_path)."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resample PDF for vision grounding
    pdf_resampled = out_dir / (pdf.stem + ".resampled.pdf")
    _resample_pdf(pdf, pdf_resampled)

    # Select converter
    if force:
        chosen = next((c for c in CONVERTERS if c.name == force), None)
        if chosen is None:
            raise ValueError(f"Unknown converter: {force}")
        if not chosen.available():
            raise RuntimeError(
                f"Requested converter '{force}' is not available on this system. "
                f"Notes: {chosen.notes}"
            )
    else:
        chosen = next((c for c in CONVERTERS if c.available()), None)
        if chosen is None:
            raise RuntimeError(
                "No PDF→Markdown converter available. Install one of: "
                + ", ".join(c.name for c in CONVERTERS)
            )

    print(f"[stage0] converter={chosen.name}  pdf={pdf}  ->  out_dir={out_dir}")
    md_path = chosen.convert(pdf, out_dir)
    return md_path, pdf_resampled


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 0: PDF → Markdown")
    ap.add_argument("--pdf", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--converter",
        choices=[c.name for c in CONVERTERS],
        default=None,
        help="Force a specific converter (default: auto-select first available)",
    )
    ap.add_argument(
        "--list", action="store_true",
        help="List available converters on this system and exit",
    )
    args = ap.parse_args()

    if args.list:
        for c in CONVERTERS:
            status = "✓" if c.available() else "✗"
            print(f"  {status} {c.name:30s} {c.notes}")
        return

    md_path, pdf_resampled = convert(args.pdf, args.out, force=args.converter)
    print(f"[stage0] done. markdown={md_path}  pdf={pdf_resampled}")


if __name__ == "__main__":
    main()
