"""Small settings window: choose the paper size used for every 2-sided print."""
import tkinter as tk
from tkinter import ttk

import win32event
import win32api
import winerror

from .config import PAPERS
from .settings import apply_defaults, load_paper, save_paper


def run() -> None:
    mutex = win32event.CreateMutex(None, False, "Local\\DuplexGuardSettings")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        return  # The window is already open.

    current = load_paper()
    root = tk.Tk()
    root.title("duplex-guard")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=16)
    frame.grid()

    ttk.Label(frame, text="Paper size for 2-sided printing",
              font=("Segoe UI", 11, "bold")).grid(sticky="w")
    ttk.Label(frame, text=f"Currently: {current.label}").grid(sticky="w", pady=(2, 10))

    labels = {paper.label: paper for paper in PAPERS.values()}
    choice = tk.StringVar(value=current.label)
    ttk.Combobox(frame, textvariable=choice, values=list(labels), state="readonly",
                 width=32).grid(sticky="w")

    ttk.Label(frame, wraplength=360, justify="left", text=(
        "Saving makes this size the default paper on EPSON L6460 Series, L6460 Duplex and "
        "L6460 One-sided, "
        "so every app's Print dialog starts with it. Every job printed on L6460 Duplex or "
        "L6460 One-sided is "
        "fitted to it.\n\nSet the same size and Plain paper on the printer's own screen, "
        "and load that paper in the cassette. Only these sizes allow automatic 2-sided "
        "printing.")).grid(sticky="w", pady=10)

    status = ttk.Label(frame, wraplength=360, justify="left", text="")
    status.grid(sticky="w")

    def save() -> None:
        paper = labels[choice.get()]
        save_paper(paper)
        results = apply_defaults(paper)
        mark = {True: "OK", False: "PROBLEM"}
        status.config(text="\n".join(f"{mark[ok]}: {message}" for ok, message in results))

    buttons = ttk.Frame(frame)
    buttons.grid(sticky="e", pady=(10, 0))
    ttk.Button(buttons, text="Save", command=save).grid(row=0, column=0, padx=4)
    ttk.Button(buttons, text="Close", command=root.destroy).grid(row=0, column=1)

    root.mainloop()
    win32api.CloseHandle(mutex)
