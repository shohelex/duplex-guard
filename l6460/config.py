"""Fixed settings for the L6460 duplex tool."""
import os
from dataclasses import dataclass
from pathlib import Path

# The real printer, and the capture printers that apps print to. Each capture printer has its
# own pipe, so the background program knows which one a job was sent to.
EPSON_QUEUE = "EPSON L6460 Series"
CAPTURE_QUEUE = "L6460 Duplex"
CAPTURE_PORT = r"\\.\pipe\L6460Duplex"
ONE_SIDED_QUEUE = "L6460 One-sided"
ONE_SIDED_PORT = r"\\.\pipe\L6460OneSided"


@dataclass(frozen=True)
class Capture:
    queue: str
    port: str
    two_sided: bool


CAPTURES = (Capture(CAPTURE_QUEUE, CAPTURE_PORT, True),
            Capture(ONE_SIDED_QUEUE, ONE_SIDED_PORT, False))

# Values from the installed L6460 driver (DeviceCapabilities).
SOURCE_CASSETTE = 258
MEDIA_PLAIN = 1

ONE_SIDED = 1  # DMDUP_SIMPLEX
DUPLEX_LONG_EDGE = 2  # DMDUP_VERTICAL
DUPLEX_SHORT_EDGE = 3  # DMDUP_HORIZONTAL

MM_PER_PT = 25.4 / 72


@dataclass(frozen=True)
class Paper:
    name: str
    paper_id: int  # dmPaperSize: Windows ids, plus Epson's own id for 16K
    width_mm: float
    height_mm: float

    @property
    def width_pt(self) -> float:
        return self.width_mm / MM_PER_PT

    @property
    def height_pt(self) -> float:
        return self.height_mm / MM_PER_PT

    @property
    def label(self) -> str:
        return f"{self.name}  ({self.width_mm:g} x {self.height_mm:g} mm)"


# Only these sizes keep automatic 2-sided printing on the L6460 driver; it silently turns
# 2-sided off for every other size.
PAPERS = {
    "A4": Paper("A4", 9, 210, 297),
    "Letter": Paper("Letter", 1, 215.9, 279.4),
    "B5": Paper("B5", 13, 182, 257),
    "16K": Paper("16K", 341, 195, 270),
}
DEFAULT_PAPER = "A4"
A4 = PAPERS["A4"]
A4_WIDTH_PT = A4.width_pt
A4_HEIGHT_PT = A4.height_pt

# Pages within this many millimetres of the chosen paper are printed at exactly 100%.
SIZE_TOLERANCE_MM = 2.0

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "L6460Duplex"
INCOMING_DIR = DATA_DIR / "incoming"
FAILED_DIR = DATA_DIR / "failed"
LOG_FILE = DATA_DIR / "service.log"
SETTINGS_FILE = DATA_DIR / "settings.json"
