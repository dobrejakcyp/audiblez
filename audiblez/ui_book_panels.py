"""
ui_book_panels.py - the parts of the window that SHOW the book:

    BookCard           cover, title, author, ISBN ... and links to learn more (top of the window)
    ChapterListPanel   every section of the book, ticked = read aloud (left column)
    TextPreviewPanel   the text of the selected section, editable (right column)

Panels never reach into each other: they call methods of MainWindow (in ui.py),
which then tells the other panels what to show.
"""
import io

import wx
import wx.adv
from PIL import Image

from audiblez.epub_text_extractor import QUOTE_TAG, SPOKEN_MARKER
from audiblez.fonts import DEFAULT_FONT_SIZE, LARGEST_FONT_SIZE, SMALLEST_FONT_SIZE
from audiblez.spoken_headings import SPOKEN_HEADING
from audiblez.ui_common import SPACING, bold, describe_audio_length, make_text_font, set_wrapped_text


# =============================================================================================
# Book card: cover, details and links
# =============================================================================================

class BookCard(wx.Panel):
    COVER_HEIGHT = 180
    DESCRIPTION_LENGTH = 350  # longer descriptions are shortened; the full text is in the tooltip
    DETAIL_NAMES = ("Author", "ISBN", "Publisher", "Published", "Language", "Read aloud")

    def __init__(self, parent):
        super().__init__(parent)
        box_sizer = wx.StaticBoxSizer(wx.HORIZONTAL, self, "Book")
        box = box_sizer.GetStaticBox()  # controls inside a StaticBoxSizer must be children of its box

        self.cover = wx.StaticBitmap(box)
        self.title = bold(wx.StaticText(box, label="No book opened"), size_change=3)
        self.description = wx.StaticText(box, label="Use 'Import EPUB' or 'Library' in the tools on the left to choose a book.")

        details_grid = wx.FlexGridSizer(cols=2, vgap=3, hgap=12)
        self.detail_values = {}
        for name in self.DETAIL_NAMES:
            details_grid.Add(bold(wx.StaticText(box, label=name + ":")))
            self.detail_values[name] = wx.StaticText(box, label="")
            details_grid.Add(self.detail_values[name])

        self.links_heading = bold(wx.StaticText(box, label="Learn more:"))
        self.links_sizer = wx.BoxSizer(wx.VERTICAL)
        self.links_heading.Hide()

        middle = wx.BoxSizer(wx.VERTICAL)
        middle.Add(self.title, 0, wx.BOTTOM, SPACING)
        middle.Add(details_grid, 0, wx.BOTTOM, SPACING)
        middle.Add(self.description, 0, wx.EXPAND)

        links_column = wx.BoxSizer(wx.VERTICAL)
        links_column.Add(self.links_heading, 0, wx.BOTTOM, SPACING)
        links_column.Add(self.links_sizer)

        box_sizer.Add(self.cover, 0, wx.ALL, SPACING)
        box_sizer.Add(middle, 1, wx.ALL | wx.EXPAND, SPACING)
        box_sizer.Add(links_column, 0, wx.ALL, SPACING)
        self.box = box
        self.cover.Hide()
        self.SetSizer(box_sizer)

    def show_book(self, metadata):
        set_wrapped_text(self.title, metadata.title or "(no title)", 650)
        values = {"Author": ", ".join(metadata.authors), "ISBN": metadata.isbn, "Publisher": metadata.publisher,
                  "Published": metadata.published, "Language": metadata.language}
        for name, value in values.items():
            self.detail_values[name].SetLabel(value or "-")
        self._show_description(metadata.description)
        self._show_cover(metadata.cover_image)
        self._show_links(metadata.links())
        self.Layout()
        self.GetParent().Layout()  # the card may now need more (or less) height than the previous book's

    def show_read_aloud_length(self, characters, included_count, total_count):
        self.detail_values["Read aloud"].SetLabel(
            f"{describe_audio_length(characters)}, {included_count} of {total_count} sections")

    def _show_description(self, description):
        short = description if len(description) <= self.DESCRIPTION_LENGTH else (
                description[:self.DESCRIPTION_LENGTH].rsplit(" ", 1)[0] + " ...")
        set_wrapped_text(self.description, short, 650)
        self.description.SetToolTip(description or None)

    def _show_cover(self, cover_image):
        try:
            picture = Image.open(io.BytesIO(cover_image)).convert("RGB")
        except Exception:  # no cover, or a format we cannot read: just show none
            self.cover.Hide()
            return
        width = max(1, int(self.COVER_HEIGHT * picture.width / picture.height))
        picture = picture.resize((width, self.COVER_HEIGHT), Image.LANCZOS)
        image = wx.Image(width, self.COVER_HEIGHT)
        image.SetData(picture.tobytes())
        self.cover.SetBitmap(wx.Bitmap(image))
        self.cover.Show()

    def _show_links(self, links):
        """One button per link; it opens the address in the default browser (the address is in the tooltip)."""
        self.links_sizer.Clear(delete_windows=True)
        for link in links:
            button = wx.Button(self.box, label=f"{link.label}  ↗")
            button.SetToolTip(link.url)
            button.Bind(wx.EVT_BUTTON, lambda event, url=link.url: wx.LaunchDefaultBrowser(url))
            self.links_sizer.Add(button, 0, wx.EXPAND | wx.BOTTOM, 3)
        self.links_heading.Show(bool(links))


