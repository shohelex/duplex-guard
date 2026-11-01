"""Background program behind the "L6460 Duplex" printer.

Apps print to that printer, whose port is a named pipe. Each job arrives here as a PDF, is
rebuilt as A4, and is then sent to the Epson with fixed settings.

If this program is not running, the pipe does not exist. Windows then keeps the job waiting
in the queue and retries, so a job is not lost.
"""
import ctypes
import logging
import logging.handlers
import queue
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import pywintypes
import win32api
import win32con
import win32event
import win32file
import win32gui
import win32pipe
import win32print
import winerror

from . import printer
from .config import CAPTURE_PORT, CAPTURE_QUEUE, DATA_DIR, EPSON_QUEUE, FAILED_DIR, INCOMING_DIR, LOG_FILE
from .normalize import UnprintableDocument, normalize

PIPE_BUFFER = 1 << 16
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
JOB_STATUS_PRINTING = 0x10
JOB_TROUBLE = (win32print.JOB_STATUS_ERROR | win32print.JOB_STATUS_OFFLINE |
               win32print.JOB_STATUS_PAPEROUT | win32print.JOB_STATUS_USER_INTERVENTION |
               win32print.JOB_STATUS_BLOCKED_DEVQ)
WATCH_SECONDS = 15 * 60

log = logging.getLogger("l6460")


@dataclass
class CapturedJob:
    path: Path
    title: str = "Print job"
    copies: int = 1
    spooled_pages: int = 0


class Tray:
    """Tray icon that shows the program is running and displays short notices."""

    ICON_ID = 1

    def __init__(self):
        self._ready = threading.Event()
        self._hwnd = 0
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(5)

    def _base(self):
        icon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
        return self._hwnd, self.ICON_ID, win32gui.NIF_ICON | win32gui.NIF_TIP, 0, icon, CAPTURE_QUEUE

    def _run(self):
        try:
            self._hwnd = win32gui.CreateWindow("STATIC", CAPTURE_QUEUE, 0, 0, 0, 0, 0, 0, 0, None, None)
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, self._base())
        except pywintypes.error:
            log.warning("tray icon unavailable", exc_info=True)
            self._hwnd = 0
        finally:
            self._ready.set()
        win32gui.PumpMessages()

    def notice(self, title: str, message: str) -> None:
        if not self._hwnd:
            return
        hwnd, icon_id, flags, callback, icon, tip = self._base()
        data = (hwnd, icon_id, flags | win32gui.NIF_INFO, callback, icon, tip,
                message[:250], 10000, title[:60], win32gui.NIIF_INFO)
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, data)
        except pywintypes.error:
            log.warning("could not show notice", exc_info=True)


def alert(message: str) -> None:
    """Show a problem the user must see, without holding up the next job."""
    log.error(message)
    flags = win32con.MB_OK | win32con.MB_ICONWARNING | win32con.MB_SETFOREGROUND | win32con.MB_TOPMOST
    threading.Thread(target=ctypes.windll.user32.MessageBoxW,
                     args=(0, message, CAPTURE_QUEUE, flags), daemon=True).start()


def describe_current_job() -> dict:
    """Return what Windows knows about the job it is sending now."""
    try:
        handle = win32print.OpenPrinter(CAPTURE_QUEUE)
    except pywintypes.error:
        return {}
    try:
        jobs = win32print.EnumJobs(handle, 0, 32, 2)
    finally:
        win32print.ClosePrinter(handle)
    for job in jobs:
        if job["Status"] & JOB_STATUS_PRINTING:
            devmode = job.get("pDevMode")
            return {"title": job.get("pDocument") or "Print job",
                    "copies": max(1, getattr(devmode, "Copies", 1)),
                    "spooled_pages": job.get("TotalPages", 0)}
    return {}


def receive(pipe) -> Path | None:
    """Save one job from a connected pipe, or return None if it carried no data."""
    target = INCOMING_DIR / f"{uuid.uuid4().hex}.pdf"
    received = 0
    with target.open("wb") as out:
        while True:
            try:
                _, chunk = win32file.ReadFile(pipe, PIPE_BUFFER)
            except pywintypes.error as exc:
                if exc.winerror in (winerror.ERROR_BROKEN_PIPE, winerror.ERROR_PIPE_NOT_CONNECTED):
                    break
                raise
            out.write(chunk)
            received += len(chunk)
    if received == 0:
        target.unlink()  # Windows opens the port briefly just to test it.
        return None
    return target


