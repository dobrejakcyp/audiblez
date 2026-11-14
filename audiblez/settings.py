"""
settings.py - remembers your choices between sessions (voice, speed, folders, window size ...).

They are kept in a small, human-readable JSON file next to the program:

    C:\\Users\\lukas\\audiblez\\settings.json

The window loads it when it opens and saves it when it closes (and when a conversion starts).
Delete the file to go back to the defaults. A broken or outdated file is never an error:
every value that is missing or has the wrong type simply falls back to its default.
"""
import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "settings.json"


@dataclass
class UserSettings:
    voice_id: str = "bm_george"
    speed: float = 1.0
    device: str = "cuda"  # "cuda" or "cpu"
    library_folder: str = ""  # the audiobook library (library.py); "" = Documents\\Audiobook Library
    last_book_folder: str = ""  # where the Import dialog starts (e.g. Downloads)
    show_short_files: bool = False
    window_size: list = field(default_factory=list)  # [width, height]; empty = choose automatically
    window_position: list = field(default_factory=list)  # [x, y]
    window_maximized: bool = False
    tool_column_width: int = 0  # pixels; 0 = the default width
    text_font_face: str = ""  # font of the book text; "" = the system default (see fonts.py)
    text_font_size: int = 12
    favourite_fonts: list = field(default_factory=list)  # the user's own recommended fonts
    picture_text_removed: dict = field(default_factory=dict)  # book file name -> CSS classes removed (tool 6)

    @classmethod
    def load(cls, path=SETTINGS_FILE):
        settings = cls()
        try:
            saved = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):  # no file yet, or not valid JSON
            return settings
        if not isinstance(saved, dict):
            return settings
        for setting in fields(cls):
            value = saved.get(setting.name)
            default = getattr(settings, setting.name)
            if isinstance(value, int) and isinstance(default, float) and not isinstance(value, bool):
                value = float(value)  # JSON may store 1.0 as 1
            if value is not None and type(value) is type(default):
                setattr(settings, setting.name, value)
        return settings

    def save(self, path=SETTINGS_FILE):
        """Write to a temporary file first, then swap it in, so a crash can never leave half a file."""
        path = Path(path)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        temporary.replace(path)