# =============================================================================================
# Left column: the list of book sections
# =============================================================================================

class ChapterListPanel(wx.Panel):
    """
    Every row of the table shows one BookSection (see chapter_selection.py).
    Rows are NOT the same as file numbers: short/empty files can be hidden, so we keep
    self.visible_sections, where position N in the list = row N in the table.
    """

    COLUMN_READ, COLUMN_TITLE, COLUMN_LENGTH, COLUMN_WHY, COLUMN_STATUS = range(5)

    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main_window = main_window
        self.sections = []
        self.visible_sections = []
        # wxPython fires "ticked"/"unticked" events even when WE change the boxes (redrawing, hiding them
        # during generation). While this is True those events are ignored, so they cannot undo the user's choice.
        self.ignoring_tick_events = False

        heading = bold(wx.StaticText(self, label="Book contents"))
        explanation = wx.StaticText(self, label="Ticked parts are read aloud, grey parts are skipped.")
        self.show_short_files_checkbox = wx.CheckBox(self, label="Show short and empty files (cover, title page ...)")
        self.show_short_files_checkbox.Bind(wx.EVT_CHECKBOX, lambda event: self.redraw())

        self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)  # one row at a time
        self.table.SetMinSize((250, 200))  # otherwise the sum of the column widths becomes the minimum width
        for column, name, width in [(self.COLUMN_READ, "Read", 45), (self.COLUMN_TITLE, "Title", 260),
                                    (self.COLUMN_LENGTH, "Characters", 75), (self.COLUMN_WHY, "Why", 120),
                                    (self.COLUMN_STATUS, "Status", 90)]:
            self.table.InsertColumn(column, name)
            self.table.SetColumnWidth(column, width)
        self.table.EnableCheckBoxes()
        self.table.Bind(wx.EVT_LIST_ITEM_CHECKED, lambda event: self.set_included(event.GetIndex(), True))
        self.table.Bind(wx.EVT_LIST_ITEM_UNCHECKED, lambda event: self.set_included(event.GetIndex(), False))
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_row_selected)

        # The header has its own sizer, so MainWindow can give it the same height as the text column's
        # header: then the list and the text start at the same line (see set_header_height).
        self.header_sizer = wx.BoxSizer(wx.VERTICAL)
        self.header_sizer.Add(heading, 0, wx.LEFT | wx.TOP, SPACING)
        self.header_sizer.Add(explanation, 0, wx.LEFT, SPACING)
        self.header_sizer.Add(self.show_short_files_checkbox, 0, wx.LEFT | wx.TOP, SPACING)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.header_sizer, 0, wx.EXPAND)
        sizer.Add(self.table, 1, wx.ALL | wx.EXPAND, SPACING)
        self.SetSizer(sizer)

    def header_height(self):
        return self.header_sizer.CalcMin().height

    def set_header_height(self, height):
        self.header_sizer.SetMinSize((-1, height))
        self.Layout()

    # ---- filling the table -------------------------------------------------------------------

    def show_sections(self, sections):
        self.sections = sections
        self.redraw()

    def redraw(self):
        """(Re)draw all rows, in book order."""
        show_short_files = self.show_short_files_checkbox.GetValue()
        self.visible_sections = [s for s in self.sections if show_short_files or not s.is_short]
        self.ignoring_tick_events = True
        self.table.DeleteAllItems()
        for row, section in enumerate(self.visible_sections):
            self.table.Append(['', section.display_title, f"{section.text_length:,}", section.reason, ''])
            self.table.CheckItem(row, section.is_included)
            self.paint_row(row)
        self.ignoring_tick_events = False

    def paint_row(self, row):
        """Grey text = this part will not be read aloud. System colours, so dark mode keeps working."""
        colour_name = wx.SYS_COLOUR_LISTBOXTEXT if self.visible_sections[row].is_included else wx.SYS_COLOUR_GRAYTEXT
        self.table.SetItemTextColour(row, wx.SystemSettings.GetColour(colour_name))

    def refresh_length(self, section):
        if section in self.visible_sections:
            self.table.SetItem(self.visible_sections.index(section), self.COLUMN_LENGTH, f"{section.text_length:,}")

    # ---- user actions ------------------------------------------------------------------------

    def set_included(self, row, is_included):
        if self.ignoring_tick_events:
            return
        section = self.visible_sections[row]
        section.is_included = is_included
        section.chapter.is_selected = is_included  # the flag core.main() looks at
        self.paint_row(row)
        self.main_window.on_sections_changed()

    def on_row_selected(self, event):
        self.main_window.on_section_selected(self.visible_sections[event.GetIndex()])

    def select_section(self, section):
        """Highlight a section's row (this also shows its text, via on_row_selected)."""
        if section in self.visible_sections:
            row = self.visible_sections.index(section)
            self.table.Select(row)
            self.table.EnsureVisible(row)
        else:
            self.main_window.on_section_selected(section)

    # ---- during generation -------------------------------------------------------------------

    def lock_for_generation(self):
        """While generating, the ticks cannot change; ticked rows get a ✔️ and the status 'Planned'."""
        self.ignoring_tick_events = True  # stays on until unlock_after_generation()
        self.table.EnableCheckBoxes(False)
        self.show_short_files_checkbox.Disable()  # redrawing now would wipe the status column
        for row, section in enumerate(self.visible_sections):
            if section.is_included:
                self.table.SetItem(row, self.COLUMN_READ, '✔️')
                self.table.SetItem(row, self.COLUMN_STATUS, "Planned")

    def unlock_after_generation(self):
        self.table.EnableCheckBoxes(True)
        self.show_short_files_checkbox.Enable()
        for row, section in enumerate(self.visible_sections):
            self.table.SetItem(row, self.COLUMN_READ, '')
            self.table.CheckItem(row, section.is_included)  # the status column is kept on purpose
        self.ignoring_tick_events = False

    def set_status(self, chapter_index, status):
        for row, section in enumerate(self.visible_sections):
            if section.chapter.chapter_index == chapter_index:
                self.table.SetItem(row, self.COLUMN_STATUS, status)


