# duplex-guard

Reliable 2-sided printing on Windows from any app. Fixes page sizes and stops the driver silently
turning duplex off.

**Status:** early version, set up for the Epson L6460 on A4 paper only. A 4-page Letter-size test
job printed correctly on paper as 2 A4 sheets, on both sides and with no printer error. Word and
Acrobat were tested without paper, by checking the printer data. Printing from Chrome and Edge is
not yet tested.

## Using it

Choose one-sided or 2-sided by choosing the printer, in any app's Print dialog:

| Printer | Prints |
|---|---|
| **L6460 Duplex** (the default) | 2-sided |
| **L6460 One-sided** | one-sided |

Both fix the paper size and margins the same way. Their Print dialogs have no 1-sided/2-sided
option, because the Windows PDF driver they are built on has none. **EPSON L6460 Series** is
still there, but it prints whatever paper size the app sends.

Printer settings in the Print dialog do not matter: every job is printed 2-sided on plain paper
from the cassette, at the paper size chosen in the settings window. The print range and number
of copies are still honoured.

## Paper size

Click the tray icon, or open **duplex-guard settings** from the Start menu, to see and change the
paper size. It is A4 until you change it. Only A4, Letter, B5 and 16K are offered, because the
driver turns 2-sided off for every other size.

Saving does three things:

- every job on **L6460 Duplex** is fitted to that size;
- that size becomes your default paper on both **EPSON L6460 Series** and **L6460 Duplex**, so
  every app's Print dialog starts with it, including when you choose 2-sided on the Epson itself;
- the background program sets it again each time it starts, in case something replaced it.

Set the same size on the printer's own screen. The computer cannot change that setting.

A default only sets the size an app starts with, and an app can still choose another size. Acrobat
Reader, for example, sent a 210 x 280 mm PDF as Letter. So:

- **L6460 Duplex is the default printer**, so it is already chosen when you print. Pick
  **L6460 One-sided** for one-sided printing. Windows' option to switch the default
  printer by itself is turned off, so this stays.
- **The Epson is guarded.** If a 2-sided job reaches **EPSON L6460 Series** with a paper size
  other than the chosen one, the background program pauses it straight away and asks whether
  to cancel it (then reprint with L6460 Duplex) or print it anyway. It cannot correct such a
  job, because Windows has already laid the pages out for the wrong size.

| Your document | What happens |
|---|---|
| Pages already the chosen size | Printed at exactly 100% |
| Larger pages | Shrunk to fit and centred |
| Smaller pages | Kept at 100% and centred |
| Landscape pages | Turned to fit the sheet |
| Every page is landscape | Flips on the short edge, so it turns like a book |

## Known limits

- Thick paper, photo paper, letterhead, envelopes, Legal, Indian-Legal, 8.5 x 13 in and A5 cannot
  be printed 2-sided automatically. The driver does not allow it. Use **EPSON L6460 Series**.
- Several copies of an odd-page document from Word: Word repeats the pages itself, so nothing shows
  where a copy ends, and copy 2 starts on the back of copy 1's last sheet. Print the copies as
  separate jobs instead. Other routes tested keep copies on separate sheets.

## One setting on the printer

The printer's own paper setting must say **the chosen size, Plain paper**. It is on the printer's screen, and
it usually asks when the cassette is put back in. The computer cannot read or change it.

## How it works

```
Any app -> "L6460 Duplex" printer -> named pipe -> background program
        -> every page rebuilt at the chosen size -> EPSON L6460 Series (that size, Cassette,
           Plain, 2-sided)
```

- The driver can silently turn 2-sided off, so the tool checks the settings it hands back. If
  any changed, it shows a message and prints nothing.
- If the background program is not running, jobs wait in the Windows queue and are not lost.
- Jobs that cannot be printed are saved in `%LOCALAPPDATA%\L6460Duplex\failed`.
- The log is at `%LOCALAPPDATA%\L6460Duplex\service.log`.

## Install and remove

Each script asks for Windows admin approval once. Neither one changes the existing Epson printer.

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
```

Needs the Epson L6460 driver, with the printer named exactly `EPSON L6460 Series`, and Python 3.11
on PATH with its add-ons:

```powershell
python -m pip install pymupdf pillow pywin32
```

Keep the folder in place after installing, because the background program runs from it.

## Tests

```powershell
python -m pytest tests
```

The tests use no paper. The printer tests run the real Epson driver, write its output to a file
and check the bytes that would reach the printer. The driver's limits were read from the installed
driver: 2-sided works only on A4, Letter, B5 and 16K, and only on plain paper.

To follow a whole job without paper, stop the background program and run
`python -m l6460 serve --to-file FOLDER`, then confirm `test mode` in the log before printing. Do
not change the Windows default printer for a test: Windows manages it on this PC and may ignore
the change, and silent browser printing then goes to the real printer.
