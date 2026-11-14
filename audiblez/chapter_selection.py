"""
chapter_selection.py - decides WHICH PARTS of the book are read aloud, and explains why.

THE BIG PICTURE
    An EPUB is a zip folder of small web pages ("files"): cover, title page, chapters, notes,
    index, copyright ... Every file becomes one BookSection with:

        display_title   a human name, taken from the book's own table of contents
        is_included     read aloud or not (only the default; you can change it in the GUI)
        reason          a few words explaining that default, shown in the GUI's "Why" column
        is_short        True for (nearly) empty files; the GUI hides these unless you ask

HOW THE DEFAULT IS DECIDED (the first step that applies wins)
    1. 100 characters or less               -> not read, "too short"  (cover, title page, part dividers)
    2. untitled page before the first entry
       of the table of contents             -> not read, "front matter" (title page, half title ...)
    3. title says it is not story text      -> not read, e.g. "notes"  (contents, notes, index, copyright ...)
    4. text says "All rights reserved"      -> not read, "copyright"  (copyright pages named after the publisher)
    5. title says it is extra story text    -> read,     e.g. "afterword" (preface, introduction, epilogue ...)
    6. title starts with a chapter number   -> read,     "chapter"   ("1. 1953", "One. OIL DROPS", "Chapter 2 ...")
    7. file name looks like a chapter       -> read,     "chapter"   (the rule the original audiblez used)
    8. anything else                        -> not read, "not recognised"
    The "title" is the page's entry in the table of contents. A page without any (not even a previous
    one it continues) is judged by its first line instead, so a page that starts with "CONTENTS" is
    recognised as the contents.
    If nothing at all ends up being read, every "not recognised" file is read instead
    (the original audiblez did something similar; known non-story pages stay unticked).

    Steps 3 and 5 only look at the START of the title, so "Notes" or "Praise for Sapiens"
    match, but a chapter called "In Praise of Idleness" does not.
"""
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from audiblez.spoken_headings import numbered_title


@dataclass
class BookSection:
    """One file of the book, as shown in one row of the GUI's chapter list."""
    chapter: object  # the ebooklib document; it carries .extracted_text, .title, .chapter_index
    display_title: str
    is_included: bool
    reason: str
    is_short: bool

    @property
    def file_name(self):
        return self.chapter.get_name()

    @property
    def text_length(self):
        return len(self.chapter.extracted_text)


class SectionClassifier:
    """Turns the extracted chapters into BookSections, deciding for each one whether it is read aloud."""

    MINIMUM_CHARACTERS = 100
    LONGEST_COPYRIGHT_PAGE = 10_000  # characters; a longer page that says "All rights reserved" is not a copyright page

    # Titles that START with one of these are not part of the story (step 2).
    NOT_STORY_TITLE = re.compile(
        r"^(contents|table of contents|copyright|index|notes|endnotes|footnotes|acknowledge?ments"
        r"|praise|about the authors?|about the publisher|also by|other books by|(?:selected )?bibliography|references"
        r"|further reading|permissions|illustration credits|picture credits|cover|title page|dedication|colophon"
        r"|the project gutenberg|the full project gutenberg)\b",
        re.IGNORECASE)

    # Titles that START with one of these are real text, even though they are not numbered chapters (step 3).
    STORY_EXTRA_TITLE = re.compile(
        r"^(afterword|foreword|preface|prologue|epilogue|introduction|conclusion|postscript"
        r"|a note on|author['’]s note)\b",
        re.IGNORECASE)

    # File names that look like chapters (step 4). Same patterns as the original audiblez.
    CHAPTER_FILE_NAME = re.compile(r"chapter|part_?\d{1,3}|split_?\d{1,3}|ch_?\d{1,3}|chap_?\d{1,3}", re.IGNORECASE)

    def describe(self, chapters):
        """Return one BookSection per chapter, in book order."""
        sections = []
        book_has_table_of_contents = any(getattr(chapter, "title", "") for chapter in chapters)
        for chapter in chapters:
            # Before the first table-of-contents entry, a page has no title at all (step 2)
            is_front_matter = book_has_table_of_contents and not getattr(chapter, "title", "")
            is_included, reason = self._decide(chapter, is_front_matter)
            sections.append(BookSection(
                chapter=chapter,
                display_title=self._display_title(chapter),
                is_included=is_included,
                reason=reason,
                is_short=len(chapter.extracted_text) <= self.MINIMUM_CHARACTERS))
        self._fall_back_to_everything_if_nothing_is_included(sections)
        return sections

    # ---- the decision ------------------------------------------------------------------------

    def _decide(self, chapter, is_front_matter=False):
        """Returns (is_included, reason). Follows the numbered steps in the module description."""
        text = chapter.extracted_text
        title = (getattr(chapter, "title", "") or "").strip() or text.split("\n", 1)[0].rstrip(".").strip()
        if len(text) <= self.MINIMUM_CHARACTERS:
            return False, "too short"
        if is_front_matter:
            return False, "front matter"
        if match := self.NOT_STORY_TITLE.match(title):
            return False, match.group(1).lower()
        if len(text) < self.LONGEST_COPYRIGHT_PAGE and "all rights reserved" in text.lower():
            return False, "copyright"
        if match := self.STORY_EXTRA_TITLE.match(title):
            return True, match.group(1).lower()
        if numbered_title(title):
            return True, "chapter"
        if self.CHAPTER_FILE_NAME.search(chapter.get_name()):
            return True, "chapter"
        return False, "not recognised"

    def _fall_back_to_everything_if_nothing_is_included(self, sections):
        """Used when no file name looks like a chapter: read every file that was merely "not recognised"
        (files we KNOW are not story text, such as copyright or license pages, stay unticked)."""
        if any(section.is_included for section in sections):
            return
        print('Not easy to recognize the chapters, defaulting to all non-empty documents.')
        for section in sections:
            if section.reason == "not recognised":
                section.is_included = True
                section.reason = "no chapters recognised"

    # ---- the name shown to the user ----------------------------------------------------------

    def _display_title(self, chapter):
        """
        The best human name for a file:
          1. its own entry in the table of contents      "1. An Animal of No Significance"
          2. the previous entry, marked as continued      "12. The Law of Religion (continued)"
          3. the first line of its text                   for books without a table of contents
          4. the file name                                when everything else is empty
        """
        toc_title = (getattr(chapter, "title", "") or "").strip()
        if toc_title and not getattr(chapter, "title_is_inherited", False):
            return toc_title
        if toc_title:
            return f"{toc_title} (continued)"
        first_line = chapter.extracted_text.split("\n", 1)[0].rstrip(".").strip()
        if first_line:
            return first_line[:60]
        return PurePosixPath(chapter.get_name()).stem


def find_good_chapters(document_chapters):
    """The chapters that are read aloud by default (used by the command line)."""
    return [section.chapter for section in SectionClassifier().describe(document_chapters) if section.is_included]
