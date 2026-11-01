"""Fixed settings for the L6460 duplex tool."""
import os
from pathlib import Path

# The real printer, and the capture printer that apps print to.
EPSON_QUEUE = "EPSON L6460 Series"
CAPTURE_QUEUE = "L6460 Duplex"
CAPTURE_PORT = r"\\.\pipe\L6460Duplex"

# Values from the installed L6460 driver (DeviceCapabilities).
PAPER_A4 = 9
SOURCE_CASSETTE = 258
MEDIA_PLAIN = 1

DUPLEX_LONG_EDGE = 2  # DMDUP_VERTICAL
DUPLEX_SHORT_EDGE = 3  # DMDUP_HORIZONTAL

# A4 in PDF points (1/72 inch).
A4_WIDTH_PT = 210 / 25.4 * 72
A4_HEIGHT_PT = 297 / 25.4 * 72
MM_PER_PT = 25.4 / 72

# Pages within this many millimetres of A4 are printed at exactly 100%.
A4_TOLERANCE_MM = 2.0

DATA_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "L6460Duplex"
INCOMING_DIR = DATA_DIR / "incoming"
FAILED_DIR = DATA_DIR / "failed"
LOG_FILE = DATA_DIR / "service.log"
