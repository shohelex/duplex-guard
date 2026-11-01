"""Page rebuilding tests. These use no printer and no paper."""
from pathlib import Path

import fitz
import pytest

from l6460.config import A4_HEIGHT_PT, A4_WIDTH_PT, DUPLEX_LONG_EDGE, DUPLEX_SHORT_EDGE
from l6460.normalize import UnprintableDocument, normalize, plan_copies

MM = 72 / 25.4
LETTER = (215.9 * MM, 279.4 * MM)
LEGAL = (215.9 * MM, 355.6 * MM)
A5 = (148 * MM, 210 * MM)
A4 = (A4_WIDTH_PT, A4_HEIGHT_PT)


def make_pdf(path: Path, sizes, rotate: int = 0) -> Path:
    """Each page has a solid red bar along its top edge."""
    doc = fitz.open()
    for width, height in sizes:
        page = doc.new_page(width=width, height=height)
        page.draw_rect(fitz.Rect(0, 0, width, 30), color=(1, 0, 0), fill=(1, 0, 0))
        if rotate:
            page.set_rotation(rotate)
    doc.save(path)
    doc.close()
    return path


def red_bounds(page: fitz.Page) -> fitz.Rect:
    """Find where the red bar landed, in page points."""
    pixmap = page.get_pixmap(dpi=36, alpha=False)
    points = [(x, y) for y in range(pixmap.height) for x in range(pixmap.width)
              if pixmap.pixel(x, y)[0] > 200 and pixmap.pixel(x, y)[1] < 80]
    assert points, "red bar is missing"
    xs, ys = zip(*points)
    return fitz.Rect(min(xs) * 2, min(ys) * 2, (max(xs) + 1) * 2, (max(ys) + 1) * 2)


def run(tmp_path, sizes, **options):
    source = make_pdf(tmp_path / "in.pdf", sizes, rotate=options.pop("rotate", 0))
    target = tmp_path / "out.pdf"
    report = normalize(source, target, **options)
    return fitz.open(target), report


@pytest.mark.parametrize("size", [LETTER, LEGAL, A5, A4, (A4_HEIGHT_PT, A4_WIDTH_PT)])
def test_every_page_comes_out_a4_portrait(tmp_path, size):
    doc, _ = run(tmp_path, [size])
    assert doc[0].rect.width == pytest.approx(A4_WIDTH_PT, abs=0.05)
    assert doc[0].rect.height == pytest.approx(A4_HEIGHT_PT, abs=0.05)


def test_mixed_sizes_all_become_a4(tmp_path):
    doc, report = run(tmp_path, [LETTER, A4, LEGAL])
    assert doc.page_count == 3
    assert {(round(p.rect.width), round(p.rect.height)) for p in doc} == {(595, 842)}
    assert report.scaled_pages == [1, 3]


def test_a4_page_stays_at_true_size(tmp_path):
    doc, report = run(tmp_path, [A4])
    assert report.scaled_pages == []
    bar = red_bounds(doc[0])
    assert bar.x0 == pytest.approx(0, abs=3)
    assert bar.y0 == pytest.approx(0, abs=3)
    assert bar.x1 == pytest.approx(A4_WIDTH_PT, abs=3)


def test_letter_shrinks_to_fit_width_and_is_centred(tmp_path):
    doc, report = run(tmp_path, [LETTER])
    assert report.smallest_scale == pytest.approx(210 / 215.9, abs=0.001)
    bar = red_bounds(doc[0])
    assert bar.x0 == pytest.approx(0, abs=3)
    assert bar.x1 == pytest.approx(A4_WIDTH_PT, abs=3)
    expected_gap = (A4_HEIGHT_PT - LETTER[1] * report.smallest_scale) / 2
    assert bar.y0 == pytest.approx(expected_gap, abs=3)


def test_legal_shrinks_to_fit_height(tmp_path):
    doc, report = run(tmp_path, [LEGAL])
    assert report.smallest_scale == pytest.approx(297 / 355.6, abs=0.001)


