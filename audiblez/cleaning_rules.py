"""
cleaning_rules.py - decides WHICH PARTS of a book are NOT read aloud.

THE BIG PICTURE
    An EPUB chapter is a small web page (HTML). Before the text goes to the voice model,
    we walk through every element of that page (<p>, <sup>, <nav>, ...) and ask a list
    of rules: "Do you want this element removed?"

    The FIRST rule that says yes wins. The element, and everything inside it, is deleted
    and the cleaning report gives that rule the credit. Whatever survives is read aloud.

    Besides removing whole elements, there are also small TEXT EDITS (see the bottom half
    of this file) that fix up text which is kept, e.g. deleting "(see fig. 3)".

HOW TO ADD YOUR OWN RULE
    1. Write a class that inherits from RemovalRule (or LabelOrClassRule for the usual case).
    2. Give it a `name` and a `reason`. Both are shown in the cleaning report.
    3. Fill in the few attributes (or implement `matches`) that say what to remove.
    4. Add it to `default_removal_rules()` near the bottom of this file.
    5. Add a case for it to test_cleaning_rules.py so it can never silently break.
"""
import re


# =============================================================================================
# Small helpers used by several rules
# =============================================================================================

# Tags that only style a few words INSIDE a sentence. Rules that guess from CSS class names
# never remove these, so we cannot accidentally cut words out of the middle of a sentence.
INLINE_TAGS = {"span", "a", "em", "i", "b", "strong", "small", "sup", "sub", "u", "abbr", "cite", "code"}


def class_names_of(element):
    """CSS class names of an element: <p class="note small"> -> ["note", "small"]."""
    return element.get("class") or []


def meaning_labels_of(element):
    """
    The "meaning labels" a book author can attach to an element, for example
    epub:type="footnote" or role="doc-footnote". The "doc-" prefix is dropped,
    so both spellings give the same label: {"footnote"}.
    """
    labels = set()
    for attribute_name in ("epub:type", "role"):
        for label in (element.get(attribute_name) or "").split():
            labels.add(label.removeprefix("doc-"))
    return labels


# =============================================================================================
# Removal rules
# =============================================================================================

class RemovalRule:
    """Base class. A rule answers one question: should this element be removed?"""

    name = "unnamed rule"  # short label shown in the report
    reason = "(explain in plain words why this text should not be read aloud)"

    def matches(self, element):
        """Return True if `element` must be removed (together with everything inside it)."""
        raise NotImplementedError


class LabelOrClassRule(RemovalRule):
    """
    The usual kind of rule. An element is removed when ANY of these is true:
      - its HTML tag is in `tag_names`                      (e.g. <nav>)
      - the author gave it a meaning label from `labels`    (e.g. epub:type="footnote")
      - one of its CSS class names fully matches `class_pattern`
        (only for block elements, see INLINE_TAGS above)
    """

    tag_names = set()
    labels = set()
    class_pattern = None  # a compiled regular expression, or None

    def matches(self, element):
        if element.name in self.tag_names:
            return True
        if self.labels & meaning_labels_of(element):
            return True
        if self.class_pattern is None or element.name in INLINE_TAGS:
            return False
        return any(self.class_pattern.fullmatch(name) for name in class_names_of(element))


class CaptionRule(LabelOrClassRule):
    name = "picture captions"
    reason = "A caption describes a picture the listener cannot see, and interrupts the story."
    tag_names = {"figcaption"}
    # Matches: caption, captions, cap, figcap, fig-caption, image_caption, photo-caption ...
    # Does NOT match "caps" (small capitals) or "dropcap" (decorative first letter).
    class_pattern = re.compile(r"(?:fig|img|image|photo)?[-_]?(?:cap|captions?)", re.IGNORECASE)


class NavigationRule(LabelOrClassRule):
    name = "navigation lists"
    reason = "Table of contents and page lists are for tapping around, not for listening."
    tag_names = {"nav"}
    labels = {"toc", "landmarks", "page-list", "lot", "lof"}


class PageBreakRule(LabelOrClassRule):
    name = "page-number markers"
    reason = "Markers like <span epub:type='pagebreak'>45</span> would inject a page number into a sentence."
    labels = {"pagebreak"}


