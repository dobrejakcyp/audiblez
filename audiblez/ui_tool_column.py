"""
ui_tool_column.py - the column of tools on the far left of the window.

The column has two parts:

    scrolling part (new tools go here, in the order you use them)
        1. Book file          open an EPUB, choose where the audiobook is saved
        2. Voice              language, model, voice (with an instant sample), CPU or GPU
        3. Speed              slider and a number box, kept in sync
        4. Picture text       captions and photo credits found next to pictures: jump to them, remove them
    fixed at the bottom (always visible)
        Create audiobook      file name, start/stop button, progress bar, time remaining

To hear a piece of the book, highlight it in the text column and right-click (see ui_book_panels.py).
Every section is a ToolSection: a titled box with its controls stacked inside.
Buttons call methods of MainWindow (in ui.py); the sections never talk to each other.
"""
import os
import platform
import subprocess
import time
from pathlib import Path

import torch.cuda
import wx
from wx.lib.scrolledpanel import ScrolledPanel

from audiblez.ui_common import SPACING, bold, set_wrapped_text
from audiblez.voice_library import LANGUAGES, MODEL_NAME, Voice, all_voices, voices_of

DEFAULT_VOICE = Voice("bm_george")


class ToolSection(wx.Panel):
    """A titled box in the tool column. Subclasses put their controls in it with add() and add_row()."""

    def __init__(self, parent, title):
        super().__init__(parent)
        self.wrapped_texts = {}  # label -> its full text, so it can be wrapped again when the column width changes
        self.wrap_width = self.WRAP_WIDTH
        self.box_sizer = wx.StaticBoxSizer(wx.VERTICAL, self, title)
        self.box = self.box_sizer.GetStaticBox()  # controls must be children of the box, not of the panel
        self.SetSizer(self.box_sizer)

    # Controls may be at most this wide by their own wish. Without it, one long file name would make
    # the whole column wider than the window shows, and buttons would centre their label out of sight.
    NARROWEST_ALLOWED = 60

    def add(self, control, flags=wx.EXPAND):
        control.SetMinSize((self.NARROWEST_ALLOWED, -1))
        self.box_sizer.Add(control, 0, flags | wx.LEFT | wx.RIGHT | wx.TOP, SPACING)
        return control

    def add_row(self, *controls_and_stretch):
        """Put several controls side by side. Pass (control, stretch) pairs; stretch 1 = takes the free space."""
        row = wx.BoxSizer(wx.HORIZONTAL)
        for control, stretch in controls_and_stretch:
            if stretch:  # stretchy controls must also be allowed to become narrow (see NARROWEST_ALLOWED)
                control.SetMinSize((self.NARROWEST_ALLOWED, -1))
            row.Add(control, stretch, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, SPACING)
        self.box_sizer.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, SPACING)

    def label(self, text):
        return wx.StaticText(self.box, label=text)

    def finish(self):
        self.box_sizer.AddSpacer(SPACING)

    WRAP_WIDTH = 240  # pixels at the default column width; changes when the column is resized (see rewrap)

    def show_text(self, label, text):
        """Put a (possibly long) text in a label: wrap it to the column and make room for all of its lines."""
        self.wrapped_texts[label] = text
        set_wrapped_text(label, text, self.wrap_width)
        self.relayout()

    def rewrap(self, width):
        """The column got wider or narrower: wrap every long text again to the new width."""
        if width == self.wrap_width:
            return
        self.wrap_width = width
        for label, text in self.wrapped_texts.items():
            set_wrapped_text(label, text, width)
        self.relayout()

    def relayout(self):
        """Re-arrange after controls were shown or hidden. A scroll area must also learn its new height."""
        parent = self.GetParent()
        parent.Layout()
        if isinstance(parent, ScrolledPanel):
            parent.FitInside()


# =============================================================================================

