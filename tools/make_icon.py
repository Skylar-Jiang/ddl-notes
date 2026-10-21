"""Generate our code-drawn icon; no downloaded image or font dependency."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddl_notes.windows import tray_image


target = Path(__file__).resolve().parents[1] / 'ddl_notes' / 'assets'
target.mkdir(exist_ok=True)
tray_image().save(target / 'app.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])