def capture_loop(jobs: "queue.Queue[CapturedJob]") -> None:
    mode = (win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT |
            PIPE_REJECT_REMOTE_CLIENTS)
    while True:
        pipe = win32pipe.CreateNamedPipe(CAPTURE_PORT, win32pipe.PIPE_ACCESS_DUPLEX, mode,
                                         win32pipe.PIPE_UNLIMITED_INSTANCES, PIPE_BUFFER,
                                         PIPE_BUFFER, 0, None)
        try:
            win32pipe.ConnectNamedPipe(pipe, None)
            details = describe_current_job()
            path = receive(pipe)
            if path:
                job = CapturedJob(path, **details)
                log.info("captured %s, %s bytes", job, path.stat().st_size)
                jobs.put(job)
        except pywintypes.error:
            log.exception("capture failed")
            time.sleep(1)
        finally:
            win32file.CloseHandle(pipe)


def watch(job_id: int, title: str) -> None:
    """Follow a job on the Epson and report if it stops with a problem."""
    handle = win32print.OpenPrinter(EPSON_QUEUE)
    warned = False
    deadline = time.monotonic() + WATCH_SECONDS
    try:
        while time.monotonic() < deadline:
            try:
                job = win32print.GetJob(handle, job_id, 2)
            except pywintypes.error:
                return  # The job has left the queue.
            if job["Status"] & JOB_TROUBLE and not warned:
                warned = True
                detail = job.get("pStatus") or "the printer needs attention"
                alert(f"'{title}' has stopped: {detail}.\n\nCheck the printer's screen. "
                      "If it mentions paper, make sure the cassette holds A4 and that the "
                      "printer's paper setting says A4, Plain paper.")
            time.sleep(2)
    finally:
        win32print.ClosePrinter(handle)


def process(job: CapturedJob, tray: Tray, to_file: Path | None) -> None:
    clean = job.path.with_suffix(".a4.pdf")
    try:
        report = normalize(job.path, clean, job.copies, job.spooled_pages)
        log.info("%r: %s", job.title, report.summary())
        tray.notice("Preparing 2-sided print", f"{job.title}\n{report.summary()}")
        output = to_file / f"{job.path.stem}.prn" if to_file else None
        sent = printer.send(clean, job.title, report.duplex_edge, report.copies, to_file=output)
        log.info("sent %r as Epson job %d, %d pages", job.title, sent.job_id, sent.pages)
        if not to_file:
            watch(sent.job_id, job.title)
    except (UnprintableDocument, printer.PrinterRefused, pywintypes.error) as exc:
        kept = FAILED_DIR / job.path.name
        shutil.move(job.path, kept)
        alert(f"'{job.title}' was not printed, so no paper was used.\n\nReason: {exc}\n\n"
              f"A copy is saved at:\n{kept}")
    else:
        job.path.unlink()
    finally:
        clean.unlink(missing_ok=True)


def worker_loop(jobs: "queue.Queue[CapturedJob]", tray: Tray, to_file: Path | None) -> None:
    while True:
        job = jobs.get()
        try:
            process(job, tray, to_file)
        except Exception:
            log.exception("unexpected failure on %r", job.title)
            alert(f"'{job.title}' could not be printed because of an unexpected error. "
                  f"Details are in {LOG_FILE}.")


def set_up_logging() -> None:
    for folder in (DATA_DIR, INCOMING_DIR, FAILED_DIR):
        folder.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def set_aside_leftovers() -> None:
    """Move unfinished jobs aside. Printing them again could duplicate a finished job."""
    for leftover in INCOMING_DIR.glob("*.pdf"):
        if leftover.name.endswith(".a4.pdf"):
            leftover.unlink()
        else:
            shutil.move(leftover, FAILED_DIR / leftover.name)
            log.warning("set aside unfinished job %s", leftover.name)


def serve(to_file: Path | None = None) -> None:
    set_up_logging()
    mutex = win32event.CreateMutex(None, False, "Local\\L6460DuplexService")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        log.info("already running")
        return

    set_aside_leftovers()
    log.info("started%s", f" (test mode, writing to {to_file})" if to_file else "")
    jobs: "queue.Queue[CapturedJob]" = queue.Queue()
    tray = Tray()
    threading.Thread(target=worker_loop, args=(jobs, tray, to_file), daemon=True).start()
    try:
        capture_loop(jobs)
    finally:
        win32api.CloseHandle(mutex)
