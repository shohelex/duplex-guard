"""Background program behind the "L6460 Duplex" printer.

Apps print to that printer, whose port is a named pipe. Each job arrives here as a PDF, is
rebuilt at the chosen paper size, and is then sent to the Epson with fixed settings.

If this program is not running, the pipe does not exist. Windows then keeps the job waiting
in the queue and retries, so a job is not lost.
"""
import ctypes
import logging
import logging.handlers
import queue
import shutil
import subprocess
import sys
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
from .config import (CAPTURE_QUEUE, CAPTURES, DATA_DIR, EPSON_QUEUE, FAILED_DIR, INCOMING_DIR,
                     LOG_FILE, Capture)
from .normalize import UnprintableDocument, normalize
from .settings import apply_defaults, load_paper

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
    two_sided: bool = True


class Tray:
    """Tray icon: shows the program is running and the paper size, opens the settings
    window when clicked, and displays short notices."""

    ICON_ID = 1
    CALLBACK = win32con.WM_USER + 20

    def __init__(self):
        self._ready = threading.Event()
        self._hwnd = 0
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(5)

    def _base(self):
        icon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
        tip = f"duplex-guard: {load_paper().name} paper. Click for settings."
        flags = win32gui.NIF_ICON | win32gui.NIF_TIP | win32gui.NIF_MESSAGE
        return self._hwnd, self.ICON_ID, flags, self.CALLBACK, icon, tip[:127]

    def _on_tray(self, hwnd, message, wparam, lparam):
        if lparam in (win32con.WM_LBUTTONUP, win32con.WM_RBUTTONUP):
            open_settings()
        return 0

    def _add_icon(self) -> bool:
        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, self._base())
            return True
        except pywintypes.error:
            return False

    def _on_taskbar_created(self, hwnd, message, wparam, lparam):
        self._add_icon()  # Explorer restarted, and the old icon went with it.
        return 0

    def _run(self):
        try:
            window_class = win32gui.WNDCLASS()
            window_class.hInstance = win32api.GetModuleHandle(None)
            window_class.lpszClassName = "DuplexGuardTray"
            taskbar_created = win32gui.RegisterWindowMessage("TaskbarCreated")
            window_class.lpfnWndProc = {self.CALLBACK: self._on_tray,
                                        taskbar_created: self._on_taskbar_created}
            win32gui.RegisterClass(window_class)
            self._hwnd = win32gui.CreateWindow(window_class.lpszClassName, CAPTURE_QUEUE, 0,
                                               0, 0, 0, 0, 0, 0, window_class.hInstance, None)
        except pywintypes.error:
            log.warning("tray window unavailable", exc_info=True)
            self._hwnd = 0
            self._ready.set()
            return
        self._ready.set()
        # At login the taskbar may not be ready yet, so keep trying for two minutes.
        for _ in range(60):
            if self._add_icon():
                break
            time.sleep(2)
        else:
            log.warning("tray icon could not be added")
        win32gui.PumpMessages()

    def refresh(self) -> None:
        """Show the current paper size in the tooltip."""
        if self._hwnd:
            try:
                win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, self._base())
            except pywintypes.error:
                pass

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


