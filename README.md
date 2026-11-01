# duplex-guard

Reliable 2-sided printing on Windows from any app. Fixes page sizes and stops the driver silently
turning duplex off.

**Status:** early version, set up for the Epson L6460 on A4 paper only. A 4-page Letter-size test
job printed correctly on paper as 2 A4 sheets, on both sides and with no printer error. Word and
Acrobat were tested without paper, by checking the printer data. Printing from Chrome and Edge is
not yet tested.

## Using it

Print as usual and choose **L6460 Duplex** as the printer. This works from Word, Acrobat,
Chrome, Edge and anything else with a Print dialog. For one-sided printing, keep using
**EPSON L6460 Series**.

Printer settings in the Print dialog do not matter: every job is printed 2-sided on A4 plain
paper from the cassette. The print range and number of copies are still honoured.

| Your document | What happens |
|---|---|
| A4 pages | Printed at exactly 100% |
| Letter, Legal or larger pages | Shrunk to fit A4 and centred |
| Pages smaller than A4 | Kept at 100% and centred |
| Landscape pages | Turned to fit the sheet |
| Every page is landscape | Flips on the short edge, so it turns like a book |

## Known limits

- Thick paper, photo paper, letterhead, envelopes, Legal, Indian-Legal, 8.5 x 13 in and A5 cannot
  be printed 2-sided automatically. The driver does not allow it. Use **EPSON L6460 Series**.
- Several copies of an odd-page document from Word: Word repeats the pages itself, so nothing shows
  where a copy ends, and copy 2 starts on the back of copy 1's last sheet. Print the copies as
  separate jobs instead. Other routes tested keep copies on separate sheets.

## One setting on the printer

The printer's own paper setting must say **A4, Plain paper**. It is on the printer's screen, and
it usually asks when the cassette is put back in. The computer cannot read or change it.

## How it works

```
Any app -> "L6460 Duplex" printer -> named pipe -> background program
        -> every page rebuilt as A4 -> EPSON L6460 Series (A4, Cassette, Plain, 2-sided)
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
