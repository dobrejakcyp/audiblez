"""
ui_voice_list.py - a window that lists EVERY voice of the model, so you can compare and choose.

For each voice it shows the language, the gender, whether the voice file is already on this
computer (otherwise it is downloaded once, the first time it is used) and whether its instant
sample is ready. Double-click a row (or press Listen) to hear it; "Use this voice" picks it.
"""
import wx

from audiblez.ui_common import SPACING
from audiblez.voice_library import MODEL_NAME, all_voices



class VoiceListDialog(wx.Dialog):
    COLUMNS = [("Voice", 150), ("Language", 150), ("Gender", 70), ("On this computer", 120), ("Sample ready", 100)]

    def __init__(self, parent, main_window, current_voice):
        super().__init__(parent, title=f"All voices of {MODEL_NAME}", size=(680, 620),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.main_window = main_window
        self.voices = all_voices()

        intro = wx.StaticText(self, label="Double-click a voice to hear it. 'Use this voice' selects it for your book.")
        self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for column, (name, width) in enumerate(self.COLUMNS):
            self.table.InsertColumn(column, name)
            self.table.SetColumnWidth(column, width)
        self.fill_table()
        self.table.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda event: self.listen())  # double-click or Enter


        listen_button = wx.Button(self, label="Listen")
        use_button = wx.Button(self, label="Use this voice")
        close_button = wx.Button(self, wx.ID_CLOSE, label="Close")
        listen_button.Bind(wx.EVT_BUTTON, lambda event: self.listen())
        use_button.Bind(wx.EVT_BUTTON, lambda event: self.use_selected_voice())
        close_button.Bind(wx.EVT_BUTTON, lambda event: self.EndModal(wx.ID_CLOSE))
        self.SetEscapeId(wx.ID_CLOSE)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(listen_button, 0, wx.RIGHT, SPACING)
        buttons.Add(use_button, 0, wx.RIGHT, SPACING)
        buttons.AddStretchSpacer()
        buttons.Add(close_button)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(intro, 0, wx.ALL, SPACING * 2)
        sizer.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, SPACING * 2)
        sizer.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, SPACING * 2)
        self.SetSizer(sizer)

        if current_voice in self.voices:
            row = self.voices.index(current_voice)
            self.table.Select(row)
            self.table.EnsureVisible(row)

    def fill_table(self):
        samples = self.main_window.voice_samples
        for voice in self.voices:
            installed_note = "" if voice.language.is_installed else " (not installed)"
            self.table.Append([voice.display_name, voice.language.name + installed_note, voice.gender,
                               "yes" if voice.is_downloaded else "no (downloads once)",
                               "yes" if samples.has_sample(voice) else "no"])

    def selected_voice(self):
        row = self.table.GetFirstSelected()
        return self.voices[row] if row != -1 else None

    def listen(self):
        voice = self.selected_voice()
        if voice:
            self.main_window.play_voice_sample(voice)

    def use_selected_voice(self):
        voice = self.selected_voice()
        if voice:
            self.main_window.tools.voice_section.select_voice(voice)
            self.EndModal(wx.ID_OK)