class FileSection(ToolSection):
    def __init__(self, parent, main_window):
        super().__init__(parent, "1. Book file")
        self.open_button = self.add(wx.Button(self.box, label="📁 Open EPUB..."))
        self.open_button.Bind(wx.EVT_BUTTON, main_window.on_open)
        self.input_name = self.add(wx.StaticText(self.box, label="No book opened yet", style=wx.ST_ELLIPSIZE_MIDDLE))

        self.add(bold(self.label("Save the audiobook to:")))
        self.output_folder_text = self.add(wx.TextCtrl(self.box, value=os.path.abspath('.'), style=wx.TE_READONLY))
        change_button = wx.Button(self.box, label="📂 Change...")
        open_folder_button = wx.Button(self.box, label="Show folder")
        change_button.Bind(wx.EVT_BUTTON, self.choose_output_folder)
        open_folder_button.Bind(wx.EVT_BUTTON, lambda event: open_folder_in_file_manager(self.output_folder))
        self.add_row((change_button, 1), (open_folder_button, 1))
        self.finish()

    @property
    def output_folder(self):
        return self.output_folder_text.GetValue()

    def show_input_file(self, file_path):
        self.input_name.SetLabel(Path(file_path).name)
        self.input_name.SetToolTip(file_path)

    def choose_output_folder(self, event):
        with wx.DirDialog(self, "Choose where to save the audiobook:", defaultPath=self.output_folder) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.output_folder_text.SetValue(dialog.GetPath())


# =============================================================================================

class VoiceSection(ToolSection):
    def __init__(self, parent, main_window):
        super().__init__(parent, "2. Voice")
        self.voices_in_list = []  # the Voice objects behind the entries of voice_choice, in the same order

        self.add(bold(self.label("Language:")))
        language_names = [language.name + ("" if language.is_installed else "  (not installed)")
                          for language in LANGUAGES]
        self.language_choice = self.add(wx.Choice(self.box, choices=language_names))
        self.language_choice.Bind(wx.EVT_CHOICE, lambda event: self.fill_voice_list())

        model_name = self.label(MODEL_NAME)
        model_name.SetToolTip("The voice model installed on this computer")
        self.add_row((bold(self.label("Model:")), 0), (model_name, 1))

        self.add(bold(self.label("Voice:")))
        self.voice_choice = wx.Choice(self.box)
        self.hear_button = wx.Button(self.box, label="Listen")
        self.hear_button.SetToolTip("Play a short sample of this voice")
        self.hear_button.Bind(wx.EVT_BUTTON, lambda event: main_window.play_voice_sample(self.voice))
        self.add_row((self.voice_choice, 1), (self.hear_button, 0))
        all_voices_button = self.add(wx.Button(self.box, label="📋 All voices..."))
        all_voices_button.SetToolTip("Compare every voice of every language, and see which are on this computer")
        all_voices_button.Bind(wx.EVT_BUTTON, main_window.on_show_all_voices)

        self.cpu_radio = wx.RadioButton(self.box, label="CPU", style=wx.RB_GROUP)
        self.cuda_radio = wx.RadioButton(self.box, label="GPU (CUDA)")
        if torch.cuda.is_available():
            self.cuda_radio.SetValue(True)
        else:
            self.cpu_radio.SetValue(True)
            self.cuda_radio.Disable()
        self.add_row((bold(self.label("Runs on:")), 0), (self.cpu_radio, 0), (self.cuda_radio, 0))
        self.finish()

        self.language_choice.SetSelection(LANGUAGES.index(DEFAULT_VOICE.language))
        self.fill_voice_list(select=DEFAULT_VOICE)

    def fill_voice_list(self, select=None):
        language = LANGUAGES[self.language_choice.GetSelection()]
        self.voices_in_list = voices_of(language.code)
        self.voice_choice.Set([voice.display_name for voice in self.voices_in_list])
        self.voice_choice.SetSelection(self.voices_in_list.index(select) if select in self.voices_in_list else 0)

    def select_voice(self, voice):
        """Switch the language list to the voice's language and select the voice."""
        self.language_choice.SetSelection(LANGUAGES.index(voice.language))
        self.fill_voice_list(select=voice)

    @property
    def voice(self):
        return self.voices_in_list[self.voice_choice.GetSelection()]

    @property
    def device(self):
        return "cuda" if self.cuda_radio.GetValue() else "cpu"

    def select_device(self, device):
        if device == "cuda" and self.cuda_radio.IsEnabled():
            self.cuda_radio.SetValue(True)
        else:
            self.cpu_radio.SetValue(True)


# =============================================================================================