# =============================================================================================
# Right column: the text that will be read aloud (editable)
# =============================================================================================

class TextPreviewPanel(wx.Panel):
    """
    The text of the selected section, coloured by what each line is (see line_style):
    headings light blue, quotations lavender, picture text yellow, normal text plain.
    Above it: a search box that searches the whole book (MainWindow.search_book).
    Right-click opens a menu: read the highlighted text aloud, stop reading, and the usual
    cut / copy / paste / select all (the text can be edited before the audiobook is made).
    Colours follow the lines as they were extracted; after you edit a section by hand they are
    left off for it, because the lines may no longer match.
    """

    HIGHLIGHT = wx.TextAttr(wx.BLACK, wx.Colour(255, 228, 130))  # picture text: black on yellow (it asks for action)
    HEADING_COLOUR = wx.Colour(220, 232, 246)  # muted blue
    QUOTE_COLOUR = wx.Colour(236, 230, 246)  # muted lavender
    HEADING_TAGS = {SPOKEN_HEADING, "h1", "h2", "h3", "h4", "h5", "h6"}
    QUOTE_TAGS = {QUOTE_TAG, SPOKEN_MARKER}
    TIP = "Tip: highlight some text and right-click to hear it."

    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main_window = main_window
        self.section = None

        # The header always has exactly three one-line rows, so the text below never jumps up or down:
        # long titles and file names get "..." instead of a second line (ST_ELLIPSIZE_...).
        self.heading = bold(wx.StaticText(self, label="Text to be read aloud", style=wx.ST_ELLIPSIZE_END))
        self.file_label = wx.StaticText(self, label="Select a section on the left. You can edit the text here.",
                                        style=wx.ST_ELLIPSIZE_MIDDLE)
        # Third row: the yellow "N yellow lines" note when this section has picture text, otherwise the tip
        self.note = wx.StaticText(self, label=self.TIP, style=wx.ST_ELLIPSIZE_END)
        for label in (self.heading, self.file_label, self.note):
            label.SetMinSize((50, -1))  # may become narrow; "..." takes care of the rest
        # RICH2: allows colours. NOHIDESEL: a highlighted line stays visible when the focus is elsewhere.
        self.text_area = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_WORDWRAP | wx.TE_RICH2 | wx.TE_NOHIDESEL)
        self.text_area.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)
        self.text_area.SetFont(make_text_font("", DEFAULT_FONT_SIZE))  # MainWindow applies the saved font
        self.highlighted_classes = ()  # remembered, so the text can be shown again in another font
        self.font_button = wx.Button(self, label="Aa  Font...", style=wx.BU_EXACTFIT)
        self.font_button.SetToolTip("Choose the font and size of the book text (also in View → Text font)")
        self.font_button.Bind(wx.EVT_BUTTON, main_window.on_choose_text_font)
        self.text_area.Bind(wx.EVT_TEXT, self.on_text_edited)

        # Search the whole book: Enter or ▶ = next place, Shift+Enter or ◀ = previous place (Ctrl+F jumps here)
        self.search_box = wx.SearchCtrl(self, size=(190, -1), style=wx.TE_PROCESS_ENTER)
        self.search_box.SetDescriptiveText("Search the book (Ctrl+F)")
        self.search_box.ShowCancelButton(True)
        self.search_box.Bind(wx.EVT_TEXT_ENTER, lambda event: self.search(forward=not wx.GetKeyState(wx.WXK_SHIFT)))
        self.search_box.Bind(wx.EVT_SEARCH, lambda event: self.search(forward=True))
        self.search_box.Bind(wx.EVT_SEARCH_CANCEL, lambda event: self.clear_search())
        self.previous_match_button = wx.Button(self, label="◀", style=wx.BU_EXACTFIT)
        self.next_match_button = wx.Button(self, label="▶", style=wx.BU_EXACTFIT)
        self.previous_match_button.SetToolTip("Previous place (Shift+Enter)")
        self.next_match_button.SetToolTip("Next place (Enter)")
        self.previous_match_button.Bind(wx.EVT_BUTTON, lambda event: self.search(forward=False))
        self.next_match_button.Bind(wx.EVT_BUTTON, lambda event: self.search(forward=True))
        self.match_count = wx.StaticText(self, label="", size=(70, -1))

        # A small legend of the line colours, next to the file name
        self.legend = [self.legend_label(" Heading ", self.HEADING_COLOUR), self.legend_label(" Quote ", self.QUOTE_COLOUR),
                       self.legend_label(" Picture text ", self.HIGHLIGHT.GetBackgroundColour())]

        self.header_sizer = wx.BoxSizer(wx.VERTICAL)  # see ChapterListPanel.header_sizer
        title_row = wx.BoxSizer(wx.HORIZONTAL)
        title_row.Add(self.heading, 1, wx.ALIGN_CENTER_VERTICAL)
        title_row.Add(self.search_box, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, SPACING)
        title_row.Add(self.previous_match_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, SPACING // 2)
        title_row.Add(self.next_match_button, 0, wx.ALIGN_CENTER_VERTICAL)
        title_row.Add(self.match_count, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, SPACING)
        title_row.Add(self.font_button, 0, wx.LEFT, SPACING)
        file_row = wx.BoxSizer(wx.HORIZONTAL)
        file_row.Add(self.file_label, 1, wx.ALIGN_CENTER_VERTICAL)
        for label in self.legend:
            file_row.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, SPACING // 2)
        self.header_sizer.Add(title_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, SPACING)
        self.header_sizer.Add(file_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, SPACING // 2)
        self.header_sizer.Add(self.note, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, SPACING)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.header_sizer, 0, wx.EXPAND)
        sizer.Add(self.text_area, 1, wx.ALL | wx.EXPAND, SPACING)
        self.SetSizer(sizer)

    def header_height(self):
        return self.header_sizer.CalcMin().height

    def set_header_height(self, height):
        self.header_sizer.SetMinSize((-1, height))
        self.Layout()

    def legend_label(self, text, colour):
        label = wx.StaticText(self, label=text)
        label.SetBackgroundColour(colour)
        label.SetForegroundColour(wx.BLACK)
        label.SetToolTip("Lines of this kind have this colour in the text below")
        return label

    def set_text_font(self, face, size):
        """Show the book text in another font. The text is put in again, so the yellow lines are kept."""
        size = min(LARGEST_FONT_SIZE, max(SMALLEST_FONT_SIZE, size or DEFAULT_FONT_SIZE))
        self.text_area.SetFont(make_text_font(face, size))
        if self.section is not None:
            position = self.text_area.GetInsertionPoint()  # stay at the same place in the text
            self.show_section(self.section, self.highlighted_classes)
            self.text_area.SetInsertionPoint(position)
            self.text_area.ShowPosition(position)

    def show_note(self, yellow_lines):
        """The third header row: the yellow note if this section has picture text, otherwise the tip."""
        if yellow_lines:
            self.note.SetLabel(f"{yellow_lines} yellow line(s): text found next to pictures. "
                               "Jump to it or remove it with tool 4 on the left.")
            self.note.SetBackgroundColour(self.HIGHLIGHT.GetBackgroundColour())
            self.note.SetForegroundColour(wx.BLACK)
        else:
            self.note.SetLabel(self.TIP)
            self.note.SetBackgroundColour(wx.NullColour)  # back to the normal window colours
            self.note.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))
        self.note.Refresh()

    def show_section(self, section, highlighted_classes=()):
        """Show the section's text; lines from elements with one of `highlighted_classes` turn yellow."""
        self.section = section
        self.highlighted_classes = highlighted_classes
        self.heading.SetLabel(section.display_title)
        self.file_label.SetLabel(f"File: {section.file_name}   ({section.reason})")
        self.text_area.ChangeValue(section.chapter.extracted_text)  # ChangeValue does not fire EVT_TEXT
        self.show_note(self.colour_lines(section.chapter, set(highlighted_classes)))

    def line_style(self, kind, picture_classes):
        """The colours for one line from its kind (tag, css classes); None = plain text."""
        tag, classes = kind
        if picture_classes & set(classes):
            return self.HIGHLIGHT
        text_colour = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        if tag in self.HEADING_TAGS:
            return wx.TextAttr(text_colour, self.HEADING_COLOUR)
        if tag in self.QUOTE_TAGS:
            return wx.TextAttr(text_colour, self.QUOTE_COLOUR)
        return None

    def colour_lines(self, chapter, picture_classes):
        """Colour every line by its kind. Returns how many lines are picture text (yellow)."""
        line_kinds = getattr(chapter, "line_kinds", None)
        lines = chapter.extracted_text.split("\n")[:-1]  # the text ends with a newline
        if not line_kinds or len(line_kinds) != len(lines):
            return 0  # the text was edited by hand, so the lines no longer match their kinds
        position, picture_lines = 0, 0
        for line, kind in zip(lines, line_kinds):
            style = self.line_style(kind, picture_classes)
            if style is not None:
                self.text_area.SetStyle(position, position + len(line), style)
                picture_lines += style is self.HIGHLIGHT
            position += len(line) + 1  # +1 for the newline
        return picture_lines

    def selected_text(self):
        """The text the user highlighted with the mouse, or "" if nothing is highlighted."""
        return self.text_area.GetStringSelection()

    # ---- search (the whole book; MainWindow decides where the next place is) -------------------

    def focus_search(self):
        self.search_box.SetFocus()
        self.search_box.SelectAll()

    def search(self, forward):
        query = self.search_box.GetValue()
        if query.strip():
            position = self.text_area.GetSelection()[0]
            self.main_window.search_book(query, self.section, position, forward)

    def clear_search(self):
        self.search_box.Clear()
        self.match_count.SetLabel("")

    def show_match_count(self, text):
        self.match_count.SetLabel(text)

    def reveal_range(self, start, end):
        """Scroll to characters start..end of the shown text and highlight them (used by search)."""
        self.text_area.SetSelection(start, end)
        self.text_area.ShowPosition(start)

    def reveal_line(self, line_number):
        """Scroll to line `line_number` of the shown text and highlight it (used to jump to picture text)."""
        lines = self.text_area.GetValue().split("\n")
        if not 0 <= line_number < len(lines):
            return
        start = sum(len(line) + 1 for line in lines[:line_number])  # +1 for each newline
        self.text_area.SetSelection(start, start + len(lines[line_number]))
        self.text_area.ShowPosition(start)

    # ---- right-click menu ----------------------------------------------------------------------

    def on_context_menu(self, event):
        selected = self.selected_text().strip()
        menu = wx.Menu()
        read = menu.Append(wx.ID_ANY, "🔊 Read the selected text aloud" if selected
                           else "🔊 Read aloud (highlight some text first)")
        read.Enable(bool(selected))
        stop = menu.Append(wx.ID_ANY, "⏹ Stop reading")
        menu.AppendSeparator()
        editing = [(wx.ID_CUT, self.text_area.CanCut(), self.text_area.Cut),
                   (wx.ID_COPY, self.text_area.CanCopy(), self.text_area.Copy),
                   (wx.ID_PASTE, self.text_area.CanPaste(), self.text_area.Paste),
                   (wx.ID_SELECTALL, True, self.text_area.SelectAll)]
        for item_id, possible, action in editing:
            menu.Append(item_id).Enable(possible)  # standard items: Windows provides label and shortcut
            menu.Bind(wx.EVT_MENU, lambda event, action=action: action(), id=item_id)
        menu.Bind(wx.EVT_MENU, lambda event: self.main_window.read_aloud(selected), read)
        menu.Bind(wx.EVT_MENU, lambda event: self.main_window.stop_reading(), stop)
        self.text_area.PopupMenu(menu)
        menu.Destroy()

    def on_text_edited(self, event):
        """Edits go straight into the text that will be read aloud."""
        if self.section is None:
            return
        self.section.chapter.extracted_text = self.text_area.GetValue()
        self.main_window.on_section_text_edited(self.section)
