"""Rebuild any PDF so that every page is exactly A4 portrait.

The result is an ordinary PDF, so it can be inspected or tested without using paper.
"""
from dataclasses import dataclass, field
from pathlib import Path

import fitz

from .config import (A4_HEIGHT_PT, A4_TOLERANCE_MM, A4_WIDTH_PT, DUPLEX_LONG_EDGE,
                     DUPLEX_SHORT_EDGE, MM_PER_PT)


class UnprintableDocument(Exception):
    """The captured file cannot be turned into pages."""


@dataclass
class Report:
    pages: int = 0
    sheets: int = 0
    duplex_edge: int = DUPLEX_LONG_EDGE
    source_sizes: dict = field(default_factory=dict)
    rotated_pages: list = field(default_factory=list)
    scaled_pages: list = field(default_factory=list)
    smallest_scale: float = 1.0
    blank_added: bool = False
    copies: int = 1

    def summary(self) -> str:
        sizes = ", ".join(f"{count} x {size}" for size, count in self.source_sizes.items())
        edge = "short edge" if self.duplex_edge == DUPLEX_SHORT_EDGE else "long edge"
        parts = [f"{self.pages} pages on {self.sheets} sheets, flip on {edge}", f"source: {sizes}"]
        if self.copies > 1:
            parts.insert(1, f"{self.copies} copies")
        if self.scaled_pages:
            parts.append(f"{len(self.scaled_pages)} resized (smallest {self.smallest_scale:.0%})")
        if self.rotated_pages:
            parts.append(f"{len(self.rotated_pages)} rotated")
        return "; ".join(parts)


def _size_name(width_pt: float, height_pt: float) -> str:
    return f"{width_pt * MM_PER_PT:.0f}x{height_pt * MM_PER_PT:.0f}mm"


def _is_a4(width_pt: float, height_pt: float) -> bool:
    tolerance = A4_TOLERANCE_MM / MM_PER_PT
    return abs(width_pt - A4_WIDTH_PT) <= tolerance and abs(height_pt - A4_HEIGHT_PT) <= tolerance


def plan_copies(pdf_pages: int, spooled_pages: int, copies: int) -> tuple:
    """Return which captured pages make one set, and how many sets to print.

    The capture printer reports that it cannot make copies, so Windows repeats the pages
    in the captured PDF (always 1 2 3 1 2 3, even with collate off) while the job still
    states the copy count. Printing that PDF `copies` times would multiply the copies.
    Reducing it to one set lets each copy get its own blank back when needed, so copies
    never share a sheet.
    """
    if copies <= 1 or spooled_pages == 0:
        return list(range(pdf_pages)), 1
    if pdf_pages == spooled_pages * copies:
        return list(range(spooled_pages)), copies
    return list(range(pdf_pages)), copies


def normalize(source: Path, target: Path, copies: int = 1, spooled_pages: int = 0) -> Report:
    """Write `target` with one A4 portrait page for each page of one set in `source`.

    Landscape pages are turned to fit the sheet. Pages larger than A4 shrink to fit and
    smaller pages stay at 100%, centred. When several copies are due, an odd set gets a
    blank back, so that a second copy cannot start on the back of the first copy.
    """
    try:
        src = fitz.open(source)
    except Exception as exc:
        raise UnprintableDocument(f"not a readable PDF: {exc}") from exc

    with src:
        if src.is_encrypted or src.page_count == 0:
            raise UnprintableDocument("the document is locked or has no pages")

        keep, sets = plan_copies(src.page_count, spooled_pages, copies)
        report = Report(pages=len(keep), copies=sets)
        out = fitz.open()
        with out:
            for index in keep:
                rect = src[index].rect
                width, height = rect.width, rect.height
                name = _size_name(width, height)
                report.source_sizes[name] = report.source_sizes.get(name, 0) + 1

                landscape = width > height
                if landscape:
                    report.rotated_pages.append(index + 1)
                    width, height = height, width

                if _is_a4(width, height):
                    # Fill the sheet exactly, so true A4 pages stay at true size.
                    box = fitz.Rect(0, 0, A4_WIDTH_PT, A4_HEIGHT_PT)
                else:
                    scale = min(1.0, A4_WIDTH_PT / width, A4_HEIGHT_PT / height)
                    if scale < 1.0:
                        report.scaled_pages.append(index + 1)
                        report.smallest_scale = min(report.smallest_scale, scale)
                    left = (A4_WIDTH_PT - width * scale) / 2
                    top = (A4_HEIGHT_PT - height * scale) / 2
                    box = fitz.Rect(left, top, left + width * scale, top + height * scale)

                page = out.new_page(width=A4_WIDTH_PT, height=A4_HEIGHT_PT)
                page.show_pdf_page(box, src, index, rotate=90 if landscape else 0)

            # A landscape-only document reads like a book when flipped on the short edge.
            if len(report.rotated_pages) == report.pages:
                report.duplex_edge = DUPLEX_SHORT_EDGE

            if sets > 1 and out.page_count % 2:
                out.new_page(width=A4_WIDTH_PT, height=A4_HEIGHT_PT)
                report.blank_added = True

            report.sheets = (out.page_count + 1) // 2
            out.save(target, garbage=3, deflate=True)
    return report