class SpeedSection(ToolSection):
    """A slider for quick changes and a number box for exact values. Changing one updates the other."""

    SLOWEST, NORMAL, FASTEST = 0.5, 1.0, 2.0

    def __init__(self, parent):
        super().__init__(parent, "3. Speed")
        # A slider only knows whole numbers, so it works in hundredths: 100 = speed 1.0
        self.slider = wx.Slider(self.box, value=100, minValue=int(self.SLOWEST * 100), maxValue=int(self.FASTEST * 100))
        self.slider.SetToolTip("Double-click to reset to normal speed (1.0)")
        self.number_box = wx.SpinCtrlDouble(self.box, min=self.SLOWEST, max=self.FASTEST, initial=1.0, inc=0.05,
                                            size=(75, -1))
        self.number_box.SetDigits(2)
        self.slider.Bind(wx.EVT_SLIDER, self.on_slider_moved)
        # The Windows slider never reports a real double-click (its window class does not ask for them),
        # so we detect it ourselves: two presses within the system's double-click time = reset.
        self.last_press_time = 0.0
        self.slider.Bind(wx.EVT_LEFT_DOWN, self.on_slider_pressed)
        self.number_box.Bind(wx.EVT_SPINCTRLDOUBLE, self.on_number_typed)
        self.add_row((self.slider, 1), (self.number_box, 0))
        self.add(wx.StaticText(self.box, label="0.5 = slow,  1.0 = normal,  2.0 = fast"))
        self.finish()

    def on_slider_pressed(self, event):
        now = time.monotonic()
        if now - self.last_press_time <= double_click_seconds():
            self.last_press_time = 0.0  # a third quick click starts counting again
            wx.CallAfter(self.set_speed, self.NORMAL)  # after the slider has finished handling this click
        else:
            self.last_press_time = now
        event.Skip()  # the slider still gets the click, so dragging keeps working

    def on_slider_moved(self, event):
        self.number_box.SetValue(self.slider.GetValue() / 100)

    def on_number_typed(self, event):
        self.slider.SetValue(round(self.number_box.GetValue() * 100))

    def set_speed(self, speed):
        speed = min(self.FASTEST, max(self.SLOWEST, speed))
        self.number_box.SetValue(speed)
        self.slider.SetValue(round(speed * 100))

    @property
    def speed(self):
        return round(self.number_box.GetValue(), 2)


# =============================================================================================

class CreateSection(ToolSection):
    def __init__(self, parent, main_window):
        super().__init__(parent, "Create audiobook")
        self.summary = self.add(wx.StaticText(self.box, label="Open a book first."))
        self.file_name = self.add(wx.StaticText(self.box, label="", style=wx.ST_ELLIPSIZE_MIDDLE))
        self.start_button = self.add(wx.Button(self.box, label="🚀 Create audiobook"))
        self.start_button.Bind(wx.EVT_BUTTON, main_window.on_start)
        self.stop_button = self.add(wx.Button(self.box, label="⏹ Stop"))
        self.stop_button.SetToolTip("Stop after the current sentence. Finished chapters are kept, "
                                    "so starting again continues where it stopped.")
        self.stop_button.Bind(wx.EVT_BUTTON, main_window.on_stop)
        self.gauge = self.add(wx.Gauge(self.box, range=100, style=wx.GA_PROGRESS))
        self.time_left = self.add(wx.StaticText(self.box, label=""))
        self.gauge.Hide()
        self.stop_button.Hide()
        self.finish()

    def show_summary(self, text, file_name):
        self.file_name.SetLabel(f"Saves as: {file_name}")
        self.file_name.SetToolTip(file_name)
        self.show_text(self.summary, text)

    def show_started(self):
        self.gauge.SetValue(0)
        self.gauge.Show()
        self.start_button.Hide()
        self.stop_button.SetLabel("⏹ Stop")
        self.stop_button.Enable()
        self.stop_button.Show()
        self.time_left.SetLabel("Starting...")
        self.relayout()

    def show_stopping(self):
        self.stop_button.SetLabel("⏳ Stopping after this sentence...")
        self.stop_button.Disable()

    def show_busy(self):
        self.gauge.Pulse()  # animated bar: working, but no percentage known

    def show_progress(self, percent, time_left_text):
        self.gauge.SetValue(percent)
        self.time_left.SetLabel(time_left_text)

    FINISHED_MESSAGES = {"done": "Finished.", "stopped": "Stopped. Start again to continue.",
                         "failed": "Stopped because of an error."}

    def show_finished(self, outcome):
        """outcome is "done", "stopped" or "failed"."""
        if outcome != "done":
            self.gauge.SetValue(0)
        self.time_left.SetLabel(self.FINISHED_MESSAGES[outcome])
        self.stop_button.Hide()
        self.start_button.Show()
        self.relayout()