class IndexRule(LabelOrClassRule):
    name = "back-of-book index"
    reason = "An alphabetical list of terms and page numbers is meaningless when listened to."
    labels = {"index"}
    class_pattern = re.compile(r"index.*", re.IGNORECASE)  # index, indexmain, index_sub ...


class NoteBodyRule(LabelOrClassRule):
    name = "footnote / endnote text"
    reason = "Notes interrupt the sentence the listener is following. Remove them, or move them elsewhere."
    labels = {"footnote", "footnotes", "endnote", "endnotes", "rearnote", "rearnotes"}
    class_pattern = re.compile(r"(?:foot|end|rear)?notes?", re.IGNORECASE)  # note, footnote, endnotes ...


class NoteMarkerRule(RemovalRule):
    """
    The tiny raised number (or symbol) in the text that points to a note: "...in 1492.¹"
    Read aloud, it becomes a stray "one" glued to the end of the sentence.

    Careful: a plain exponent like 2<sup>4</sup> is NOT a note marker, so we only remove
    markers that are links, or that the author labelled epub:type="noteref".
    """

    name = "note markers"
    reason = "A raised note number read aloud becomes a stray number glued to a sentence."
    # Text that looks like a note marker: 12, [12], (12), *, †, ‡ ...
    MARKER_TEXT = re.compile(r"[\[(]?\s*(?:\d{1,3}|[*†‡§¶#]+)\s*[\])]?")

    def matches(self, element):
        if "noteref" in meaning_labels_of(element):
            return True
        is_link = element.name == "a" and element.get("href")
        is_raised_link = element.name == "sup" and element.find("a", href=True)
        if is_link or is_raised_link:
            return bool(self.MARKER_TEXT.fullmatch(element.get_text().strip()))
        return False


class UserChosenClassRule(RemovalRule):
    """
    Removes every element that has one of the CSS class names YOU passed with --drop-class.
    This is the tool for book-specific leftovers: run with --report, look at the "most common
    kept elements" table, and pass the class names of anything that should not be read.
    Unlike the other class-based rules this one also applies to inline elements (<span>),
    because you asked for it explicitly.
    """

    def __init__(self, class_names):
        self.class_names = set(class_names)
        self.name = "your --drop-class choices: " + ", ".join(sorted(self.class_names))
        self.reason = "You asked for these CSS classes to be removed."

    def matches(self, element):
        return any(name in self.class_names for name in class_names_of(element))


def default_removal_rules(extra_class_names=()):
    """
    The rules used for normal conversions, in the order they are asked.
    The order only matters for the report: when two rules match the same element,
    the earlier one gets the credit.
    """
    rules = [CaptionRule(), NavigationRule(), PageBreakRule(), IndexRule(), NoteBodyRule(), NoteMarkerRule()]
    if extra_class_names:
        rules.append(UserChosenClassRule(extra_class_names))
    return rules


# =============================================================================================
# Text edits (applied to text that is KEPT; they never remove a whole element)
# =============================================================================================

class TextEdit:
    """Base class. A text edit receives one line of text and returns the fixed-up line."""

    name = "unnamed text edit"

    def apply(self, text):
        raise NotImplementedError


class FigureReferenceEdit(TextEdit):
    """Deletes "(fig. 20)", "(see fig. 5)", "(detail of fig. 19)", "(figs. 63, 64)", "(Figure 3)"."""

    name = "figure references like (fig. 3)"
    PATTERN = re.compile(
        r"\s*\((?:see\s+(?:also\s+)?|detail\s+of\s+|cf\.\s*)?(?:figs?\.|figures?)\s*\d+[^()]*\)", re.IGNORECASE)

    def apply(self, text):
        return self.PATTERN.sub("", text)


class DecorativeSymbolEdit(TextEdit):
    """
    Deletes decorative note markers and section-break symbols such as the black diamond
    that some EPUBs put after endnote links. The symbols  •  †  ‡  are kept on purpose,
    because they can carry meaning.
    """

    name = "decorative symbols"
    PATTERN = re.compile("[♦◆◇❖■□⁂✦✧❧☙]")

    def apply(self, text):
        return self.PATTERN.sub("", text)


def default_text_edits():
    """The text edits used for normal conversions, applied in this order."""
    return [FigureReferenceEdit(), DecorativeSymbolEdit()]
