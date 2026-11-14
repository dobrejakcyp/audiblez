"""
spoken_headings.py - makes the listener HEAR where a part or chapter begins.

A printed book shows a new chapter with big type, white space and a new page. In an audiobook
all of that disappears, and the heading lines read like random words ("One. OIL DROPS. The first
thing..."). This module gives every chapter one clear spoken heading instead:

    printed (first lines of the chapter)        spoken
    "One." / "OIL DROPS."                       "Chapter One. OIL DROPS."
    "CHAPTER ONE." / "ADA, COUNTESS ..."        "Chapter 1. Ada, Countess of Lovelace."
    "1. Eight Billion Minds."                   "Chapter 1. Eight Billion Minds."
    "Introduction." / "WICKED PROBLEMS."        "Introduction. WICKED PROBLEMS."

A part page ("Part 1", "PART ONE", "Part I: Cold War Chips") is so short that it is never read on
its own, so its name is spoken at the start of the next chapter: "Part 1. Chapter One. OIL DROPS."

HOW IT WORKS (add_spoken_headings, once per book, after the chapters got their titles)
    1. A short page whose title says "Part ..." / "Book ..." is remembered as the next part heading.
    2. A chapter with its OWN entry in the table of contents gets a heading made from that entry
       (spoken_heading). A file that only continues the previous chapter gets nothing.
    3. The printed heading lines at the very start of the chapter are removed, but only lines that
       are part of the heading (same words; "One", "1" and "I" count as the same number).
       So "POETICAL SCIENCE." under "ADA, COUNTESS OF LOVELACE." stays: it is not in the title.
    4. The part heading (if any) and the chapter heading become the first lines of the text.
       They show up in the window's text column, so you can see and edit them.
"""
import re

from audiblez.cleaning_rules import QuotationMarkEdit

NUMBER_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
                "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
                "nineteen", "twenty"]
TENS_WORDS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60}
ROMAN_NUMERAL = re.compile(r"^(?=[ivxlc])c{0,3}(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$", re.IGNORECASE)

# One number as chapters are numbered: 7, VII, seven, twenty-one
NUMBER = (r"(?:\d{1,3}|[ivxlc]{1,7}|(?:twenty|thirty|forty|fifty|sixty)(?:[- ](?:one|two|three|four|five|six"
          r"|seven|eight|nine))?|" + "|".join(NUMBER_WORDS[1:]) + r")")
SEPARATOR = r"(?P<separator>\s*[.:)\-–—]\s*|\s+|$)"
# A title that starts with a chapter number: "1. 1953", "One. OIL DROPS", "Chapter 1: ...", "CHAPTER 2 The Computer"
NUMBERED_TITLE = re.compile(rf"^(?P<word>chapter\s+)?(?P<number>{NUMBER}){SEPARATOR}(?P<rest>.*)$", re.IGNORECASE)
# A part page: "Part 1", "PART ONE", "Part I: Cold War Chips", "Book Two"
PART_TITLE = re.compile(rf"^(?P<word>part|book)\s+(?P<number>{NUMBER}){SEPARATOR}(?P<rest>.*)$", re.IGNORECASE)
SPOKEN_HEADING = "spoken heading"  # the kind of the added heading lines (the window colours them)
LONGEST_HEADING_LINE = 90  # characters; a longer first line is real text, never a heading
MOST_HEADING_LINES = 4


def numbered_title(title):
    """
    The match of NUMBERED_TITLE, or None when the "number" is really a word. The regular expression
    alone would also accept "Civil War" (only Roman-numeral letters) or "One Day in May", so:
      - the number must really be a number (digits, a number word or a valid Roman numeral), and
      - a number followed by just a space counts only after "Chapter" or when it is written in digits.
    """
    return checked_number_match(NUMBERED_TITLE.match(title.strip()))


def part_title(title):
    """Like numbered_title(), for part pages: "Part 1", "PART ONE", "Part I: Cold War Chips"."""
    return checked_number_match(PART_TITLE.match(title.strip()))


def checked_number_match(match):
    if not match:
        return None
    number = match["number"]
    if number_as_digits(number) == number and not number.isdigit():
        return None  # "civil", "mix": letters that look like a Roman numeral but are not one
    if not match["word"] and not match["separator"].strip() and match["rest"] and not number.isdigit():
        return None  # "One Day in May", "I Was Born": a word starting a title, not a chapter number
    return match