# =============================================================================================

class PictureTextSection(ToolSection):
    """
    Shows the kinds of text that picture_text_detector.py found next to pictures (captions,
    photo credits).
      - Previous / Next jump to every place where the selected kind occurs, chapter by chapter.
      - Tick the kinds you do not want to hear and press the button: they are removed from the
        whole book. Untick a kind and press the button again to bring it back.
    """

    def __init__(self, parent, main_window):
        super().__init__(parent, "4. Picture text")
        self.main_window = main_window
        self.groups = []
        self.removed_classes = []
        self.lines = []  # (section, line number) of every occurrence of the selected kind
        self.position = -1  # index in self.lines of the occurrence shown last; -1 = none yet
        self.message = self.add(wx.StaticText(self.box, label="Open a book to look for picture captions and credits."))
        self.group_list = self.add(wx.CheckListBox(self.box, size=(-1, 75)))
        self.group_list.Bind(wx.EVT_LISTBOX, lambda event: self.select_kind(event.GetSelection()))
        self.sample = self.add(wx.StaticText(self.box, label=""))
        self.previous_button = wx.Button(self.box, label="◀ Previous")
        self.position_label = wx.StaticText(self.box, label="", style=wx.ALIGN_CENTRE_HORIZONTAL)
        self.next_button = wx.Button(self.box, label="Next ▶")
        self.previous_button.Bind(wx.EVT_BUTTON, lambda event: self.step(-1))
        self.next_button.Bind(wx.EVT_BUTTON, lambda event: self.step(+1))
        self.previous_button.SetToolTip("Show the previous place where this kind of text occurs")
        self.next_button.SetToolTip("Show the next place where this kind of text occurs")
        self.add_row((self.previous_button, 0), (self.position_label, 1), (self.next_button, 0))
        self.apply_button = self.add(wx.Button(self.box, label="✂ Remove the ticked kinds"))
        self.apply_button.SetToolTip("Ticked kinds are removed from the whole book. "
                                     "Untick a kind and press again to bring it back.")
        self.apply_button.Bind(wx.EVT_BUTTON, main_window.on_apply_picture_text)
        self.show_text(self.message, self.message.GetLabel())
        self.show_controls(False)
        self.finish()

    def show_controls(self, visible):
        for control in (self.group_list, self.sample, self.previous_button, self.position_label,
                        self.next_button, self.apply_button):
            control.Show(visible)
        self.relayout()

    def show_groups(self, groups, removed_classes):
        self.groups = groups
        self.removed_classes = list(removed_classes)
        if not groups:
            self.show_text(self.message, "No text next to pictures was found in this book.")
            self.show_controls(False)
            return
        self.show_text(self.message, f"Found {len(groups)} kind(s) of text next to pictures. Not yet removed "
                                     "parts are yellow in the text column. Tick what you do not want to hear:")
        self.group_list.Set([group.label for group in groups])
        for row, group in enumerate(groups):
            self.group_list.Check(row, group.css_class in removed_classes)
        self.group_list.SetSelection(0)
        self.select_kind(0)
        self.show_controls(True)

    def select_kind(self, row):
        """A kind was picked in the list: show an example and get ready to jump through its occurrences."""
        self.show_sample(row)
        self.lines = self.main_window.find_picture_text_lines(self.groups[row].css_class)
        self.position = -1
        self.update_position_label()

    def step(self, direction):
        """Jump to the next (+1) or previous (-1) occurrence; after the last one it starts again."""
        if not self.lines:
            return
        self.position = (self.position + direction) % len(self.lines)
        section, line_number = self.lines[self.position]
        self.main_window.show_picture_text_line(section, line_number)
        self.update_position_label()

    def update_position_label(self):
        row = self.group_list.GetSelection()
        removed = 0 <= row < len(self.groups) and self.groups[row].css_class in self.removed_classes
        if not self.lines:
            text = "removed from the book" if removed else "none in the text"
        elif self.position < 0:
            text = f"{len(self.lines)} in the text"
        else:
            text = f"{self.position + 1} of {len(self.lines)}"
        self.position_label.SetLabel(text)
        self.previous_button.Enable(bool(self.lines))
        self.next_button.Enable(bool(self.lines))
        self.relayout()

    def show_sample(self, row):
        if 0 <= row < len(self.groups):
            group = self.groups[row]
            sample = group.samples[0] if group.samples else ""
            self.show_text(self.sample, f'e.g. "{sample}"\n{group.near_picture_count} of {group.total_count} '
                                        f'are next to a picture, {group.characters:,} characters in total.')

    def ticked_classes(self):
        return [group.css_class for row, group in enumerate(self.groups) if self.group_list.IsChecked(row)]


