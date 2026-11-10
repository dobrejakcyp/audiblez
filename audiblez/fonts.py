"""
fonts.py - which fonts the reader can choose for the book text, and which ones we recommend.

    installed_font_names()   every font installed on this computer (asks the operating system)
    clean_font_names(names)  tidy a raw list: no duplicates, no "@" fonts, alphabetical
    recommended_fonts(names) the good serif reading fonts that are actually installed
    search_fonts(names, s)   the names that contain `s` (not case-sensitive)

WHY SERIF FONTS ARE RECOMMENDED
    Serif fonts (with small strokes at the ends of letters, like Georgia or Garamond) are what
    printed books use; for long reading most people find them calmer than interface fonts.
    There is no reliable way to ask Windows "is this font a serif font?", so we keep a list of
    well-known serif reading fonts and show those that are installed. The user can also keep
    their own list of favourites (stored in settings.json), which then comes first.
"""

# Well-known serif fonts that are pleasant for long reading. Only installed ones are shown.
# Windows ships the first group; the others come with Office, Linux, macOS or free font packs.
RECOMMENDED_SERIF_FONTS = [
    "Georgia", "Cambria", "Constantia", "Sitka Text", "Sitka Small", "Palatino Linotype", "Book Antiqua",
    "Times New Roman", "Garamond", "Bookman Old Style", "Century Schoolbook", "Perpetua", "Goudy Old Style",
    "Baskerville Old Face", "Charter", "Iowan Old Style", "Literata", "Merriweather", "Lora", "PT Serif",
    "Noto Serif", "Source Serif 4", "Source Serif Pro", "EB Garamond", "Crimson Text", "Crimson Pro",
    "Libre Baskerville", "Linux Libertine", "Linux Libertine O", "DejaVu Serif", "Liberation Serif",
]

DEFAULT_FONT_SIZE = 12
SMALLEST_FONT_SIZE, LARGEST_FONT_SIZE = 8, 32


def installed_font_names():
    """Every font installed on this computer. Needs a running wx.App (it asks the operating system)."""
    import wx
    return clean_font_names(wx.FontEnumerator().GetFacenames())


def clean_font_names(names):
    """
    Tidy a raw list of font names: drop duplicates and empty names, and drop names starting with "@"
    (Windows lists every Asian font a second time as "@Name", a sideways version for vertical text).
    """
    unique = {name.strip() for name in names if name and name.strip() and not name.startswith("@")}
    return sorted(unique, key=str.casefold)


def recommended_fonts(installed_names):
    """The fonts from RECOMMENDED_SERIF_FONTS that are installed, in the order of that list."""
    installed_by_lower_name = {name.casefold(): name for name in installed_names}
    return [installed_by_lower_name[name.casefold()] for name in RECOMMENDED_SERIF_FONTS
            if name.casefold() in installed_by_lower_name]


def search_fonts(names, search_text):
    """The names that contain `search_text`, ignoring upper/lower case. An empty search keeps everything."""
    wanted = search_text.strip().casefold()
    return [name for name in names if wanted in name.casefold()]