def number_as_digits(number_text):
    """"One" -> "1", "VII" -> "7", "twenty-one" -> "21", "12" -> "12". Anything else is returned unchanged."""
    word = number_text.lower().replace(" ", "-")
    if word.isdigit():
        return str(int(word))
    if word in NUMBER_WORDS:
        return str(NUMBER_WORDS.index(word))
    tens, _, ones = word.partition("-")
    if tens in TENS_WORDS and (not ones or ones in NUMBER_WORDS[1:10]):
        return str(TENS_WORDS[tens] + (NUMBER_WORDS.index(ones) if ones else 0))
    if ROMAN_NUMERAL.match(word):
        return str(roman_to_int(word))
    return number_text


def roman_to_int(roman):
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
    total = 0
    for letter, next_letter in zip(roman.lower(), roman.lower()[1:] + " "):
        value = values[letter]
        total += -value if values.get(next_letter, 0) > value else value
    return total


def spoken_number(number_text):
    """Roman numerals become digits (the voice would say "eye vee"); words and digits are kept as printed."""
    return number_as_digits(number_text) if ROMAN_NUMERAL.match(number_text) else number_text


def spoken_heading(title):
    """
    The heading to speak for a table-of-contents title, always ending with a period:
        "One. OIL DROPS"          -> "Chapter One. OIL DROPS."
        "1: Introduction"         -> "Chapter 1. Introduction."
        "CHAPTER 2 The Computer"  -> "Chapter 2. The Computer."
        "Part I: Cold War Chips"  -> "Part 1. Cold War Chips."
        "Introduction"            -> "Introduction."
    """
    title = " ".join(QuotationMarkEdit().apply(title).split())  # the same as in the book's text
    if part := part_title(title):
        heading = f"{part['word'].strip().capitalize()} {spoken_number(part['number'])}"
        rest = part["rest"]
    elif numbered := numbered_title(title):
        heading = f"Chapter {spoken_number(numbered['number'])}"
        rest = numbered["rest"]
    else:
        heading, rest = title, ""
    return " ".join(with_period(piece) for piece in (heading, rest) if piece.strip())


def with_period(text):
    text = text.strip()
    return text if text.endswith((".", "!", "?", "…")) else text + "."


def comparable_words(text):
    """Lowercase words with every number written as digits, for comparing a printed line with a title."""
    words = re.findall(r"[^\W_]+", text.lower())
    return " ".join(number_as_digits(word) for word in words)


def is_part_page(chapter, short_page_characters):
    title = chapter.title if not getattr(chapter, "title_is_inherited", False) else ""
    first_line = chapter.extracted_text.split("\n", 1)[0]
    return (len(chapter.extracted_text) <= short_page_characters
            and bool(part_title(title) or part_title(first_line)))


def add_spoken_headings(chapters, short_page_characters):
    """
    Give every chapter that has its own table-of-contents entry one spoken heading (see the top of
    this module). `short_page_characters`: a page this short is never read on its own (a part page).
    Changes chapter.extracted_text and keeps chapter.line_kinds in step with its lines.
    """
    waiting_part_heading = ""
    for chapter in chapters:
        if is_part_page(chapter, short_page_characters):
            title = chapter.title if not getattr(chapter, "title_is_inherited", False) else ""
            waiting_part_heading = spoken_heading(title or chapter.extracted_text.split("\n", 1)[0])
            continue
        has_own_title = bool(chapter.title) and not getattr(chapter, "title_is_inherited", False)
        if not has_own_title or len(chapter.extracted_text) <= short_page_characters:
            continue
        heading = spoken_heading(chapter.title)
        new_lines = [line for line in (waiting_part_heading, heading) if line]
        waiting_part_heading = ""
        replace_printed_heading(chapter, heading, new_lines)


def replace_printed_heading(chapter, heading, new_lines):
    """Drop the printed heading lines at the start of the chapter and put `new_lines` there instead."""
    lines = chapter.extracted_text.split("\n")[:-1]  # the text ends with a newline
    kinds = list(getattr(chapter, "line_kinds", None) or [])
    heading_words = f" {comparable_words(heading)} "
    printed_heading_lines = 0
    for line in lines[:MOST_HEADING_LINES]:
        words = comparable_words(line)
        if not words or len(line) > LONGEST_HEADING_LINE or f" {words} " not in heading_words:
            break
        printed_heading_lines += 1
    chapter.extracted_text = "".join(line + "\n" for line in new_lines + lines[printed_heading_lines:])
    if len(kinds) == len(lines):  # keep one kind per line (used for the colours in the window)
        chapter.line_kinds = [(SPOKEN_HEADING, ())] * len(new_lines) + kinds[printed_heading_lines:]
    else:  # they did not match before, so any colours would land on the wrong lines: show none
        chapter.line_kinds = []
