"""
spoken_blocks.py - where the voice should pause longer than between two sentences.

A narrator pauses before and after a heading, so the listener hears that a new part begins.
Kokoro has no setting for that: it only reads sentences. So core.py speaks a chapter in BLOCKS
and puts real silence (a stretch of zeros in the audio) after each block that needs it:

    "...names like Altair and Apple."         block 1, then 0.7 s silence
    "THE CULTURAL BREW."                      block 2 (a subheading), then 0.7 s silence
    "The personal computer was made ..."      block 3, the rest of the text

Which lines are headings comes from chapter.line_kinds (see epub_text_extractor.py and
spoken_headings.py). When the text was edited by hand and the kinds no longer match its lines,
the chapter is spoken as one block, without the extra pauses, exactly as before.
"""
from dataclasses import dataclass

from audiblez.epub_text_extractor import HEADING_TAGS, SUBHEADING
from audiblez.spoken_headings import SPOKEN_HEADING

PAUSE_AROUND_HEADING = 0.7  # seconds of silence before and after a heading
HEADING_KINDS = {SPOKEN_HEADING, SUBHEADING, *HEADING_TAGS}


@dataclass
class SpokenBlock:
    text: str
    pause_after: float = 0.0  # seconds of silence after it


def spoken_blocks(text, line_kinds):
    """Split a chapter's text into SpokenBlocks: every heading on its own, with a pause around it."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # the text ends with a newline
    if not line_kinds or len(line_kinds) != len(lines):
        return [SpokenBlock(text)]
    blocks, waiting_lines = [], []

    def finish_waiting_lines(pause_after):
        if waiting_lines:
            blocks.append(SpokenBlock("\n".join(waiting_lines) + "\n", pause_after))
            waiting_lines.clear()

    for line, (tag, _classes) in zip(lines, line_kinds):
        if tag in HEADING_KINDS:
            finish_waiting_lines(pause_after=PAUSE_AROUND_HEADING)  # the pause BEFORE the heading
            blocks.append(SpokenBlock(line + "\n", PAUSE_AROUND_HEADING))  # ...and after it
        else:
            waiting_lines.append(line)
    finish_waiting_lines(pause_after=0.0)
    return blocks
