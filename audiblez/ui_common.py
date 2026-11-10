"""ui_common.py - small helpers shared by all parts of the window."""
import wx

SPACING = 5
CHARACTERS_PER_AUDIO_MINUTE = 900  # rough speech speed, same estimate as the cleaning report


def bold(control, size_change=0):
    """Make a control's text bold (and optionally bigger). Returns the control, so it can be used inline."""
    font = control.GetFont()
    font.SetWeight(wx.FONTWEIGHT_BOLD)
    font.SetPointSize(font.GetPointSize() + size_change)
    control.SetFont(font)
    return control


def set_wrapped_text(label, text, width):
    """
    Put `text` in a wx.StaticText and wrap it to `width` pixels.
    Why not just SetLabel() + Wrap()? A label that was wrapped once remembers that width and ignores
    the next Wrap() with the same width, even after SetLabel() put in new, unwrapped text, so the new
    text would stay one long, cut-off line. Wrap(-1) makes it forget the old width first.
    """
    label.Wrap(-1)
    label.SetLabel(text)
    label.Wrap(width)
    label.InvalidateBestSize()  # so the layout asks for the new number of lines


def make_text_font(face, size):
    """The font for the book text. `face` "" means the system's default font."""
    return wx.Font(size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, False, face)


def describe_audio_length(characters):
    """ "836,717 characters (about 15.5 hours of audio)"; below one hour in minutes instead of "0.0 hours"."""
    minutes = round(characters / CHARACTERS_PER_AUDIO_MINUTE)
    if minutes < 60:
        duration = f"about {minutes} minute{'' if minutes == 1 else 's'}"
    else:
        duration = f"about {characters / CHARACTERS_PER_AUDIO_MINUTE / 60:.1f} hours"
    return f"{characters:,} characters ({duration} of audio)"