def open_settings() -> None:
    """Open the settings window in its own process, so it never holds up printing."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(pythonw if pythonw.exists() else sys.executable), "-m", "l6460",
                      "settings"], cwd=str(Path(__file__).resolve().parents[1]))


def alert(message: str) -> None:
    """Show a problem the user must see, without holding up the next job."""
    log.error(message)
    flags = win32con.MB_OK | win32con.MB_ICONWARNING | win32con.MB_SETFOREGROUND | win32con.MB_TOPMOST
    threading.Thread(target=ctypes.windll.user32.MessageBoxW,
                     args=(0, message, CAPTURE_QUEUE, flags), daemon=True).start()


def describe_current_job(queue_name: str = CAPTURE_QUEUE) -> dict:
    """Return what Windows knows about the job it is sending now."""
    try:
        handle = win32print.OpenPrinter(queue_name)
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


def capture_loop(jobs: "queue.Queue[CapturedJob]", capture: Capture) -> None:
    mode = (win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT |
            PIPE_REJECT_REMOTE_CLIENTS)
    while True:
        pipe = win32pipe.CreateNamedPipe(capture.port, win32pipe.PIPE_ACCESS_DUPLEX, mode,
                                         win32pipe.PIPE_UNLIMITED_INSTANCES, PIPE_BUFFER,
                                         PIPE_BUFFER, 0, None)
        try:
            win32pipe.ConnectNamedPipe(pipe, None)
            details = describe_current_job(capture.queue)
            path = receive(pipe)
            if path:
                job = CapturedJob(path, **details, two_sided=capture.two_sided)
                log.info("captured %s, %s bytes", job, path.stat().st_size)
                jobs.put(job)
        except pywintypes.error:
            log.exception("capture failed")
            time.sleep(1)
        finally:
            win32file.CloseHandle(pipe)


def watch(job_id: int, title: str, paper_name: str) -> None:
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
                      f"If it mentions paper, make sure the cassette holds {paper_name} and "
                      f"that the printer's paper setting says {paper_name}, Plain paper.")
            time.sleep(2)
    finally:
        win32print.ClosePrinter(handle)


def process(job: CapturedJob, tray: Tray, to_file: Path | None) -> None:
    clean = job.path.with_suffix(".a4.pdf")
    paper = load_paper()  # Read per job, so a change in the settings window applies at once.
    tray.refresh()
    try:
        report = normalize(job.path, clean, job.copies, job.spooled_pages, paper, job.two_sided)
        log.info("%r: %s", job.title, report.summary())
        kind = "2-sided" if job.two_sided else "one-sided"
        tray.notice(f"Preparing {kind} print", f"{job.title}\n{report.summary()}")
        output = to_file / f"{job.path.stem}.prn" if to_file else None
        sent = printer.send(clean, job.title, report.duplex_edge, report.copies, to_file=output,
                            paper=paper)
        log.info("sent %r as Epson job %d, %d pages", job.title, sent.job_id, sent.pages)
        if not to_file:
            watch(sent.job_id, job.title, paper.name)
    except (UnprintableDocument, printer.PrinterRefused, pywintypes.error) as exc:
        kept = FAILED_DIR / job.path.name
        shutil.move(job.path, kept)
        alert(f"'{job.title}' was not printed, so no paper was used.\n\nReason: {exc}\n\n"
              f"A copy is saved at:\n{kept}")
    else:
        job.path.unlink()
    finally:
        clean.unlink(missing_ok=True)


GUARD_INTERVAL = 0.25
DMDUP_SIMPLEX = 1


def paper_name(paper_id: int) -> str:
    """Name of a paper size as the Epson driver calls it."""
    try:
        ids = win32print.DeviceCapabilities(EPSON_QUEUE, "", win32con.DC_PAPERS)
        names = win32print.DeviceCapabilities(EPSON_QUEUE, "", win32con.DC_PAPERNAMES)
        return dict(zip(ids, names)).get(paper_id, f"size {paper_id}").strip()
    except pywintypes.error:
        return f"size {paper_id}"


def wrong_size_for_duplex(devmode, paper) -> bool:
    """A 2-sided job whose paper differs from the paper in the cassette."""
    return (devmode is not None and devmode.Duplex != DMDUP_SIMPLEX
            and devmode.PaperSize != paper.paper_id)


def ask_about_paused(job_id: int, title: str, asked: str, paper_name_: str) -> None:
    flags = (win32con.MB_YESNO | win32con.MB_ICONWARNING | win32con.MB_SETFOREGROUND |
             win32con.MB_TOPMOST | win32con.MB_DEFBUTTON1)
    answer = ctypes.windll.user32.MessageBoxW(0, (
        f"'{title}' was sent to EPSON L6460 Series as 2-sided on {asked} paper, but your paper "
        f"is {paper_name_}. It has been paused so that no paper is wasted.\n\n"
        f"Yes: cancel it. Then print again and choose the printer {CAPTURE_QUEUE}, which "
        f"always uses {paper_name_}.\n\nNo: print it anyway."), CAPTURE_QUEUE, flags)
    command = win32print.JOB_CONTROL_DELETE if answer == win32con.IDYES else win32print.JOB_CONTROL_RESUME
    try:
        handle = win32print.OpenPrinter(EPSON_QUEUE)
        try:
            win32print.SetJob(handle, job_id, 0, None, command)
        finally:
            win32print.ClosePrinter(handle)
        log.info("guard: job %d %s by the user", job_id,
                 "cancelled" if command == win32print.JOB_CONTROL_DELETE else "resumed")
    except pywintypes.error:
        log.info("guard: job %d had already left the queue", job_id)


def guard_loop() -> None:
    """Pause 2-sided jobs sent straight to the Epson with the wrong paper size.

    Windows has already laid such a job out for that size, so it cannot be corrected,
    only stopped before it wastes paper.
    """
    handle = win32print.OpenPrinter(EPSON_QUEUE)
    checked: set[int] = set()
    while True:
        try:
            jobs = win32print.EnumJobs(handle, 0, 64, 2)
        except pywintypes.error:
            time.sleep(2)
            continue
        paper = load_paper()
        for job in jobs:
            job_id, devmode = job["JobId"], job.get("pDevMode")
            if job_id in checked or devmode is None:
                continue
            checked.add(job_id)
            # This tool sends its own jobs as RAW, and they already have the right settings.
            # Apps send EMF.
            if job.get("pDatatype") == "RAW" or not wrong_size_for_duplex(devmode, paper):
                continue
            try:
                win32print.SetJob(handle, job_id, 0, None, win32print.JOB_CONTROL_PAUSE)
            except pywintypes.error:
                log.warning("guard: could not pause job %d", job_id, exc_info=True)
                continue
            asked = paper_name(devmode.PaperSize)
            log.warning("guard: paused job %d %r, 2-sided on %s instead of %s",
                        job_id, job.get("pDocument"), asked, paper.name)
            threading.Thread(target=ask_about_paused, daemon=True,
                             args=(job_id, job.get("pDocument") or "Print job", asked,
                                   paper.name)).start()
        checked &= {job["JobId"] for job in jobs}
        time.sleep(GUARD_INTERVAL)


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
    # Put the chosen size back as the default, in case a driver update or a change in
    # Printing Preferences replaced it.
    apply_defaults(load_paper())
    jobs: "queue.Queue[CapturedJob]" = queue.Queue()
    tray = Tray()
    threading.Thread(target=worker_loop, args=(jobs, tray, to_file), daemon=True).start()
    if not to_file:
        threading.Thread(target=guard_loop, daemon=True).start()
    for capture in CAPTURES[1:]:
        threading.Thread(target=capture_loop, args=(jobs, capture), daemon=True).start()
    try:
        capture_loop(jobs, CAPTURES[0])
    finally:
        win32api.CloseHandle(mutex)
