"""
ui_library_dialog.py - the Library window: every imported book and what has happened to it.

    Book                          Status              Imported          Last opened       Audiobook made
    Yuval Noah Harari - Nexus     ✅ Audiobook made   2026-11-14 15:30  2026-11-14 15:31  2026-11-14 17:02
    ...
    [Open book]  [Show folder]                                                            [Close]

Double-click a row (or press Open book) to open it. The status is read from the book's folder each
time the window opens (see library.py), so it is always up to date. The list itself is library.json.
"""
import wx

from audiblez.ui_common import SPACING
from audiblez.ui_tool_column import open_folder_in_file_manager


class LibraryDialog(wx.Dialog):
    COLUMNS = [("Book", 330), ("Status", 140), ("Imported", 125), ("Last opened", 125), ("Audiobook made", 125)]

    def __init__(self, parent, library):
        """
        library   the Library (library.py) to show.
        After ShowModal() returns wx.ID_OK, `chosen_epub_path` is the book to open.
        """
        super().__init__(parent, title="Library", size=(900, 520), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.library = library
        self.chosen_epub_path = None
        self.books = library.books_recent_first()

        intro = wx.StaticText(self, label=f"Books in {library.folder}. Double-click a book to open it.")
        self.table = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for column, (name, width) in enumerate(self.COLUMNS):
            self.table.InsertColumn(column, name)
            self.table.SetColumnWidth(column, width)
        self.fill_table()
        self.table.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda event: self.open_selected_book())  # double-click or Enter
        self.table.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda event: self.update_buttons())

        self.open_button = wx.Button(self, label="📖 Open book")
        self.folder_button = wx.Button(self, label="Show folder")
        close_button = wx.Button(self, wx.ID_CLOSE, label="Close")
        self.open_button.Bind(wx.EVT_BUTTON, lambda event: self.open_selected_book())
        self.folder_button.Bind(wx.EVT_BUTTON, lambda event: self.show_selected_folder())
        close_button.Bind(wx.EVT_BUTTON, lambda event: self.EndModal(wx.ID_CLOSE))
        self.SetEscapeId(wx.ID_CLOSE)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(self.open_button, 0, wx.RIGHT, SPACING)
        buttons.Add(self.folder_button, 0, wx.RIGHT, SPACING)
        buttons.AddStretchSpacer()
        buttons.Add(close_button)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(intro, 0, wx.ALL, SPACING * 2)
        sizer.Add(self.table, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, SPACING * 2)
        if not self.books:
            sizer.Add(wx.StaticText(self, label="The library is empty. Use 📥 Import EPUB... to add a book."),
                      0, wx.ALL, SPACING * 2)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, SPACING * 2)
        self.SetSizer(sizer)

        if self.books:
            self.table.Select(0)
        self.update_buttons()

    def fill_table(self):
        for book in self.books:
            self.table.Append([book.display_name, self.library.status_of(book), book.imported_at,
                               book.last_opened_at, book.audiobook_made_at or "-"])

    def selected_book(self):
        row = self.table.GetFirstSelected()
        return self.books[row] if row != -1 else None

    def update_buttons(self):
        book = self.selected_book()
        self.open_button.Enable(book is not None and self.library.has_epub(book))
        self.folder_button.Enable(book is not None and self.library.book_folder(book).is_dir())

    def open_selected_book(self):
        book = self.selected_book()
        if book is None or not self.library.has_epub(book):
            return
        self.chosen_epub_path = str(self.library.epub_path(book))
        self.EndModal(wx.ID_OK)

    def show_selected_folder(self):
        book = self.selected_book()
        if book is not None:
            open_folder_in_file_manager(str(self.library.book_folder(book)))