class ToolColumn(wx.Panel):
    """
    The column on the left, in two parts:
      - scroll_area: the tool sections, stacked; it scrolls when the window is too short.
        New tools are added here.
      - create_section: "Create audiobook", fixed at the bottom so it is always visible.
    Its width can be changed by dragging the divider next to it (see MainWindow.create_layout);
    long texts are then wrapped again to the new width.
    """

    WIDTH = 290  # default width in pixels
    NARROWEST = 240
    SPACE_AROUND_TEXT = 50  # section borders, margins and the scroll bar: text width = column width - this

    def __init__(self, parent, main_window):
        super().__init__(parent, size=(self.WIDTH, -1))
        self.Bind(wx.EVT_SIZE, self.on_resized)

        self.scroll_area = ScrolledPanel(self)
        self.file_section = FileSection(self.scroll_area, main_window)
        self.voice_section = VoiceSection(self.scroll_area, main_window)
        self.speed_section = SpeedSection(self.scroll_area)
        self.picture_text_section = PictureTextSection(self.scroll_area, main_window)
        self.tool_sections = (self.file_section, self.voice_section, self.speed_section, self.picture_text_section)
        scroll_sizer = wx.BoxSizer(wx.VERTICAL)
        for section in self.tool_sections:
            scroll_sizer.Add(section, 0, wx.EXPAND | wx.ALL, SPACING)
        self.scroll_area.SetSizer(scroll_sizer)
        self.scroll_area.SetupScrolling(scroll_x=False)

        self.create_section = CreateSection(self, main_window)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.scroll_area, 1, wx.EXPAND)
        sizer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, SPACING)
        sizer.Add(self.create_section, 0, wx.EXPAND | wx.ALL, SPACING)
        self.SetSizer(sizer)
        self.set_book_actions_enabled(False)

    def on_resized(self, event):
        event.Skip()  # let wx do the normal layout as well
        text_width = max(120, self.GetClientSize().width - self.SPACE_AROUND_TEXT)
        for section in (*self.tool_sections, self.create_section):
            section.rewrap(text_width)

    def set_book_actions_enabled(self, enabled):
        """Creating an audiobook only makes sense once a book is open."""
        self.create_section.start_button.Enable(enabled)

    def set_locked_for_generation(self, locked):
        """While an audiobook is being made, settings must not change and no other book may be opened."""
        for section in self.tool_sections:
            section.Enable(not locked)
        self.create_section.start_button.Enable(not locked)

    # ---- remembering the settings (see settings.py) ------------------------------------------

    def apply_settings(self, settings):
        """Put saved settings into the controls. Values that are no longer valid are skipped."""
        voice = Voice(settings.voice_id)
        if voice in all_voices():
            self.voice_section.select_voice(voice)
        self.voice_section.select_device(settings.device)
        self.speed_section.set_speed(settings.speed)
        if settings.output_folder and os.path.isdir(settings.output_folder):
            self.file_section.output_folder_text.SetValue(settings.output_folder)

    def store_settings(self, settings):
        """Copy the current state of the controls into `settings` (saving is done by the caller)."""
        settings.voice_id = self.voice_section.voice.id
        settings.device = self.voice_section.device
        settings.speed = self.speed_section.speed
        settings.output_folder = self.file_section.output_folder


def double_click_seconds():
    """The double-click speed set in Windows (Mouse settings), in seconds. 0.5 s elsewhere."""
    if platform.system() == "Windows":
        import ctypes
        return ctypes.windll.user32.GetDoubleClickTime() / 1000
    return 0.5


def open_folder_in_file_manager(folder_path):
    import platform
    try:
        if platform.system() == 'Windows':
            subprocess.Popen(['explorer', folder_path])
        elif platform.system() == 'Linux':
            subprocess.Popen(['xdg-open', folder_path])
        elif platform.system() == 'Darwin':
            subprocess.Popen(['open', folder_path])
    except Exception as e:
        print(e)
