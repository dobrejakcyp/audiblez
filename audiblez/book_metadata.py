"""
book_metadata.py - the facts about a book (title, author, ISBN, cover ...) and links to learn more.

Everything here is read from the EPUB file itself. Nothing is looked up online:
the links are only opened in your browser when you click them in the window.
"""
import re
from dataclasses import dataclass, field
from urllib.parse import quote_plus

import ebooklib
from bs4 import BeautifulSoup

# A 13-digit ISBN (starts with 978 or 979) or a 10-digit one (the last character may be X).
ISBN_PATTERN = re.compile(r"97[89]\d{10}|\d{9}[\dX]")


@dataclass
class BookLink:
    """One clickable link in the book card."""
    label: str
    url: str


@dataclass
class BookMetadata:
    title: str = ""
    authors: list = field(default_factory=list)
    isbn: str = ""
    publisher: str = ""
    published: str = ""  # usually a date like 2025-01-21, sometimes only a year
    language: str = ""  # a code like "en", "en-GB", "nl"
    description: str = ""  # the publisher's blurb, as plain text
    cover_image: bytes = b""

    @classmethod
    def from_epub(cls, book):
        """Read everything we can from an ebooklib book (the result of epub.read_epub)."""

        def all_values(name):
            return [value.strip() for value, _attributes in book.get_metadata("DC", name) if value and value.strip()]

        def first_value(name):
            values = all_values(name)
            return values[0] if values else ""

        cover = find_cover(book)
        return cls(
            title=first_value("title"),
            authors=all_values("creator"),
            isbn=cls._find_isbn(all_values("identifier")),
            publisher=first_value("publisher"),
            published=first_value("date")[:10],
            language=first_value("language"),
            description=cls._plain_text(first_value("description")),
            cover_image=cover.get_content() if cover else b"",
        )

    @staticmethod
    def _find_isbn(identifiers):
        """EPUBs store identifiers like "urn:isbn:978-0-06-345398-2" or "uuid:...". Return the ISBN digits, or ""."""
        for identifier in identifiers:
            candidate = identifier.split(":")[-1].replace("-", "").replace(" ", "").upper()
            if ISBN_PATTERN.fullmatch(candidate):
                return candidate
        return ""

    @staticmethod
    def _plain_text(html_or_text):
        """Descriptions are often small pieces of HTML; keep only the words."""
        return " ".join(BeautifulSoup(html_or_text, "lxml").get_text(" ").split()) if html_or_text else ""

    # ---- links -------------------------------------------------------------------------------

    @property
    def search_title(self):
        """The title without bracketed extras: "Sapiens [Tenth Anniversary Edition]" -> "Sapiens"."""
        return re.sub(r"\s*[\[(].*?[\])]", "", self.title).strip()

    def links(self):
        """Links to learn more about the book. They are searches, so they always lead somewhere useful."""
        wikipedia_search = f"https://{self._wikipedia_language()}.wikipedia.org/w/index.php?search="
        title_and_author = f"{self.search_title} {self.authors[0] if self.authors else ''}".strip()
        links = []
        if self.search_title:
            links.append(BookLink("The book on Wikipedia", wikipedia_search + quote_plus(self.search_title)))
        for author in self.authors[:2]:
            links.append(BookLink(f"{author} on Wikipedia", wikipedia_search + quote_plus(author)))
        if title_and_author:
            links.append(BookLink("Search DuckDuckGo", "https://duckduckgo.com/?q=" + quote_plus(title_and_author)))
        goodreads_query = self.isbn or title_and_author  # the ISBN finds the exact edition
        if goodreads_query:
            links.append(BookLink("Goodreads (ratings and reviews)",
                                  "https://www.goodreads.com/search?q=" + quote_plus(goodreads_query)))
        return links

    def _wikipedia_language(self):
        """Use the Wikipedia in the book's own language ("nl" -> nl.wikipedia.org); English if unknown."""
        code = self.language[:2].lower()
        return code if code.isalpha() and len(code) == 2 else "en"


def find_cover(book):
    """Find the cover image of an ebooklib book, or None. (Moved here unchanged from core.py.)"""
    def is_image(item):
        return item is not None and item.media_type.startswith('image/')

    for item in book.get_items_of_type(ebooklib.ITEM_COVER):
        if is_image(item):
            return item

    # https://idpf.org/forum/topic-715
    for meta in book.get_metadata('OPF', 'cover'):
        if is_image(item := book.get_item_with_id(meta[1]['content'])):
            return item

    if is_image(item := book.get_item_with_id('cover')):
        return item

    for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
        if 'cover' in item.get_name().lower() and is_image(item):
            return item

    return None
