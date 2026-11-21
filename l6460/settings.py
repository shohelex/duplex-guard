"""The chosen paper size, and making it the default paper on both printers.

The default is the per-user one that Printing Preferences changes, and it is where every
app's Print dialog starts. Setting it needs no admin approval.
"""
import json
import logging

import pywintypes
import win32con
import win32print

from . import config
from .config import CAPTURES, DEFAULT_PAPER, EPSON_QUEUE, PAPERS, Paper

DM_OUT_BUFFER, DM_IN_BUFFER = 2, 8

log = logging.getLogger("l6460")


def load_paper() -> Paper:
    """Return the saved paper size, or A4 if none was saved or the file is unreadable."""
    try:
        name = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8")).get("paper")
    except (OSError, ValueError, AttributeError):
        name = None
    return PAPERS.get(name, PAPERS[DEFAULT_PAPER])


def save_paper(paper: Paper) -> None:
    config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.SETTINGS_FILE.write_text(json.dumps({"paper": paper.name}), encoding="utf-8")


def _apply_to(queue: str, paper: Paper) -> str:
    handle = win32print.OpenPrinter(queue)
    try:
        sizes = win32print.DeviceCapabilities(queue, "", win32con.DC_PAPERS)
        if paper.paper_id not in sizes:
            return f"{queue}: does not offer {paper.name}, left unchanged"

        # Start from what this user's apps see now, so other preferences are kept.
        wanted = win32print.GetPrinter(handle, 2)["pDevMode"]
        win32print.DocumentProperties(0, handle, queue, wanted, None, DM_OUT_BUFFER)
        wanted.PaperSize = paper.paper_id
        wanted.Fields &= ~(win32con.DM_PAPERLENGTH | win32con.DM_PAPERWIDTH)
        wanted.Fields |= win32con.DM_PAPERSIZE

        merged = win32print.GetPrinter(handle, 2)["pDevMode"]
        win32print.DocumentProperties(0, handle, queue, merged, wanted, DM_IN_BUFFER | DM_OUT_BUFFER)
        if merged.PaperSize != paper.paper_id:
            return f"{queue}: the driver refused {paper.name}"
        win32print.SetPrinter(handle, 9, {"pDevMode": merged}, 0)

        seen = win32print.GetPrinter(handle, 2)["pDevMode"]
        win32print.DocumentProperties(0, handle, queue, seen, None, DM_OUT_BUFFER)
        if seen.PaperSize != paper.paper_id:
            return f"{queue}: could not set {paper.name} (Windows kept size {seen.PaperSize})"
        return f"{queue}: default paper is now {paper.name}"
    finally:
        win32print.ClosePrinter(handle)


def apply_defaults(paper: Paper) -> list[tuple[bool, str]]:
    """Make `paper` the default on both printers. Returns (succeeded, message) per printer."""
    results = []
    for queue in (EPSON_QUEUE, *(capture.queue for capture in CAPTURES)):
        try:
            message = _apply_to(queue, paper)
            ok = message.endswith(f"now {paper.name}") or "does not offer" in message
        except pywintypes.error as exc:
            ok, message = False, f"{queue}: {exc.strerror}"
        log.info("default paper: %s", message)
        results.append((ok, message))
    return results
