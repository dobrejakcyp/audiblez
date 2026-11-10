"""
picture_text_detector.py - finds text that belongs to PICTURES (captions, photo credits).

WHY THIS IS NEEDED
    Many EPUBs mark captions only with a CSS class the publisher invented. Sapiens, for example,
    uses <p class="capl0"> for captions and <p class="credit"> for photo credits, with no standard
    label such as <figcaption>. A fixed rule cannot know those names in advance, but their POSITION
    gives them away: they always sit right next to a picture.

HOW IT WORKS
    1. For every picture (<img>) we collect the text blocks around it:
         - text inside the same box as the picture:    <div><img/><p>caption</p></div>
         - up to two text blocks right after it:       <div><img/></div> <p>caption</p> <p>© credit</p>
           (other pictures in between are skipped, because several pictures often share one caption)
         - the one text block right before it.
    2. For every KIND of block (tag + CSS class, e.g. <p class="capl0">) we count how many there
       are in the book and how many of those were next to a picture.
    3. A kind that is nearly always next to a picture is picture text. Normal story paragraphs
       (e.g. <p class="indent">) touch a picture now and then too, but only a share of them, so
       they are not reported. As a safety margin for books full of pictures (a technical book can
       have a diagram on every page), a kind that holds more than 10% of the book's text is never
       reported: captions and credits are always a small part of a book, the story never is.
    4. Each kind gets a name: "picture credits" (copyright signs, agency names, or "credit" in the
       class name), "short labels" (on average only a few characters, like "or" between two
       diagrams) or else "picture captions".

    Kinds that the default cleaning rules already remove (e.g. class "caption") are not reported.
    The result is only a suggestion: the GUI shows it, and YOU decide what gets removed.
"""
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from audiblez.cleaning_rules import default_removal_rules

TEXT_BLOCK_TAGS = ("p", "li", "h4", "h5", "h6")

# Words that photo credits typically contain ("© Getty Images", "Courtesy of ...", "Wikimedia Commons")
CREDIT_WORDS = re.compile(r"©|\b(getty|corbis|alamy|shutterstock|courtesy|wikimedia|public domain|"
                          r"photo(graph)? by|library of congress|bridgeman|akg-images|ullstein|"
                          r"granger|reuters|associated press|nasa)\b", re.IGNORECASE)
SHORT_LABEL_LENGTH = 15  # kinds shorter than this on average are labels, not captions


@dataclass
class PictureTextGroup:
    """One kind of element (e.g. <p class="capl0">) that was found next to pictures."""
    tag: str
    css_class: str
    total_count: int = 0  # how many of these are in the book
    near_picture_count: int = 0  # how many of them are next to a picture
    characters: int = 0
    samples: list = field(default_factory=list)
    example_element: object = None  # one element of this kind next to a picture (to check the default rules)

    @property
    def share_near_pictures(self):
        return self.near_picture_count / self.total_count if self.total_count else 0

    @property
    def average_length(self):
        return self.characters / self.total_count if self.total_count else 0

    @property
    def kind(self):
        """A human name for this kind of text (see step 4 in the module description)."""
        looks_like_credits = sum(bool(CREDIT_WORDS.search(sample)) for sample in self.samples) * 2 >= len(self.samples)
        if "credit" in self.css_class.lower() or (self.samples and looks_like_credits):
            return "picture credits"
        if self.average_length < SHORT_LABEL_LENGTH:
            return "short labels"
        return "picture captions"

    @property
    def label(self):
        return f"{self.kind}: {self.css_class} ({self.total_count}x)"


class PictureTextDetector:
    MINIMUM_SHARE_NEAR_PICTURES = 0.6  # at least 60% of this kind must sit next to a picture
    MINIMUM_COUNT = 2  # a kind seen only once is not a pattern
    MAXIMUM_SHARE_OF_BOOK_TEXT = 0.10  # the story itself is never picture text (see step 3)
    BLOCKS_AFTER_A_PICTURE = 2
    SAMPLES_PER_GROUP = 3
    SAMPLE_LENGTH = 90

    def __init__(self, rules_already_applied=None):
        self.rules_already_applied = rules_already_applied or default_removal_rules()

    def find_groups(self, chapters):
        """`chapters` are ebooklib documents (they have get_body_content()). Returns PictureTextGroups."""
        groups = {}  # (tag, css class) -> PictureTextGroup
        self.book_characters = 0
        for chapter in chapters:
            page = BeautifulSoup(chapter.get_body_content(), "lxml")
            near_pictures = self._text_blocks_near_pictures(page)
            for block in page.find_all(TEXT_BLOCK_TAGS):
                text = " ".join(block.get_text().split())
                css_classes = block.get("class") or []
                if not text or not css_classes:  # without a class name we could not target it anyway
                    continue
                group = groups.setdefault((block.name, css_classes[0]), PictureTextGroup(block.name, css_classes[0]))
                group.total_count += 1
                group.characters += len(text)
                self.book_characters += len(text)
                if id(block) in near_pictures:
                    group.near_picture_count += 1
                    if len(group.samples) < self.SAMPLES_PER_GROUP:
                        group.samples.append(text[:self.SAMPLE_LENGTH])
                    if group.example_element is None:
                        group.example_element = block
        return [group for group in groups.values() if self._is_picture_text(group)]

    # ---- step 1: which text blocks touch a picture? -------------------------------------------

    def _text_blocks_near_pictures(self, page):
        near = set()  # id() of every text block next to a picture
        for picture in page.find_all("img"):
            box = self._box_around(picture)
            near.update(id(block) for block in box.find_all(TEXT_BLOCK_TAGS))
            near.update(id(block) for block in self._text_blocks_after(box))
            before = self._text_block_before(box)
            if before is not None:
                near.add(id(before))
        return near

    @staticmethod
    def _box_around(picture):
        """The small container that holds the picture (e.g. <div class="full40">), or the picture itself."""
        parent = picture.parent
        return parent if parent is not None and parent.name in ("div", "figure", "p", "span", "a") else picture

    def _text_blocks_after(self, box):
        found = []
        for sibling in box.find_next_siblings():
            if sibling.find("img") is not None or sibling.name == "img":
                continue  # another picture of the same group
            if sibling.name in TEXT_BLOCK_TAGS:
                found.append(sibling)
                if len(found) == self.BLOCKS_AFTER_A_PICTURE:
                    break
            else:
                break  # something else (a heading, a section) ends the search
        return found

    @staticmethod
    def _text_block_before(box):
        for sibling in box.find_previous_siblings():
            if sibling.find("img") is not None or sibling.name == "img":
                continue
            return sibling if sibling.name in TEXT_BLOCK_TAGS else None
        return None

    # ---- step 3: is this kind picture text? ----------------------------------------------------

    def _is_picture_text(self, group):
        if group.near_picture_count < self.MINIMUM_COUNT:
            return False
        if group.share_near_pictures < self.MINIMUM_SHARE_NEAR_PICTURES:
            return False
        if group.characters > self.MAXIMUM_SHARE_OF_BOOK_TEXT * self.book_characters:
            return False  # too big a part of the book to be captions: it is the story itself
        return not self._already_removed(group.example_element)

    def _already_removed(self, element):
        """True if a default cleaning rule already removes this element (or a box around it)."""
        return any(rule.matches(candidate)
                   for candidate in [element, *element.parents] if candidate.name
                   for rule in self.rules_already_applied)
