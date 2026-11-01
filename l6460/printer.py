"""Print a normalized A4 PDF on the L6460 with explicit, verified settings."""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

import fitz
import win32con
import win32gui
import win32print
from PIL import Image

from .config import EPSON_QUEUE, MEDIA_PLAIN, PAPER_A4, SOURCE_CASSETTE

DM_OUT_BUFFER, DM_IN_BUFFER = 2, 8
PHYSICALWIDTH, PHYSICALHEIGHT = 110, 111
PHYSICALOFFSETX, PHYSICALOFFSETY = 112, 113
LOGPIXELSX, LOGPIXELSY = 88, 90
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
GDI_ERROR = -1


class PrinterRefused(Exception):
    """The driver would not keep the settings, or the job could not be sent."""


class _DocInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_int), ("lpszDocName", wintypes.LPCWSTR),
                ("lpszOutput", wintypes.LPCWSTR), ("lpszDatatype", wintypes.LPCWSTR),
                ("fwType", wintypes.DWORD)]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


_gdi = ctypes.WinDLL("gdi32", use_last_error=True)
_gdi.StartDocW.argtypes = [wintypes.HDC, ctypes.POINTER(_DocInfo)]
_gdi.StartDocW.restype = ctypes.c_int
for _name in ("StartPage", "EndPage", "EndDoc", "AbortDoc"):
    getattr(_gdi, _name).argtypes = [wintypes.HDC]
    getattr(_gdi, _name).restype = ctypes.c_int
_gdi.StretchDIBits.argtypes = [wintypes.HDC] + [ctypes.c_int] * 8 + [
    ctypes.c_void_p, ctypes.POINTER(_BitmapInfoHeader), wintypes.UINT, wintypes.DWORD]
_gdi.StretchDIBits.restype = ctypes.c_int


@dataclass
class SentJob:
    job_id: int
    pages: int
    dpi: int


def locked_devmode(handle, duplex_edge: int):
    """Return a devmode for A4, cassette, plain paper and duplex, checked by the driver.

    The driver can silently change settings it does not allow, such as turning duplex
    off, so what it hands back is compared with what was asked for.
    """
    wanted = win32print.GetPrinter(handle, 2)["pDevMode"]
    wanted.PaperSize = PAPER_A4
    wanted.Orientation = win32con.DMORIENT_PORTRAIT
    wanted.Duplex = duplex_edge
    wanted.DefaultSource = SOURCE_CASSETTE
    wanted.MediaType = MEDIA_PLAIN
    wanted.Scale = 100
    wanted.Copies = 1
    wanted.Fields &= ~(win32con.DM_PAPERLENGTH | win32con.DM_PAPERWIDTH)
    wanted.Fields |= (win32con.DM_ORIENTATION | win32con.DM_PAPERSIZE | win32con.DM_DUPLEX |
                      win32con.DM_DEFAULTSOURCE | win32con.DM_MEDIATYPE | win32con.DM_SCALE |
                      win32con.DM_COPIES)

    final = win32print.GetPrinter(handle, 2)["pDevMode"]
    win32print.DocumentProperties(0, handle, EPSON_QUEUE, final, wanted,
                                  DM_IN_BUFFER | DM_OUT_BUFFER)

    expected = {"PaperSize": PAPER_A4, "Duplex": duplex_edge,
                "DefaultSource": SOURCE_CASSETTE, "MediaType": MEDIA_PLAIN,
                "Orientation": win32con.DMORIENT_PORTRAIT}
    changed = {key: getattr(final, key) for key, value in expected.items()
               if getattr(final, key) != value}
    if changed:
        raise PrinterRefused(f"the Epson driver changed these settings: {changed}")
    return final


def _draw_page(hdc: int, page: fitz.Page) -> None:
    """Render one page at device resolution and place it on the physical sheet."""
    caps = win32print.GetDeviceCaps
    width, height = caps(hdc, PHYSICALWIDTH), caps(hdc, PHYSICALHEIGHT)
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(width / page.rect.width, height / page.rect.height), alpha=False)
    image = Image.frombuffer("RGB", (pixmap.width, pixmap.height), pixmap.samples, "raw", "RGB",
                             0, 1)
    stride = (pixmap.width * 3 + 3) & ~3  # DIB rows are 4-byte aligned, in BGR order.
    pixels = image.tobytes("raw", "BGR", stride)

    header = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), pixmap.width, -pixmap.height,
                               1, 24, 0, 0, 0, 0, 0, 0)
    # Coordinates start at the printable corner, so step back to the true paper corner.
    # That keeps both sides of a sheet aligned with each other.
    drawn = _gdi.StretchDIBits(hdc, -caps(hdc, PHYSICALOFFSETX), -caps(hdc, PHYSICALOFFSETY),
                               width, height, 0, 0, pixmap.width, pixmap.height, pixels,
                               ctypes.byref(header), DIB_RGB_COLORS, SRCCOPY)
    if drawn in (0, GDI_ERROR):
        raise PrinterRefused(f"the driver rejected the page image ({ctypes.get_last_error()})")


def send(pdf: Path, title: str, duplex_edge: int, copies: int = 1,
         to_file: Path | None = None) -> SentJob:
    """Send `pdf` to the Epson. `to_file` keeps the printer data in a file instead of printing."""
    handle = win32print.OpenPrinter(EPSON_QUEUE)
    try:
        devmode = locked_devmode(handle, duplex_edge)
    finally:
        win32print.ClosePrinter(handle)

    hdc = win32gui.CreateDC("WINSPOOL", EPSON_QUEUE, devmode)
    started = False
    try:
        # RAW makes the driver compress each page as it arrives. Without it Windows spools
        # about 100 MB of uncompressed image per A4 page.
        info = _DocInfo(ctypes.sizeof(_DocInfo), title[:200] or "L6460 Duplex",
                        str(to_file) if to_file else None, "RAW", 0)
        job_id = _gdi.StartDocW(hdc, ctypes.byref(info))
        if job_id <= 0:
            raise PrinterRefused(f"Windows would not start the job ({ctypes.get_last_error()})")
        started = True

        with fitz.open(pdf) as doc:
            for _ in range(copies):
                for page in doc:
                    if _gdi.StartPage(hdc) <= 0:
                        raise PrinterRefused("the driver would not start a page")
                    _draw_page(hdc, page)
                    if _gdi.EndPage(hdc) <= 0:
                        raise PrinterRefused("the driver would not finish a page")
            total = doc.page_count * copies

        if _gdi.EndDoc(hdc) <= 0:
            raise PrinterRefused("the driver would not finish the job")
        started = False
        return SentJob(job_id, total, win32print.GetDeviceCaps(hdc, LOGPIXELSX))
    finally:
        if started:
            _gdi.AbortDoc(hdc)  # Never leave half a job on the printer.
        win32gui.DeleteDC(hdc)
