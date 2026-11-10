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

from audiblez.ui_common import SPACING, bold, describe_audio_length


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
        self.description = wx.StaticText(box, label="Use 'Open EPUB' in the tools on the left to choose a book.")

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
        self.title.SetLabel(metadata.title or "(no title)")
        self.title.Wrap(650)
        values = {"Author": ", ".join(metadata.authors), "ISBN": metadata.isbn, "Publisher": metadata.publisher,
                  "Published": metadata.published, "Language": metadata.language}
        for name, value in values.items():
            self.detail_values[name].SetLabel(value or "-")
        self._show_description(metadata.description)
        self._show_cover(metadata.cover_image)
        self._show_links(metadata.links())
        self.Layout()

    def show_read_aloud_length(self, characters, included_count, total_count):
        self.detail_values["Read aloud"].SetLabel(
            f"{describe_audio_length(characters)}, {included_count} of {total_count} sections")

    def _show_description(self, description):
        short = description if len(description) <= self.DESCRIPTION_LENGTH else (
                description[:self.DESCRIPTION_LENGTH].rsplit(" ", 1)[0] + " ...")
        self.description.SetLabel(short)
        self.description.SetToolTip(description or None)
        self.description.Wrap(650)

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
        self.links_sizer.Clear(delete_windows=True)
        for link in links:
            # A HyperlinkCtrl opens the address in the default browser when clicked
            self.links_sizer.Add(wx.adv.HyperlinkCtrl(self.box, label=link.label, url=link.url), 0, wx.BOTTOM, 2)
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

        self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
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

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(heading, 0, wx.LEFT | wx.TOP, SPACING)
        sizer.Add(explanation, 0, wx.LEFT, SPACING)
        sizer.Add(self.show_short_files_checkbox, 0, wx.LEFT | wx.TOP, SPACING)
        sizer.Add(self.table, 1, wx.ALL | wx.EXPAND, SPACING)
        self.SetSizer(sizer)

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
    """The text of the selected section. Lines that came from picture text are shown in yellow."""

    HIGHLIGHT = wx.TextAttr(wx.BLACK, wx.Colour(255, 228, 130))  # black text on yellow

    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main_window = main_window
        self.section = None

        self.heading = bold(wx.StaticText(self, label="Text to be read aloud"))
        self.file_label = wx.StaticText(self, label="Select a section on the left. You can edit the text here.")
        self.text_area = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_WORDWRAP | wx.TE_RICH2)  # RICH2: colours
        self.text_area.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.text_area.Bind(wx.EVT_TEXT, self.on_text_edited)

        self.legend = wx.StaticText(self, label="")
        self.legend.SetBackgroundColour(self.HIGHLIGHT.GetBackgroundColour())
        self.legend.SetForegroundColour(wx.BLACK)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.heading, 0, wx.LEFT | wx.TOP, SPACING)
        sizer.Add(self.file_label, 0, wx.LEFT, SPACING)
        sizer.Add(self.legend, 0, wx.LEFT | wx.TOP, SPACING)
        sizer.Add(self.text_area, 1, wx.ALL | wx.EXPAND, SPACING)
        self.SetSizer(sizer)

    def show_section(self, section, highlighted_classes=()):
        """Show the section's text; lines from elements with one of `highlighted_classes` turn yellow."""
        self.section = section
        self.heading.SetLabel(section.display_title)
        self.file_label.SetLabel(f"File: {section.file_name}   ({section.reason})")
        self.text_area.ChangeValue(section.chapter.extracted_text)  # ChangeValue does not fire EVT_TEXT
        count = self.highlight_lines(section.chapter, set(highlighted_classes))
        self.legend.SetLabel(f" {count} yellow line(s): text found next to pictures. "
                             "Remove it with tool 6 on the left. ")
        self.legend.Show(count > 0)
        self.Layout()

    def highlight_lines(self, chapter, css_classes):
        """Colour every line whose element had one of `css_classes`. Returns how many lines were coloured."""
        line_kinds = getattr(chapter, "line_kinds", None)
        lines = chapter.extracted_text.split("\n")[:-1]  # the text ends with a newline
        if not css_classes or not line_kinds or len(line_kinds) != len(lines):
            return 0  # nothing to colour, or the text was edited by hand so the lines no longer match
        position, coloured = 0, 0
        for line, (_tag, classes) in zip(lines, line_kinds):
            if css_classes & set(classes):
                self.text_area.SetStyle(position, position + len(line), self.HIGHLIGHT)
                coloured += 1
            position += len(line) + 1  # +1 for the newline
        return coloured

    def selected_text(self):
        """The text the user highlighted with the mouse, or "" if nothing is highlighted."""
        return self.text_area.GetStringSelection()

    def on_text_edited(self, event):
        """Edits go straight into the text that will be read aloud."""
        if self.section is None:
            return
        self.section.chapter.extracted_text = self.text_area.GetValue()
        self.main_window.on_section_text_edited(self.section)
