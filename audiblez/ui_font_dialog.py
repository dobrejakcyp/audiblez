"""
ui_font_dialog.py - the "Text font" window: choose the font and size of the book text.

    Show:  ( ) Recommended (serif)   ( ) My favourites   ( ) All fonts
    [search box]
    [list of fonts]
    Size [12]   [☆ Add to favourites]   [System default]
    preview sentence in the chosen font
                                                      [OK] [Cancel]

Every change is also shown at once in the real text column (`on_change`), so the font can be
judged on the book itself. OK keeps it; Cancel lets MainWindow put the old font back.
Favourites are kept in any case, even after Cancel: they are a list of fonts you like, not
the current choice. Saving to settings.json is done by MainWindow.
"""
import wx

from audiblez.fonts import (DEFAULT_FONT_SIZE, LARGEST_FONT_SIZE, SMALLEST_FONT_SIZE, installed_font_names,
                            recommended_fonts, search_fonts)
from audiblez.ui_common import SPACING, make_text_font

# Our own sentence plus a well-known Czech pangram: it shows at once whether a font has all the
# Czech letters (a font that lacks them shows boxes or a different-looking fallback font).
PREVIEW_TEXT = "Reading is a quiet conversation with a book. 0123456789\nPříliš žluťoučký kůň úpěl ďábelské ódy."


class FontDialog(wx.Dialog):
    RECOMMENDED, FAVOURITES, ALL = range(3)
    VIEW_NAMES = ["Recommended (serif)", "My favourites", "All fonts"]
    EMPTY_VIEW_HINTS = {
        RECOMMENDED: "None of the recommended serif fonts is installed. Have a look at All fonts.",
        FAVOURITES: "No favourites yet. Pick a font in another view and press ☆ Add to favourites.",
        ALL: "No fonts found.",
    }

    def __init__(self, parent, font_face, font_size, favourites, on_change):
        """
        font_face, font_size  the current choice ("" = the system's default font)
        favourites            list of font names; changed in place when favourites are added or removed
        on_change(face, size) called after every change, so the text column can show it live
        """
        super().__init__(parent, title="Text font", size=(480, 600), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        installed = installed_font_names()
        self.installed = set(installed)
        self.names_by_view = {self.RECOMMENDED: recommended_fonts(installed), self.ALL: installed}
        self.favourites = favourites
        self.on_change = on_change
        self.face, self.size = font_face, font_size

        self.view_choice = wx.RadioBox(self, label="Show", choices=self.VIEW_NAMES,
                                       majorDimension=3, style=wx.RA_SPECIFY_COLS)
        self.search_box = wx.SearchCtrl(self)
        self.search_box.SetDescriptiveText("Search fonts")
        self.search_box.ShowCancelButton(True)
        self.font_list = wx.ListBox(self, style=wx.LB_SINGLE)
        self.empty_hint = wx.StaticText(self, label="")

        self.size_box = wx.SpinCtrl(self, min=SMALLEST_FONT_SIZE, max=LARGEST_FONT_SIZE,
                                    initial=font_size or DEFAULT_FONT_SIZE, size=(70, -1))
        self.favourite_button = wx.Button(self, label="☆ Add to favourites")
        default_button = wx.Button(self, label="System default")
        default_button.SetToolTip("Go back to the font Windows uses by default")

        self.preview = wx.StaticText(self, label=PREVIEW_TEXT, style=wx.BORDER_SUNKEN | wx.ST_NO_AUTORESIZE)
        self.preview.SetMinSize((-1, 90))
        self.preview.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))

        self.view_choice.Bind(wx.EVT_RADIOBOX, lambda event: self.fill_list())
        self.search_box.Bind(wx.EVT_TEXT, lambda event: self.fill_list())
        self.search_box.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, lambda event: self.search_box.Clear())
        self.font_list.Bind(wx.EVT_LISTBOX, lambda event: self.choose(event.GetString(), self.size_box.GetValue()))
        self.size_box.Bind(wx.EVT_SPINCTRL, lambda event: self.choose(self.face, self.size_box.GetValue()))
        self.favourite_button.Bind(wx.EVT_BUTTON, lambda event: self.toggle_favourite())
        default_button.Bind(wx.EVT_BUTTON, lambda event: self.choose("", self.size_box.GetValue()))

        size_row = wx.BoxSizer(wx.HORIZONTAL)
        size_row.Add(wx.StaticText(self, label="Size:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, SPACING)
        size_row.Add(self.size_box, 0, wx.RIGHT, SPACING * 3)
        size_row.Add(self.favourite_button, 0, wx.RIGHT, SPACING)
        size_row.Add(default_button)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.view_choice, 0, wx.EXPAND | wx.ALL, SPACING * 2)
        sizer.Add(self.search_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, SPACING * 2)
        sizer.Add(self.font_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, SPACING * 2)
        sizer.Add(self.empty_hint, 0, wx.LEFT | wx.RIGHT | wx.TOP, SPACING * 2)
        sizer.Add(size_row, 0, wx.ALL, SPACING * 2)
        sizer.Add(self.preview, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, SPACING * 2)
        sizer.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.EXPAND | wx.ALL, SPACING * 2)
        self.SetSizer(sizer)

        # Open on the favourites if there are any (installed), otherwise on the recommended fonts
        self.view_choice.SetSelection(self.FAVOURITES if self.installed_favourites() else self.RECOMMENDED)
        self.fill_list()
        self.show_choice()

    # ---- the list --------------------------------------------------------------------------------

    def installed_favourites(self):
        return [name for name in self.favourites if name in self.installed]

    def fill_list(self):
        view = self.view_choice.GetSelection()
        names = self.installed_favourites() if view == self.FAVOURITES else self.names_by_view[view]
        shown = search_fonts(names, self.search_box.GetValue())
        self.font_list.Set(shown)
        if self.face in shown:
            self.font_list.SetStringSelection(self.face)
        if shown:
            hint = ""
        elif names:
            hint = "No font matches the search."
        else:
            hint = self.EMPTY_VIEW_HINTS[view]
        self.empty_hint.SetLabel(hint)
        self.empty_hint.Show(bool(hint))
        self.Layout()

    # ---- choosing --------------------------------------------------------------------------------

    def choose(self, face, size):
        self.face, self.size = face, size
        self.show_choice()
        self.on_change(face, size)

    def show_choice(self):
        """Make everything show the current choice: list highlight, size box, preview, favourite button."""
        if self.face in self.font_list.GetStrings():
            self.font_list.SetStringSelection(self.face)
        else:
            self.font_list.SetSelection(wx.NOT_FOUND)  # e.g. "System default" is not a font in the list
        self.size_box.SetValue(self.size)
        self.preview.SetFont(make_text_font(self.face, self.size))
        self.preview.Refresh()
        is_favourite = self.face in self.favourites
        self.favourite_button.SetLabel("★ Remove from favourites" if is_favourite else "☆ Add to favourites")
        self.favourite_button.Enable(bool(self.face))  # the system default cannot be a favourite
        self.Layout()

    def toggle_favourite(self):
        if not self.face:
            return
        if self.face in self.favourites:
            self.favourites.remove(self.face)
        else:
            self.favourites.append(self.face)
        if self.view_choice.GetSelection() == self.FAVOURITES:
            self.fill_list()
        self.show_choice()
