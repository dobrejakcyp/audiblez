"""
book_search.py - finds a piece of text anywhere in the book (the search box above the text column).

    find_in_book(sections, "transistor")    every place it occurs, in book order
    next_match(matches, sections, here, forward=True)
                                            the match to jump to from the place you are now

The search ignores upper/lower case and looks at the text exactly as it will be read aloud
(including your own edits), in every section, ticked or not. It is redone on every jump, which
takes a few milliseconds even for a long book, so it can never point at text that was edited away.
"""
from dataclasses import dataclass


@dataclass
class SearchMatch:
    section: object  # a BookSection (chapter_selection.py)
    start: int  # position in the section's text
    end: int


def find_in_book(sections, query):
    query = query.strip().casefold()
    if not query:
        return []
    matches = []
    for section in sections:
        text = section.chapter.extracted_text.casefold()
        start = text.find(query)
        while start != -1:
            matches.append(SearchMatch(section, start, start + len(query)))
            start = text.find(query, start + 1)
    return matches


def next_match(matches, sections, here, forward=True):
    """
    The index (into `matches`) of the match after - or before - `here`, going round at the end.
    `here` is (section, position): the section shown now and where the cursor or selection starts.
    Returns None when there are no matches.
    """
    if not matches:
        return None
    order = {id(section): number for number, section in enumerate(sections)}
    here_section, here_position = here
    here_key = (order.get(id(here_section), -1), here_position)
    keys = [(order[id(match.section)], match.start) for match in matches]
    if forward:
        later = [index for index, key in enumerate(keys) if key > here_key]
        return later[0] if later else 0
    earlier = [index for index, key in enumerate(keys) if key < here_key]
    return earlier[-1] if earlier else len(matches) - 1
