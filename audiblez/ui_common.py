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


def describe_audio_length(characters):
    hours = characters / CHARACTERS_PER_AUDIO_MINUTE / 60
    return f"{characters:,} characters (about {hours:.1f} hours of audio)"
