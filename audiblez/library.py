"""
library.py - the audiobook library: one root folder that holds every imported book and its audiobook.

    Audiobook Library/                      the root (default: Documents\\Audiobook Library, changeable in the window)
      library.json                          what happened to each book (this module reads and writes it)
      Yuval Noah Harari - Nexus/            one folder per book, named "Author - Title"
        Nexus.epub                          a COPY of the imported file (the original stays where it was)
        Yuval Noah Harari - Nexus.m4b       the audiobook, once it is made
        work/                               chapter .wav files while the audiobook is being made

WHY ONE FOLDER PER BOOK
    While an audiobook is made, every chapter becomes a .wav file, and the joining step writes
    helper files (one of them always has the same name, "chapters.txt"). In a shared folder the
    files of different books would sit side by side; in its own folder each book keeps them apart.
    Deleting a book from the library is deleting its folder.

WHAT IS TRACKED (library.json)
    For each book: title, author, where it was imported from, and when it was imported, last opened
    and last made into an audiobook. The STATUS shown in the Library window is NOT stored: it is read
    from the book's folder every time (Library.status_of), so it can never be out of date. Delete the
    .m4b and the book shows as "not made yet" again.

WHO CALLS WHAT
    copy_into_library()  only copies files, so the background thread that opens a book may call it
    record_opened(), record_audiobook_made()   change library.json: call them from the window's thread only
"""
import json
import shutil
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

LIBRARY_FILE_NAME = "library.json"
WORK_FOLDER_NAME = "work"  # inside a book's folder: the chapter .wav files while the audiobook is made
DEFAULT_LIBRARY_FOLDER = Path.home() / "Documents" / "Audiobook Library"


class BookStatus:
    """What the Library window shows for a book, from the most finished to the least."""
    AUDIOBOOK_MADE = "✅ Audiobook made"
    PARTLY_MADE = "⏸ Partly made"  # stopped: some chapters are ready, Create continues from there
    OPENED = "📖 Opened"
    IMPORTED = "📥 Imported"
    FILES_MISSING = "❓ EPUB missing"  # the book's folder or EPUB was deleted or moved


@dataclass
class LibraryBook:
    """One book in library.json. Dates are text like "2026-11-14 15:30", so the file stays readable."""
    folder_name: str  # the book's own folder inside the library, "Author - Title"
    epub_file: str  # the file name of the EPUB copy inside that folder ("" for an audiobook without its EPUB)
    title: str = ""
    author: str = ""
    imported_from: str = ""  # where the original EPUB was when it was imported
    imported_at: str = ""
    last_opened_at: str = ""
    audiobook_made_at: str = ""  # when the last audiobook was finished
    audiobook_file: str = ""  # its file name inside the book's folder
    voice: str = ""  # the voice of that audiobook

    @property
    def display_name(self):
        if self.author and self.title:
            return f"{self.author} - {self.title}"
        return self.title or self.folder_name

    @property
    def last_used_at(self):
        """The latest thing that happened to the book; the Library window lists recent books first."""
        return max(self.imported_at, self.last_opened_at, self.audiobook_made_at)


