#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui.py - the main window of audiblez (built with wxPython). Start it with:

    uv run audiblez-ui          (or: .venv\\Scripts\\python -m audiblez.ui)

WINDOW LAYOUT
    +--------------+--------------------------------------------------+
    | ToolColumn   | BookCard  (cover, details, links)                |
    | 1 Book file  +------------------------+-------------------------+
    | 2 Voice      | ChapterListPanel       | TextPreviewPanel        |
    | 3 Speed      | (ticked = read aloud)  | (editable text;         |
    | 4 Picture    |                        |  right-click to hear it)|
    |   text       |                        |                         |
    | ............ |                        |                         |
    | Create       |          <- drag the divider ->                  |
    | (always seen)|                        |                         |
    +--------------+------------------------+-------------------------+
    | StatusBanner: what the program is doing right now  |  summary   |
    +-----------------------------------------------------------------+

    The panels live in ui_tool_column.py and ui_book_panels.py. This file connects them.

HOW THE PARTS TALK TO EACH OTHER
    A panel never reaches into another panel. It calls a method of MainWindow ("the user picked
    a section", "the user clicked Create"), and MainWindow tells the other panels what to show.

SLOW WORK RUNS IN THE BACKGROUND
    Opening a book (BookLoader), reading text aloud and making the audiobook (CoreThread) run in background
    threads, so the window stays responsive and the status banner can show what is happening.
    Background threads must never touch the window directly: they hand results back with
    wx.CallAfter(...) or with the EVENTS below.
"""
import threading
import traceback
from tempfile import gettempdir
from pathlib import Path

import torch.cuda
import wx
import wx.adv
from wx.lib.newevent import NewEvent

from audiblez.picture_text_detector import find_lines_of_kind
from audiblez.settings import UserSettings
from audiblez.ui_book_panels import BookCard, ChapterListPanel, TextPreviewPanel
from audiblez.ui_common import SPACING, describe_audio_length
from audiblez.ui_font_dialog import FontDialog
from audiblez.ui_tool_column import ToolColumn, open_folder_in_file_manager
from audiblez.ui_voice_list import VoiceListDialog
from audiblez.voice_library import VoiceSampleLibrary

ORIGINAL_AUTHOR = "Claudio Santini (2025) and many contributors - https://claudio.uk"
CURRENT_MAINTAINER = "Lukas"
LONGEST_READ_ALOUD = 3000  # characters; reading a whole chapter aloud would take minutes to prepare

# Events sent by core.main() (running in CoreThread) to the window
EVENTS = {
    'CORE_STARTED': NewEvent(),
    'CORE_STATUS': NewEvent(),
    'CORE_PROGRESS': NewEvent(),
    'CORE_CHAPTER_STARTED': NewEvent(),
    'CORE_CHAPTER_FINISHED': NewEvent(),
    'CORE_FINISHED': NewEvent()
}


# =============================================================================================
# Status banner
# =============================================================================================

class StatusBanner:
    """The bar at the bottom: what the program is doing right now (left), and a short summary (right)."""

    def __init__(self, frame):
        self.bar = frame.CreateStatusBar(2)
        self.bar.SetStatusWidths([-3, -2])  # the left part gets 3/5 of the width

    def show(self, message, percent=None):
        self.bar.SetStatusText(f"{message}  ({percent}%)" if percent is not None else message, 0)

    def show_summary(self, text):
        self.bar.SetStatusText(text, 1)


# =============================================================================================
# Background work
# =============================================================================================

class BookLoader(threading.Thread):
    """
    Reads and cleans an EPUB in the background and reports each step to the status banner.
    `removed_classes` are CSS classes to leave out (picture text chosen in tool 6).
    """

    def __init__(self, file_path, window, removed_classes=()):
        super().__init__(daemon=True)
        self.file_path = file_path
        self.window = window
        self.removed_classes = list(removed_classes)

    def report(self, message, percent=None):
        wx.CallAfter(self.window.status.show, message, percent)

    def run(self):
        from ebooklib import epub
        from audiblez.book_metadata import BookMetadata
        from audiblez.chapter_selection import SectionClassifier
        from audiblez.epub_text_extractor import EpubTextExtractor
        from audiblez.picture_text_detector import PictureTextDetector
        try:
            self.report(f"Reading {Path(self.file_path).name} ...")
            book = epub.read_epub(self.file_path)
            self.report("Reading the book details and cover ...")
            metadata = BookMetadata.from_epub(book)
            extractor = EpubTextExtractor.with_default_rules(extra_class_names=self.removed_classes)
            chapters = extractor.extract_chapters(
                book, on_progress=lambda done, total: self.report(
                    f"Cleaning the text: file {done} of {total}", done * 100 // total))
            self.report("Deciding which sections to read aloud ...")
            sections = SectionClassifier().describe(chapters)
            self.report("Looking for picture captions and credits ...")
            picture_text_groups = PictureTextDetector().find_groups(chapters)
            wx.CallAfter(self.window.show_loaded_book, self.file_path, metadata, sections,
                         picture_text_groups, self.removed_classes)
        except Exception as error:
            traceback.print_exc()
            wx.CallAfter(self.window.show_loading_failed, self.file_path, error)


class CoreThread(threading.Thread):
    """
    Runs core.main() in the background and forwards its progress to the window as events.
    Call request_stop() to stop it politely: core.main() checks before every sentence.
    """

    def __init__(self, params):
        super().__init__(daemon=True)
        self.params = params
        self.stop_requested = threading.Event()

    def request_stop(self):
        self.stop_requested.set()

    def run(self):
        import audiblez.core as core
        try:
            core.main(**self.params, post_event=self.post_event, stop_requested=self.stop_requested)
        except Exception as e:  # otherwise the window would wait forever with no explanation
            traceback.print_exc()
            self.post_event('CORE_STATUS', message=f'❌ Failed: {e} (details in the console window)', busy=False)
            self.post_event('CORE_FINISHED', failed=True)

    def post_event(self, event_name, **kwargs):
        EventObject, _event_code = EVENTS[event_name]
        event_object = EventObject()
        for name, value in kwargs.items():
            setattr(event_object, name, value)
        wx.PostEvent(wx.GetApp().GetTopWindow(), event_object)


# =============================================================================================
# The main window
# =============================================================================================

class MainWindow(wx.Frame):
    def __init__(self, parent, title):
        # size from the usable height (screen minus taskbar): width-based sizing overflowed ultrawide screens
        area = wx.Display().GetClientArea()
        window_height = int(area.height * 0.85)
        window_width = min(window_height * 3 // 2, int(area.width * 0.9))
        super().__init__(parent, title=title, size=(window_width, window_height))

        self.settings = UserSettings.load()
        self.core_thread = None
        self.book_sections = []
        self.picture_text_groups = []
        self.highlighted_classes = []  # picture text that is found but not removed: shown in yellow
        self.selected_section = None
        self.epub_path = None
        self.book_title = ""
        self.book_metadata = None
        self.synthesis_in_progress = False
        self.reading_aloud = False  # True while a piece of text is being prepared for reading aloud
        self.reading_cancelled = False  # set by "Stop reading" while it is being prepared
        self.voice_samples = VoiceSampleLibrary()
        self.playing_sound = None  # keep a reference, otherwise the sound is destroyed while playing

        for name, handler in [('CORE_STARTED', self.on_core_started), ('CORE_STATUS', self.on_core_status),
                              ('CORE_CHAPTER_STARTED', self.on_core_chapter_started),
                              ('CORE_CHAPTER_FINISHED', self.on_core_chapter_finished),
                              ('CORE_PROGRESS', self.on_core_progress), ('CORE_FINISHED', self.on_core_finished)]:
            self.Bind(EVENTS[name][1], handler)

        self.create_menu()
        self.create_layout()
        self.status = StatusBanner(self)
        self.status.show("Ready. Open an EPUB file to begin (1. Book file, on the left).")
        self.tools.create_section.show_summary("Open a book first.", "-")
        self.restore_settings()
        self.Bind(wx.EVT_CLOSE, self.on_close)
        wx.CallAfter(self.put_divider_in_the_middle)  # only possible once the window has its real size

    # ---- remembering settings between sessions (see settings.py) -----------------------------

    def restore_settings(self):
        self.tools.apply_settings(self.settings)
        self.chapter_list.show_short_files_checkbox.SetValue(self.settings.show_short_files)
        size, position = self.settings.window_size, self.settings.window_position
        if len(size) == 2:
            self.SetSize(size)
        if len(position) == 2 and wx.Display.GetFromPoint(wx.Point(*position)) != wx.NOT_FOUND:
            self.SetPosition(position)  # only if that spot is still on a connected screen
        else:
            self.Centre()
        if self.settings.window_maximized:
            self.Maximize()
        if self.settings.tool_column_width >= ToolColumn.NARROWEST:
            wx.CallAfter(self.outer_splitter.SetSashPosition, self.settings.tool_column_width)
        self.text_preview.set_text_font(self.settings.text_font_face, self.settings.text_font_size)

    def on_choose_text_font(self, event):
        """View → Text font (or the "Aa Font..." button): choose the font of the book text."""
        with FontDialog(self, self.settings.text_font_face, self.settings.text_font_size,
                        self.settings.favourite_fonts, on_change=self.text_preview.set_text_font) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.settings.text_font_face, self.settings.text_font_size = dialog.face, dialog.size
                self.status.show(f"Text font: {dialog.face or 'system default'}, {dialog.size} pt")
            else:  # Cancel: the dialog showed its choices live, so put the saved font back
                self.text_preview.set_text_font(self.settings.text_font_face, self.settings.text_font_size)

    def save_settings(self):
        self.tools.store_settings(self.settings)
        self.settings.show_short_files = self.chapter_list.show_short_files_checkbox.GetValue()
        self.settings.window_maximized = self.IsMaximized()
        self.settings.tool_column_width = self.outer_splitter.GetSashPosition()
        if not self.IsMaximized() and not self.IsIconized():  # remember the normal size, not the maximized one
            self.settings.window_size = list(self.GetSize())
            self.settings.window_position = list(self.GetPosition())
        try:
            self.settings.save()
        except OSError as error:
            print("Could not save the settings:", error)

    def on_close(self, event):
        if self.synthesis_in_progress:
            answer = wx.MessageBox("An audiobook is still being made. Stop it and close the program?\n"
                                   "Finished chapters are kept, so you can continue later.",
                                   "Close Audiblez", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, parent=self)
            if answer != wx.YES:
                event.Veto()
                return
            self.core_thread.request_stop()
        self.save_settings()
        event.Skip()  # let the window close normally

    def create_menu(self):
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        open_item = file_menu.Append(wx.ID_OPEN, "&Open EPUB...\tCtrl+O")
        exit_item = file_menu.Append(wx.ID_EXIT, "E&xit\tCtrl+Q")
        view_menu = wx.Menu()
        font_item = view_menu.Append(wx.ID_ANY, "Text &font...\tCtrl+Shift+F")
        help_menu = wx.Menu()
        about_item = help_menu.Append(wx.ID_ABOUT, "&About")
        self.Bind(wx.EVT_MENU, self.on_choose_text_font, font_item)
        self.Bind(wx.EVT_MENU, self.on_open, open_item)
        self.Bind(wx.EVT_MENU, lambda event: self.Close(), exit_item)
        self.Bind(wx.EVT_MENU, self.on_about, about_item)
        menubar.Append(file_menu, "&File")
        menubar.Append(view_menu, "&View")
        menubar.Append(help_menu, "&Help")
        self.SetMenuBar(menubar)

    def create_layout(self):
        root = wx.Panel(self)
        # Tool column | everything else, with a divider you can drag to make the tool column wider
        self.outer_splitter = wx.SplitterWindow(root, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        self.tools = ToolColumn(self.outer_splitter, self)

        right_side = wx.Panel(self.outer_splitter)
        self.book_card = BookCard(right_side)
        self.splitter = wx.SplitterWindow(right_side, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        self.chapter_list = ChapterListPanel(self.splitter, self)
        self.text_preview = TextPreviewPanel(self.splitter, self)
        self.splitter.SplitVertically(self.chapter_list, self.text_preview)
        self.splitter.SetSashGravity(0.5)  # when the window grows, both columns grow equally
        self.splitter.SetMinimumPaneSize(250)

        right_sizer = wx.BoxSizer(wx.VERTICAL)
        right_sizer.Add(self.book_card, 0, wx.EXPAND | wx.ALL, SPACING)
        right_sizer.Add(self.splitter, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, SPACING)
        right_side.SetSizer(right_sizer)

        self.outer_splitter.SplitVertically(self.tools, right_side, ToolColumn.WIDTH)
        self.outer_splitter.SetSashGravity(0)  # when the window grows, only the right side grows
        self.outer_splitter.SetMinimumPaneSize(ToolColumn.NARROWEST)

        root_sizer = wx.BoxSizer(wx.HORIZONTAL)
        root_sizer.Add(self.outer_splitter, 1, wx.EXPAND)
        root.SetSizer(root_sizer)
        self.root = root

        # The list and the text start at the same line: give both column headers the same height
        header_height = max(self.chapter_list.header_height(), self.text_preview.header_height())
        self.chapter_list.set_header_height(header_height)
        self.text_preview.set_header_height(header_height)

    def put_divider_in_the_middle(self):
        self.splitter.SetSashPosition(self.splitter.GetClientSize().width // 2)

    def on_about(self, event):
        from audiblez import __version__
        message = (f"Audiblez {__version__} - generate audiobooks from EPUB files with the Kokoro-82M voice model.\n\n"
                   f"Original author and maintainer:\n    {ORIGINAL_AUTHOR}\n\n"
                   f"This fork (github.com/dobrejakcyp/audiblez) is maintained by:\n    {CURRENT_MAINTAINER}\n\n"
                   "Distributed under the MIT License.")
        wx.MessageBox(message, "About Audiblez", parent=self)

    # ---- 1. opening a book -------------------------------------------------------------------

    def on_open(self, event):
        if self.synthesis_in_progress:
            wx.MessageBox("An audiobook is still being made. Please wait for it to finish.",
                          "Audiobook in progress", parent=self)
            return
        with wx.FileDialog(self, "Open EPUB file", defaultDir=self.settings.last_book_folder,
                           wildcard="EPUB books (*.epub)|*.epub", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.settings.last_book_folder = str(Path(dialog.GetPath()).parent)
                self.open_epub(dialog.GetPath())

    def open_epub(self, file_path, removed_classes=None):
        """
        Start loading in the background; show_loaded_book() is called when it is done.
        Without `removed_classes`, the picture text removed last time for this book is used.
        """
        if removed_classes is None:
            removed_classes = self.settings.picture_text_removed.get(Path(file_path).name, [])
        self.tools.file_section.open_button.Disable()
        self.tools.set_book_actions_enabled(False)
        BookLoader(file_path, self, removed_classes).start()

    def show_loaded_book(self, file_path, metadata, sections, picture_text_groups, removed_classes):
        reloading_same_book = file_path == self.epub_path
        if reloading_same_book:  # keep the user's own ticks and the selected section
            self.copy_choices_from_previous_load(sections)
        self.epub_path = file_path
        self.book_metadata = metadata
        self.book_title = metadata.title or Path(file_path).stem
        self.book_sections = sections
        self.picture_text_groups = picture_text_groups
        self.highlighted_classes = [group.css_class for group in picture_text_groups
                                    if group.css_class not in removed_classes]
        for section in sections:
            section.chapter.is_selected = section.is_included  # the flag core.main() looks at

        self.book_card.show_book(metadata)
        self.tools.file_section.show_input_file(file_path)
        self.tools.picture_text_section.show_groups(picture_text_groups, removed_classes)
        self.chapter_list.show_sections(sections)
        self.chapter_list.select_section(self.section_to_show_first(sections, reloading_same_book))
        self.on_sections_changed()
        self.tools.file_section.open_button.Enable()
        self.tools.set_book_actions_enabled(True)
        self.root.Layout()
        if reloading_same_book:
            removed = ", ".join(removed_classes) or "nothing"
            self.status.show(f"Picture text updated. Removed from the book: {removed}.")
        else:
            self.status.show(f"Ready: \"{self.book_title}\" is open. Check the ticked sections, then create the audiobook.")

    def copy_choices_from_previous_load(self, new_sections):
        ticks_by_file = {section.file_name: section.is_included for section in self.book_sections}
        for section in new_sections:
            section.is_included = ticks_by_file.get(section.file_name, section.is_included)

    def section_to_show_first(self, sections, reloading_same_book):
        if reloading_same_book and self.selected_section is not None:
            for section in sections:
                if section.file_name == self.selected_section.file_name:
                    return section
        included = [section for section in sections if section.is_included]
        return (included or sections)[0]

    # ---- 4. picture text ---------------------------------------------------------------------

    def find_picture_text_lines(self, css_class):
        """Every (section, line number) in the book that came from this kind of picture text."""
        return find_lines_of_kind(self.book_sections, css_class)

    def show_picture_text_line(self, section, line_number):
        """Open the section in the text column and scroll to the line (Previous/Next of tool 4)."""
        self.chapter_list.select_section(section)
        if self.text_preview.section is not section:  # the row was already selected, so no event came
            self.on_section_selected(section)
        wx.CallAfter(self.text_preview.reveal_line, line_number)  # after the text has been put in place
        self.status.show(f"Picture text in \"{section.display_title}\", line {line_number + 1}")

    def on_apply_picture_text(self, event):
        """Reload the book, leaving out the ticked kinds of picture text, and remember the choice."""
        removed_classes = self.tools.picture_text_section.ticked_classes()
        book_name = Path(self.epub_path).name
        if removed_classes:
            self.settings.picture_text_removed[book_name] = removed_classes
        else:
            self.settings.picture_text_removed.pop(book_name, None)
        self.status.show("Applying the picture text choices ...")
        self.open_epub(self.epub_path, removed_classes)

    def show_loading_failed(self, file_path, error):
        self.tools.file_section.open_button.Enable()
        self.tools.set_book_actions_enabled(bool(self.book_sections))
        self.status.show(f"❌ Could not open {Path(file_path).name}: {error}")

    # ---- called by the book panels -----------------------------------------------------------

    def on_section_selected(self, section):
        self.selected_section = section
        self.text_preview.show_section(section, self.highlighted_classes)

    def on_sections_changed(self):
        """A tick changed (or a text was edited): update every place that shows totals."""
        included = [section for section in self.book_sections if section.is_included]
        characters = sum(section.text_length for section in included)
        self.book_card.show_read_aloud_length(characters, len(included), len(self.book_sections))
        file_name = self.book_metadata.audiobook_file_name(fallback=Path(self.epub_path).stem) + ".m4b"
        self.tools.create_section.show_summary(f"{len(included)} sections, {describe_audio_length(characters)}",
                                               file_name)
        self.status.show_summary(f"{self.book_title[:40]}: {len(included)} of {len(self.book_sections)} sections ticked")

    def on_section_text_edited(self, section):
        self.chapter_list.refresh_length(section)
        self.on_sections_changed()

    # ---- 2. hearing a voice sample -----------------------------------------------------------

    def on_show_all_voices(self, event):
        with VoiceListDialog(self, self, current_voice=self.tools.voice_section.voice) as dialog:
            dialog.ShowModal()

    def play_voice_sample(self, voice):
        if not voice.language.is_installed:
            self.status.show(f"❌ {voice.language.name} is not installed on this computer "
                             f"(missing Python package '{voice.language.required_module}').")
            return
        if self.voice_samples.has_sample(voice):
            self.play_wav(self.voice_samples.sample_path(voice), f"Playing a sample of {voice.display_name}")
            return
        # No sample yet (e.g. deleted): make it once in the background, then play it
        self.status.show(f"Making a sample of {voice.display_name} (only the first time) ...")
        self.run_in_background(lambda: self.voice_samples.create_sample(voice),
                               on_done=lambda path: self.play_wav(path, f"Playing a sample of {voice.display_name}"))

    # ---- reading highlighted text aloud (right-click in the text column) -----------------------

    def read_aloud(self, text):
        """Read `text` with the chosen voice and speed. Called from the text column's right-click menu."""
        text = text.strip()
        if not text:
            return
        if self.reading_aloud:
            self.status.show("Still preparing the previous piece of text, please wait a moment.")
            return
        shortened = len(text) > LONGEST_READ_ALOUD
        text = text[:LONGEST_READ_ALOUD]
        voice, speed = self.tools.voice_section.voice, self.tools.speed_section.speed
        torch.set_default_device(self.tools.voice_section.device)
        self.reading_aloud, self.reading_cancelled = True, False
        self.status.show(f"Preparing {len(text):,} characters with {voice.display_name} at speed {speed}"
                         + (f" (only the first {LONGEST_READ_ALOUD:,})" if shortened else "")
                         + "; the first time for a language takes a few seconds ...")
        sound_file = Path(gettempdir()) / "audiblez_read_aloud.wav"

        def when_done(path):
            self.reading_aloud = False
            if not self.reading_cancelled:
                self.play_wav(path, f"Reading {len(text):,} characters aloud. Right-click → Stop reading to stop.")

        def when_failed(error):
            self.reading_aloud = False
            self.status.show(f"❌ Reading aloud failed: {error}")

        self.run_in_background(lambda: self.voice_samples.speak_to_file(text, voice, speed, sound_file),
                               on_done=when_done, on_failed=when_failed)

    def stop_reading(self):
        wx.adv.Sound.Stop()
        self.reading_cancelled = True  # if it is still being prepared, it will not start playing
        self.status.show("Stopped reading.")

    # ---- small helpers for sound and background work -----------------------------------------

    def play_wav(self, path, message):
        wx.adv.Sound.Stop()  # stop whatever is playing
        self.playing_sound = wx.adv.Sound(str(path))
        self.playing_sound.Play(wx.adv.SOUND_ASYNC)
        self.status.show(message)

    def run_in_background(self, work, on_done, on_failed=None):
        """Run `work()` in a thread; then call on_done(result) or on_failed(error) on the window's thread."""
        def run():
            try:
                result = work()
            except Exception as error:
                traceback.print_exc()
                wx.CallAfter(on_failed or (lambda e: self.status.show(f"❌ {e}")), error)
                return
            wx.CallAfter(on_done, result)
        threading.Thread(target=run, daemon=True).start()

    # ---- creating the audiobook (fixed at the bottom of the tool column) -----------------------

    def on_start(self, event):
        selected_chapters = [section.chapter for section in self.book_sections if section.is_included]
        if not selected_chapters:
            wx.MessageBox("Tick at least one section to read aloud.", "Nothing selected", parent=self)
            return
        self.synthesis_in_progress = True
        self.save_settings()  # so the choices survive even if something goes wrong during the long run
        torch.set_default_device(self.tools.voice_section.device)
        self.tools.set_locked_for_generation(True)
        self.chapter_list.lock_for_generation()

        params = dict(file_path=self.epub_path, voice=self.tools.voice_section.voice.id, pick_manually=False,
                      speed=self.tools.speed_section.speed, output_folder=self.tools.file_section.output_folder,
                      selected_chapters=selected_chapters)
        print('Starting audiobook generation', params | {'selected_chapters': len(selected_chapters)})
        self.status.show("Starting the audiobook ...")
        self.core_thread = CoreThread(params)
        self.core_thread.start()

    def on_stop(self, event):
        answer = wx.MessageBox("Stop making the audiobook?\n\nIt stops after the current sentence. Chapters that are "
                               "already finished are kept, so pressing 'Create audiobook' again continues where it "
                               "stopped (with the same voice and ticked sections).",
                               "Stop", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, parent=self)
        if answer == wx.YES and self.core_thread:
            self.core_thread.request_stop()
            self.tools.create_section.show_stopping()
            self.status.show("Stopping after the current sentence ...")

    def on_core_started(self, event):
        self.tools.create_section.show_started()

    def on_core_status(self, event):
        self.status.show(event.message)
        if event.busy:
            self.tools.create_section.show_busy()

    def on_core_chapter_started(self, event):
        self.chapter_list.set_status(event.chapter_index, "⏳ In progress")

    def on_core_chapter_finished(self, event):
        self.chapter_list.set_status(event.chapter_index, "✅ Done")

    def on_core_progress(self, event):
        stats = event.stats
        self.tools.create_section.show_progress(stats.progress, f"About {stats.eta} left")
        self.status.show(f"Making speech: chapter {stats.chapter}, {stats.chars_per_sec:.0f} characters/sec",
                         stats.progress)

    def on_core_finished(self, event):
        if getattr(event, 'failed', False):
            outcome = "failed"
        elif getattr(event, 'stopped', False):
            outcome = "stopped"
        else:
            outcome = "done"
        self.synthesis_in_progress = False
        self.tools.set_locked_for_generation(False)
        self.tools.create_section.show_finished(outcome)
        self.chapter_list.unlock_after_generation()
        if outcome == "done":
            open_folder_in_file_manager(self.tools.file_section.output_folder)


def main():
    print('Starting GUI...')
    app = wx.App(False)
    frame = MainWindow(None, "Audiblez - Generate Audiobooks from E-books")
    frame.Show(True)
    app.SetTopWindow(frame)
    app.MainLoop()


if __name__ == '__main__':
    main()
