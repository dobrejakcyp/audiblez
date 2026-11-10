"""
epub_text_extractor.py - turns EPUB chapters into the clean text that is read aloud.

Two classes live here:

    EpubTextExtractor   does the work: removes unwanted elements, collects the readable text.
    CleaningReport      keeps score: what was removed, by which rule, and what was kept.

The rules themselves (WHAT to remove) live in cleaning_rules.py.
This file only knows HOW to apply them.
"""
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from urllib.parse import unquote

import ebooklib
from bs4 import BeautifulSoup, Comment, NavigableString

from audiblez.cleaning_rules import default_removal_rules, default_text_edits


# =============================================================================================
# The report
# =============================================================================================

@dataclass
class RemovedElements:
    """Score card of ONE removal rule."""
    element_count: int = 0
    characters: int = 0
    samples: list = field(default_factory=list)  # a few examples of what was removed


@dataclass
class KeptElements:
    """Score card of ONE kind of element that survived (e.g. all <p class="indent">)."""
    element_count: int = 0
    characters: int = 0
    first_example: str = ""


class CleaningReport:
    """Collects statistics while the extractor works, and prints them in a readable way."""

    # Rough speech speed, measured on your own Sapiens audiobook (915,000 characters = 16.7 hours).
    # Only used to turn "characters" into "minutes of audio" for the report.
    CHARACTERS_PER_AUDIO_MINUTE = 900
    SAMPLES_PER_RULE = 3
    SAMPLE_LENGTH = 70

    def __init__(self):
        self.removed_by_rule = {}  # rule name -> RemovedElements
        self.characters_removed_by_text_edit = {}  # text edit name -> number of characters
        self.kept_by_kind = {}  # (tag, css class) -> KeptElements
        self.kept_characters = 0

    @classmethod
    def combine(cls, reports):
        """Add several reports together, e.g. the reports of all chapters that will be converted."""
        combined = cls()
        for report in reports:
            for rule_name, other in report.removed_by_rule.items():
                total = combined.removed_by_rule.setdefault(rule_name, RemovedElements())
                total.element_count += other.element_count
                total.characters += other.characters
                total.samples = (total.samples + other.samples)[:cls.SAMPLES_PER_RULE]
            for edit_name, characters in report.characters_removed_by_text_edit.items():
                combined.characters_removed_by_text_edit[edit_name] = (
                    combined.characters_removed_by_text_edit.get(edit_name, 0) + characters)
            for kind, other in report.kept_by_kind.items():
                total = combined.kept_by_kind.setdefault(kind, KeptElements(first_example=other.first_example))
                total.element_count += other.element_count
                total.characters += other.characters
            combined.kept_characters += report.kept_characters
        return combined

    # ---- recording (called by the extractor) ----------------------------------------------

    def record_removed_element(self, rule, element):
        text = " ".join(element.get_text().split())  # one line, single spaces
        score_card = self.removed_by_rule.setdefault(rule.name, RemovedElements())
        score_card.element_count += 1
        score_card.characters += len(text)
        if text and len(score_card.samples) < self.SAMPLES_PER_RULE:
            score_card.samples.append(text[:self.SAMPLE_LENGTH])

    def record_text_edit(self, text_edit, characters_removed):
        if characters_removed:
            total = self.characters_removed_by_text_edit.get(text_edit.name, 0)
            self.characters_removed_by_text_edit[text_edit.name] = total + characters_removed

    def record_kept_line(self, element, line):
        self.kept_characters += len(line)
        for css_class in element.get("class") or ["(no class)"]:
            score_card = self.kept_by_kind.setdefault((element.name, css_class), KeptElements())
            score_card.element_count += 1
            score_card.characters += len(line)
            if not score_card.first_example:
                score_card.first_example = line[:self.SAMPLE_LENGTH]

    # ---- printing --------------------------------------------------------------------------

    def print_removals(self, show_samples):
        """What was taken out of the book, rule by rule."""
        print("\nCleaning report: what was NOT read aloud")
        if not self.removed_by_rule and not self.characters_removed_by_text_edit:
            print("  (nothing was removed)")
        for rule_name, score_card in self.removed_by_rule.items():
            minutes = score_card.characters / self.CHARACTERS_PER_AUDIO_MINUTE
            print(f"  {rule_name}: {score_card.element_count:,} elements, "
                  f"{score_card.characters:,} characters (about {minutes:.0f} min of audio)")
            if show_samples:
                for sample in score_card.samples:
                    print(f'      e.g. "{sample}"')
        for edit_name, characters in self.characters_removed_by_text_edit.items():
            print(f"  text edit - {edit_name}: {characters:,} characters")
        hours = self.kept_characters / self.CHARACTERS_PER_AUDIO_MINUTE / 60
        print(f"  KEPT and read aloud: {self.kept_characters:,} characters (about {hours:.1f} hours)")

    def print_most_common_kept_elements(self, how_many=15):
        """
        The kinds of element that SURVIVED, most common first. This is where leftovers hide:
        if a kind looks like a note, caption or index entry, pass its class name to --drop-class.
        """
        print(f"\nMost common kept elements (top {how_many}) - look here for leftovers to remove")
        by_count = sorted(self.kept_by_kind.items(), key=lambda item: -item[1].element_count)
        for (tag, css_class), score_card in by_count[:how_many]:
            average = score_card.characters // score_card.element_count
            print(f"  {tag}.{css_class}  x{score_card.element_count:,}  avg {average} chars  "
                  f'e.g. "{score_card.first_example}"')


# =============================================================================================
# The extractor
# =============================================================================================