class Library:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.books = {}  # folder_name -> LibraryBook
        self.load()

    # ---- library.json --------------------------------------------------------------------------

    @property
    def library_file(self):
        return self.folder / LIBRARY_FILE_NAME

    def load(self):
        """Read library.json. A missing or broken file is never an error: the library is then empty."""
        try:
            saved = json.loads(self.library_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        known_fields = {field.name for field in fields(LibraryBook)}
        for entry in saved.get("books", []) if isinstance(saved, dict) else []:
            if isinstance(entry, dict) and entry.get("folder_name"):
                book = LibraryBook(**{name: str(value) for name, value in entry.items() if name in known_fields})
                self.books[book.folder_name] = book

    def save(self):
        """Write to a temporary file first, then swap it in, so a crash can never leave half a file."""
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            temporary = self.library_file.with_suffix(".tmp")
            books = [asdict(book) for book in self.books.values()]
            temporary.write_text(json.dumps({"books": books}, indent=2, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.library_file)
        except OSError as error:  # the audiobooks themselves are safe; only the history is not updated
            print("Could not save the library file:", error)

    # ---- where things are ----------------------------------------------------------------------

    def book_folder(self, book):
        return self.folder / book.folder_name

    def epub_path(self, book):
        return self.book_folder(book) / book.epub_file

    def has_epub(self, book):
        """False for an audiobook whose EPUB is gone (or was never there): such a book cannot be opened."""
        return bool(book.epub_file) and self.epub_path(book).is_file()

    def is_in_library(self, epub_path):
        """True for an EPUB that sits in a book folder of this library (Library/<book folder>/<file>.epub)."""
        return Path(epub_path).resolve().parent.parent == self.folder.resolve()

    def book_for_file(self, epub_path):
        """The LibraryBook of an EPUB inside the library, or None."""
        if not self.is_in_library(epub_path):
            return None
        return self.books.get(Path(epub_path).parent.name)

    @staticmethod
    def work_folder_for(epub_path):
        """Where the chapter .wav files of this book go while its audiobook is made."""
        return Path(epub_path).parent / WORK_FOLDER_NAME

    # ---- importing (file work only) ------------------------------------------------------------

    def copy_into_library(self, source_path, metadata):
        """
        Copy an EPUB into its own folder in the library and return the path of the copy.
        The original is never changed. Importing the same file again returns the existing copy;
        a book that is already in the library is simply returned as it is.
        """
        source = Path(source_path)
        if self.is_in_library(source):
            return source
        folder = self.free_folder_for(metadata.audiobook_file_name(fallback=source.stem), source.name)
        copy = folder / source.name
        if not copy.exists():
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copy)  # copy2 also keeps the file's dates
        return copy

    def free_folder_for(self, book_name, epub_file):
        """
        The folder for a book: "Author - Title", or "Author - Title (2)" when that folder already
        holds a DIFFERENT EPUB (another edition with the same title). The same file goes back
        into its own folder.
        """
        number = 1
        while True:
            folder = self.folder / (book_name if number == 1 else f"{book_name} ({number})")
            other_epubs = [path for path in folder.glob("*.epub") if path.name != epub_file]
            if not other_epubs:
                return folder
            number += 1

    # ---- recording what happened (window thread only) ------------------------------------------

    def record_opened(self, epub_path, metadata, imported_from=""):
        """A book from the library was opened (imported_from is set when it was just imported)."""
        epub_path = Path(epub_path)
        if not self.is_in_library(epub_path):
            return
        now = now_as_text()
        book = self.books.get(epub_path.parent.name)
        if book is None:
            book = LibraryBook(folder_name=epub_path.parent.name, epub_file=epub_path.name, imported_at=now)
            self.books[book.folder_name] = book
        if imported_from and not book.imported_from:
            book.imported_from = str(imported_from)
        book.title = metadata.title or book.title
        book.author = metadata.authors[0] if metadata.authors else book.author
        book.last_opened_at = now
        self.save()

    def record_audiobook_made(self, epub_path, audiobook_file, voice):
        book = self.book_for_file(epub_path)
        if book is None:
            return
        book.audiobook_made_at = now_as_text()
        book.audiobook_file = audiobook_file
        book.voice = voice
        self.save()

    # ---- what the Library window shows ---------------------------------------------------------

    def status_of(self, book):
        """Read from the book's folder, so it is always true (see the top of this module)."""
        folder = self.book_folder(book)
        if book.audiobook_file and (folder / book.audiobook_file).is_file():
            return BookStatus.AUDIOBOOK_MADE  # even without its EPUB: the audiobook is what matters most
        if not self.has_epub(book):
            return BookStatus.FILES_MISSING
        work_folder = folder / WORK_FOLDER_NAME
        if work_folder.is_dir() and any(work_folder.glob("*.wav")):
            return BookStatus.PARTLY_MADE
        return BookStatus.OPENED if book.last_opened_at else BookStatus.IMPORTED

    def books_recent_first(self):
        return sorted(self.books.values(), key=lambda book: book.last_used_at, reverse=True)


def now_as_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M")
