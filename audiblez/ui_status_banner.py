"""
ui_status_banner.py - the strip at the bottom of the window that says what the program is doing.

    | ✅ Done: Yuval Noah Harari - Nexus.m4b created                     Nexus: 13 of 20 ticked  ✕ |

It is bigger than a normal status bar, and its colour says how important the message is:

    info      plain                    "Reading the book details and cover ..."
    success   green, then fades away   "✅ Done: ... created"
    warning   flashes amber, stays     "⚠ Imported 3 books, 1 could not be read."
    error     flashes red, stays       "❌ Could not open book.epub: the file is damaged ..."

A warning or error stays coloured until the next message replaces it, or until ✕ is clicked,
so it cannot be missed while you look elsewhere.

WHICH KIND A MESSAGE IS
    Messages in this program already start with an icon, so show() reads the kind from it:
    ❌ = error, ⚠ = warning, ✅ = success, anything else = info. You can also pass kind=... yourself.

HOW THE ANIMATION WORKS
    One wx.Timer drives it. Flashing switches between a strong and a soft colour a few times;
    fading mixes the success colour step by step into the normal colour (mix_colours).
"""
import time

import wx

from audiblez.ui_common import SPACING


class MessageKind:
    INFO, SUCCESS, WARNING, ERROR = "info", "success", "warning", "error"


KIND_BY_ICON = {"❌": MessageKind.ERROR, "⚠": MessageKind.WARNING, "✅": MessageKind.SUCCESS}

# (background, text) for each kind. "strong" is the second colour of a flash.
COLOURS = {
    MessageKind.SUCCESS: (wx.Colour(200, 230, 201), wx.Colour(27, 94, 32)),
    MessageKind.WARNING: (wx.Colour(255, 224, 178), wx.Colour(140, 60, 0)),
    MessageKind.ERROR: (wx.Colour(255, 205, 210), wx.Colour(150, 20, 20)),
}
STRONG_BACKGROUND = {MessageKind.WARNING: wx.Colour(255, 167, 38), MessageKind.ERROR: wx.Colour(239, 83, 80)}


def message_kind(message):
    """The kind of a message, read from its first character (see the top of this module)."""
    return KIND_BY_ICON.get(message.lstrip()[:1], MessageKind.INFO)


def mix_colours(start, end, share_of_end):
    """The colour `share_of_end` (0.0 - 1.0) of the way from `start` to `end`."""
    def channel(a, b):
        return round(a + (b - a) * share_of_end)
    return wx.Colour(channel(start.Red(), end.Red()), channel(start.Green(), end.Green()),
                     channel(start.Blue(), end.Blue()))


class StatusBanner(wx.Panel):
    FLASHES = 3  # how many times a warning or error blinks
    FLASH_STEP_MS = 180
    SUCCESS_SHOWN_MS = 2500  # how long a success stays fully green before it fades
    FADE_MS = 1500
    FADE_STEP_MS = 40

    def __init__(self, parent):
        super().__init__(parent)
        self.normal_colours = (wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE),
                               wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT))
        self.message = wx.StaticText(self, label="", style=wx.ST_ELLIPSIZE_END)
        self.summary = wx.StaticText(self, label="")
        self.close_button = wx.Button(self, label="✕", size=(28, -1), style=wx.BORDER_NONE)
        self.close_button.SetToolTip("Hide the colour of this message")
        self.close_button.Bind(wx.EVT_BUTTON, lambda event: self.calm_down())
        self.close_button.Hide()
        bigger = self.message.GetFont().Larger()
        self.message.SetFont(bigger.Bold())
        self.summary.SetFont(bigger)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.message, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, SPACING * 2)
        sizer.Add(self.summary, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, SPACING * 2)
        sizer.Add(self.close_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, SPACING)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(sizer, 1, wx.EXPAND | wx.TOP | wx.BOTTOM, SPACING + 2)
        self.SetSizer(outer)

        self.kind = MessageKind.INFO
        self.animation = None  # None, "flash", "wait" (success fully green) or "fade"
        self.steps_done = 0
        self.fade_started = 0.0
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
        self.paint(*self.normal_colours)

    # ---- what the rest of the program calls ----------------------------------------------------

    def show(self, message, percent=None, kind=None):
        """Show a message. kind: a MessageKind; without it, it is read from the message's icon."""
        self.message.SetLabel(f"{message}  ({percent}%)" if percent is not None else message)
        self.message.SetToolTip(message)
        new_kind = kind or message_kind(message)
        if new_kind == self.kind == MessageKind.INFO:
            return  # e.g. progress updates: no need to touch the colours many times a second
        self.kind = new_kind
        self.timer.Stop()
        self.animation = None
        if new_kind in (MessageKind.WARNING, MessageKind.ERROR):
            self.close_button.Show()
            self.animation, self.steps_done = "flash", 0
            self.paint(*COLOURS[new_kind])
            self.timer.Start(self.FLASH_STEP_MS)
        elif new_kind == MessageKind.SUCCESS:
            self.close_button.Hide()
            self.animation = "wait"
            self.paint(*COLOURS[new_kind])
            self.timer.StartOnce(self.SUCCESS_SHOWN_MS)
        else:
            self.close_button.Hide()
            self.paint(*self.normal_colours)
        self.Layout()

    def show_summary(self, text):
        """The short text on the right (the open book and how many sections are ticked)."""
        self.summary.SetLabel(text)
        self.Layout()

    def calm_down(self):
        """Back to the plain colours (the ✕ button), keeping the text."""
        self.timer.Stop()
        self.animation, self.kind = None, MessageKind.INFO
        self.close_button.Hide()
        self.paint(*self.normal_colours)
        self.Layout()

    # ---- colours and animation -----------------------------------------------------------------

    def paint(self, background, text_colour):
        self.SetBackgroundColour(background)
        for label in (self.message, self.summary):
            label.SetForegroundColour(text_colour)
        self.Refresh()

    def on_timer(self, event):
        if self.animation == "flash":
            self.steps_done += 1
            if self.steps_done >= self.FLASHES * 2:  # done blinking: stay in the soft colour
                self.timer.Stop()
                self.animation = None
                self.paint(*COLOURS[self.kind])
            else:
                background = STRONG_BACKGROUND[self.kind] if self.steps_done % 2 else COLOURS[self.kind][0]
                self.paint(background, COLOURS[self.kind][1])
        elif self.animation == "wait":  # the success was shown long enough: start fading
            self.animation, self.fade_started = "fade", time.monotonic()
            self.timer.Start(self.FADE_STEP_MS)
        elif self.animation == "fade":
            share = min(1.0, (time.monotonic() - self.fade_started) * 1000 / self.FADE_MS)
            start_background, start_text = COLOURS[MessageKind.SUCCESS]
            self.paint(mix_colours(start_background, self.normal_colours[0], share),
                       mix_colours(start_text, self.normal_colours[1], share))
            if share >= 1.0:
                self.timer.Stop()
                self.animation, self.kind = None, MessageKind.INFO