def test_small_page_is_not_enlarged(tmp_path):
    doc, report = run(tmp_path, [A5])
    assert report.scaled_pages == []
    bar = red_bounds(doc[0])
    assert bar.width == pytest.approx(A5[0], abs=4)
    assert bar.x0 == pytest.approx((A4_WIDTH_PT - A5[0]) / 2, abs=3)


def test_landscape_top_goes_to_left_edge_of_sheet(tmp_path):
    """Same turn a printer driver makes, so the reader turns the sheet clockwise."""
    doc, _ = run(tmp_path, [(A4_HEIGHT_PT, A4_WIDTH_PT)])
    bar = red_bounds(doc[0])
    assert bar.x0 == pytest.approx(0, abs=3)
    assert bar.width < 40
    assert bar.height == pytest.approx(A4_HEIGHT_PT, abs=4)


def test_page_with_rotate_flag_is_read_as_it_is_displayed(tmp_path):
    """A portrait page stored with /Rotate 90 displays as landscape."""
    doc, report = run(tmp_path, [A4], rotate=90)
    assert report.rotated_pages == [1]
    assert doc[0].rect.height == pytest.approx(A4_HEIGHT_PT, abs=0.05)


def test_portrait_document_flips_on_long_edge(tmp_path):
    _, report = run(tmp_path, [A4, A4])
    assert report.duplex_edge == DUPLEX_LONG_EDGE


def test_all_landscape_document_flips_on_short_edge(tmp_path):
    _, report = run(tmp_path, [(A4_HEIGHT_PT, A4_WIDTH_PT)] * 2)
    assert report.duplex_edge == DUPLEX_SHORT_EDGE


def test_mixed_orientation_stays_on_long_edge(tmp_path):
    _, report = run(tmp_path, [A4, (A4_HEIGHT_PT, A4_WIDTH_PT)])
    assert report.duplex_edge == DUPLEX_LONG_EDGE
    assert report.rotated_pages == [2]


def test_odd_set_gets_blank_back_only_for_several_copies(tmp_path):
    doc, report = run(tmp_path, [A4] * 3, copies=2, spooled_pages=3)
    assert doc.page_count == 4 and report.blank_added and report.sheets == 2
    doc.close()
    doc, report = run(tmp_path, [A4] * 3)
    assert doc.page_count == 3 and not report.blank_added and report.sheets == 2


def test_even_set_gets_no_blank(tmp_path):
    doc, report = run(tmp_path, [A4] * 2, copies=2, spooled_pages=2)
    assert doc.page_count == 2 and not report.blank_added


def test_pages_repeated_by_windows_are_not_multiplied_again(tmp_path):
    """3 pages x 2 copies arrive as 6 pages that still say 2 copies. Must print 2, not 4."""
    doc, report = run(tmp_path, [A4] * 6, copies=2, spooled_pages=3)
    assert report.copies == 2
    assert report.pages == 3
    assert doc.page_count == 4, "one set of 3 plus its blank back"


@pytest.mark.parametrize("pdf, spooled, copies, keep, sets", [
    (3, 3, 1, [0, 1, 2], 1),              # Ordinary single copy.
    (3, 3, 2, [0, 1, 2], 2),              # One set captured, the tool repeats it.
    (6, 3, 2, [0, 1, 2], 2),              # 1 2 3 1 2 3 repeated by Windows.
    (5, 0, 2, [0, 1, 2, 3, 4], 1),        # Unknown count: never risks extra paper.
])
def test_plan_copies(pdf, spooled, copies, keep, sets):
    assert plan_copies(pdf, spooled, copies) == (keep, sets)


def test_damaged_file_is_refused(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a pdf")
    with pytest.raises(UnprintableDocument):
        normalize(bad, tmp_path / "out.pdf")


def test_password_protected_file_is_refused(tmp_path):
    source = make_pdf(tmp_path / "in.pdf", [A4])
    locked = tmp_path / "locked.pdf"
    with fitz.open(source) as doc:
        doc.save(locked, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    with pytest.raises(UnprintableDocument):
        normalize(locked, tmp_path / "out.pdf")