class EpubTextExtractor:
    """
    Reads the chapters of an EPUB book and produces the text that will be read aloud.

        extractor = EpubTextExtractor.with_default_rules()
        chapters = extractor.extract_chapters(book)   # book comes from ebooklib's epub.read_epub()
        extractor.report.print_removals(show_samples=True)
    """

    # Only the text inside these tags is read aloud (same list as the original audiblez).
    TEXT_BLOCK_TAGS = ("title", "p", "h1", "h2", "h3", "h4", "li")

    def __init__(self, removal_rules, text_edits, report=None):
        self.removal_rules = removal_rules
        self.text_edits = text_edits
        self.report = report or CleaningReport()

    @classmethod
    def with_default_rules(cls, extra_class_names=()):
        """The normal setup. `extra_class_names` are the CSS classes from --drop-class."""
        return cls(default_removal_rules(extra_class_names), default_text_edits())

    # ---- public: whole book ------------------------------------------------------------------

    def extract_chapters(self, book, on_progress=None):
        """
        Returns every page of the book that is a document, each one enriched with:
            chapter.extracted_text   the clean text to read aloud
            chapter.line_kinds       per line of that text: (tag, css classes) it came from (used for highlighting)
            chapter.cleaning_report  what the cleaning removed from THIS chapter
            chapter.title            the name from the table of contents
            chapter.chapter_index    its position (the rest of audiblez relies on these names)
        After the call, self.report holds the combined report of all chapters.
        `on_progress(files_done, files_total)` is called after each file (the GUI shows it in its status bar).
        """
        documents = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT]
        chapters = []
        for item in documents:
            if on_progress:
                on_progress(len(chapters) + 1, len(documents))
            item.cleaning_report = CleaningReport()
            item.line_kinds = []  # for each line of text: (tag, css classes) of the element it came from
            item.extracted_text = self.extract_text_from_html(item.get_body_content(), item.cleaning_report,
                                                               item.line_kinds)
            chapters.append(item)
        for position, chapter in enumerate(chapters):
            chapter.chapter_index = position
        self._assign_titles_from_table_of_contents(book, chapters)
        self.report = CleaningReport.combine(chapter.cleaning_report for chapter in chapters)
        return chapters

    # ---- public: one page --------------------------------------------------------------------

    def extract_text_from_html(self, html, report=None, line_kinds=None):
        """
        Clean ONE page of HTML and return the text to read aloud, one line per paragraph.
        Statistics go into `report` (default: self.report). If a list is given as `line_kinds`,
        the (tag, css classes) of every kept line is appended to it, in the same order as the lines.
        """
        report = report or self.report
        page = BeautifulSoup(html, features="lxml")
        self._remove_unwanted_elements(page, report)
        readable_text = ""
        for block in page.find_all(self.TEXT_BLOCK_TAGS):
            line = self._make_speakable_line(self._text_of_block_itself(block), report)
            if line:
                report.record_kept_line(block, line)
                readable_text += line + "\n"
                if line_kinds is not None:
                    line_kinds.append((block.name, tuple(block.get("class") or ())))
        return readable_text

    # ---- step 1: remove elements -------------------------------------------------------------

    def _remove_unwanted_elements(self, page, report):
        # find_all lists parents BEFORE their children, so when a parent is removed its
        # children are already gone by the time we reach them (and are skipped here).
        for element in page.find_all(True):
            if element.decomposed:
                continue
            matching_rule = self._first_rule_that_matches(element)
            if matching_rule:
                report.record_removed_element(matching_rule, element)
                element.decompose()

    def _first_rule_that_matches(self, element):
        for rule in self.removal_rules:
            if rule.matches(element):
                return rule
        return None

    # ---- step 2: collect the text ------------------------------------------------------------

    def _text_of_block_itself(self, block):
        """
        The text of a block WITHOUT the text of blocks nested inside it.
        Example: <li>Fruit<ul><li>Apple</li></ul></li> gives "Fruit" for the outer item and
        "Apple" for the inner one. (The original audiblez gave "FruitApple" AND "Apple",
        so nested text was read twice.)
        """
        pieces = []
        for child in block.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                pieces.append(str(child))
            elif child.name in self.TEXT_BLOCK_TAGS:
                continue  # a nested block: it will be read on its own turn
            else:
                pieces.append(self._text_of_block_itself(child))  # inline piece such as <em> or <span>
        return "".join(pieces)

    def _make_speakable_line(self, text, report):
        """Apply the text edits; return "" when nothing speakable is left, else a line ending in a period."""
        for text_edit in self.text_edits:
            edited_text = text_edit.apply(text)
            report.record_text_edit(text_edit, len(text) - len(edited_text))
            text = edited_text
        text = text.strip()
        if not any(character.isalnum() for character in text):  # e.g. a lone "* * *"
            return ""
        if not text.endswith("."):
            text += "."  # gives the voice a pause at the end of headings and list items
        return text

    # ---- chapter titles ----------------------------------------------------------------------

    def _assign_titles_from_table_of_contents(self, book, chapters):
        """
        Names each chapter from the book's table of contents. A page without its own entry
        continues the previous one (e.g. a chapter's title page is in the table of contents,
        its text is in the next file).
        """
        titles_by_file_name = {}

        def collect(entries):
            for entry in entries:
                if isinstance(entry, tuple):  # (section, list of sub-entries)
                    collect([entry[0]])
                    collect(entry[1])
                    continue
                href = unquote((getattr(entry, "href", "") or "").split("#")[0])
                if href and entry.title:
                    titles_by_file_name.setdefault(PurePosixPath(href).name, entry.title.strip())

        collect(book.toc)
        current_title = ""
        for chapter in chapters:
            own_title = titles_by_file_name.get(PurePosixPath(chapter.get_name()).name)
            chapter.title_is_inherited = own_title is None  # True: no own entry, title copied from previous file
            if own_title is not None:
                current_title = own_title
            chapter.title = current_title
