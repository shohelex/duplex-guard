"""Printer tests. They use the installed Epson driver but send its output to a file.

No paper is used: StartDoc's output path keeps the data away from the USB port.
"""
import time
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from l6460 import printer
from l6460.config import A4_HEIGHT_PT, A4_WIDTH_PT, DUPLEX_LONG_EDGE, DUPLEX_SHORT_EDGE

REMOTE = b"\x1b(R\x08\x00\x00REMOTE1"
A4_AT_600_DPI = (4960, 7014)


def remote_settings(data: bytes) -> dict:
    """Read the two-letter commands of every remote block, keeping each first value.

    The first value is what the job asks for. The closing block resets some of them.
    """
    found = {}
    start = data.find(REMOTE)
    while start >= 0:
        cursor = start + len(REMOTE)
        while data[cursor] != 0x1b:
            name = data[cursor:cursor + 2].decode()
            length = int.from_bytes(data[cursor + 2:cursor + 4], "little")
            found.setdefault(name, data[cursor + 4:cursor + 4 + length])
            cursor += 4 + length
        start = data.find(REMOTE, cursor)
    return found


def sheet_size(data: bytes) -> tuple:
    """Read the paper size, in 1/600 inch, from the job set-up command."""
    payload = data[data.index(b"setj") + 4:]
    return int.from_bytes(payload[:4], "big"), int.from_bytes(payload[4:8], "big")


def wait_for(path: Path) -> bytes:
    for _ in range(200):
        if path.exists() and path.stat().st_size:
            size = path.stat().st_size
            time.sleep(0.5)
            if path.stat().st_size == size:
                return path.read_bytes()
        time.sleep(0.25)
    raise TimeoutError(path)


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "sample.pdf"
    doc = fitz.open()
    for number in (1, 2):
        doc.new_page(width=A4_WIDTH_PT, height=A4_HEIGHT_PT).insert_text((72, 100), f"Page {number}")
    doc.save(path)
    doc.close()
    return path


@pytest.mark.parametrize("edge", [DUPLEX_LONG_EDGE, DUPLEX_SHORT_EDGE])
def test_printer_data_says_a4_cassette_duplex(tmp_path, sample, edge):
    output = tmp_path / "job.prn"
    sent = printer.send(sample, "test", edge, to_file=output)
    data = wait_for(output)
    settings = remote_settings(data)
    assert sent.pages == 2
    assert settings["DP"] == b"\x00\x02", "duplex must be on"
    assert settings["PP"] == b"\x00\x01\x01", "paper must come from the cassette"
    assert sheet_size(data) == A4_AT_600_DPI


def test_copies_repeat_the_whole_document(tmp_path, sample):
    output = tmp_path / "job.prn"
    sent = printer.send(sample, "test", DUPLEX_LONG_EDGE, copies=3, to_file=output)
    wait_for(output)
    assert sent.pages == 6


def test_job_stops_if_driver_changes_a_setting(monkeypatch):
    """The driver drops duplex silently on some settings. The tool must refuse, not print."""
    real = printer.win32print.DocumentProperties

    def drop_duplex(hwnd, handle, name, output, source, mode):
        result = real(hwnd, handle, name, output, source, mode)
        output.Duplex = 1
        return result

    monkeypatch.setattr(printer.win32print, "DocumentProperties", drop_duplex)
    handle = printer.win32print.OpenPrinter(printer.EPSON_QUEUE)
    try:
        with pytest.raises(printer.PrinterRefused, match="Duplex"):
            printer.locked_devmode(handle, DUPLEX_LONG_EDGE)
    finally:
        printer.win32print.ClosePrinter(handle)


def test_refused_settings_create_no_job(tmp_path, sample, monkeypatch):
    def refuse(handle, edge):
        raise printer.PrinterRefused("no")

    monkeypatch.setattr(printer, "locked_devmode", refuse)
    started = SimpleNamespace(called=False)
    monkeypatch.setattr(printer.win32gui, "CreateDC",
                        lambda *args: setattr(started, "called", True))
    with pytest.raises(printer.PrinterRefused):
        printer.send(sample, "test", DUPLEX_LONG_EDGE, to_file=tmp_path / "job.prn")
    assert not started.called
