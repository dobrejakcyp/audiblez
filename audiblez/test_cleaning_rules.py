"""
Self-check for the cleaning rules. Run from C:\\Users\\lukas\\audiblez with:

    venv\\Scripts\\python -m audiblez.test_cleaning_rules

Each case feeds a tiny hand-written page to the extractor and checks exactly what comes out.
When you add a rule to cleaning_rules.py, add a case here that shows it working.
"""
from audiblez.epub_text_extractor import EpubTextExtractor


def read_aloud(html, extra_class_names=()):
    """Run the default cleaning on a snippet of HTML. Returns (text, report)."""
    extractor = EpubTextExtractor.with_default_rules(extra_class_names)
    return extractor.extract_text_from_html(html), extractor.report


def test_navigation_list_is_removed():
    text, _ = read_aloud('<nav epub:type="toc"><ol><li>Chapter 1</li></ol></nav><p>Hello there.</p>')
    assert text == "Hello there.\n", text


def test_linked_note_marker_is_removed_but_exponent_is_kept():
    text, _ = read_aloud('<p>Born in 1492.<sup><a href="#n1">1</a></sup> Died later.</p>'
                         '<p>Two to the <sup>4</sup> is sixteen.</p>')
    assert text == "Born in 1492. Died later.\nTwo to the 4 is sixteen.\n", text


def test_note_bodies_are_removed():
    text, report = read_aloud('<p>Story text.</p><p class="note">1 A footnote body.</p>'
                              '<aside epub:type="footnote"><p>Another note.</p></aside>')
    assert text == "Story text.\n", text
    assert report.removed_by_rule["footnote / endnote text"].element_count == 2


def test_index_entries_are_removed():
    text, _ = read_aloud('<p class="index">Aardvark, 12, 14</p><p class="indexsub">cats, 3</p><p>Real text.</p>')
    assert text == "Real text.\n", text


def test_caption_and_figure_reference_are_removed_but_small_caps_stay():
    text, _ = read_aloud('<figure><img src="x.png" alt="a dog"/><figcaption>Figure 3. A dog.</figcaption></figure>'
                         '<p>The <span class="caps">NASA</span> team (see fig. 3) agreed.</p>')
    assert text == "The NASA team agreed.\n", text


def test_page_break_marker_is_removed():
    text, _ = read_aloud('<p>Page <span epub:type="pagebreak">45</span> continues.</p>')
    assert text == "Page  continues.\n", text  # two spaces remain: harmless for the voice


def test_nested_list_items_are_read_once():
    text, _ = read_aloud("<ul><li>Fruit<ul><li>Apple</li></ul></li></ul>")
    assert text == "Fruit.\nApple.\n", text


def test_user_chosen_class_is_removed():
    text, _ = read_aloud('<p class="weird">Remove me.</p><p>Keep me.</p>', extra_class_names=["weird"])
    assert text == "Keep me.\n", text


def test_lines_without_words_are_skipped_and_headings_get_a_period():
    text, _ = read_aloud("<h2>A heading</h2><p>* * *</p><p>♦</p>")
    assert text == "A heading.\n", text


class FakeChapter:
    """Just enough of an ebooklib chapter for the selection logic."""
    def __init__(self, file_name, text, title="", title_is_inherited=False):
        self.file_name, self.extracted_text = file_name, text
        self.title, self.title_is_inherited = title, title_is_inherited

    def get_name(self):
        return self.file_name

    def get_type(self):
        import ebooklib
        return ebooklib.ITEM_DOCUMENT


def test_only_chapter_like_files_are_converted():
    from audiblez.chapter_selection import find_good_chapters
    long_text = "Some real story text. " * 20
    files = [FakeChapter("text/Chapter01.xhtml", long_text), FakeChapter("text/Notes.xhtml", long_text),
             FakeChapter("text/Index.xhtml", long_text), FakeChapter("text/Chapter02.xhtml", "too short")]
    assert [c.get_name() for c in find_good_chapters(files)] == ["text/Chapter01.xhtml"]


def test_sections_get_titles_and_reasons():
    from audiblez.chapter_selection import SectionClassifier
    long_text = "Some real story text. " * 20
    files = [
        FakeChapter("text/Cover.xhtml", "", title="Cover"),
        FakeChapter("text/Frontmatter01.xhtml", long_text, title="A Note on the Anniversary Edition"),
        FakeChapter("text/Frontmatter02.xhtml", long_text, title="Timeline of History"),
        FakeChapter("text/Chapter01.xhtml", long_text, title="1. An Animal of No Significance"),
        FakeChapter("text/Chapter01b.xhtml", long_text, title="1. An Animal of No Significance", title_is_inherited=True),
        FakeChapter("text/Backmatter01.xhtml", long_text, title="Afterword: The Animal that Became a God"),
        FakeChapter("text/Notes.xhtml", long_text, title="Notes"),
        FakeChapter("text/Praise.xhtml", long_text, title="Praise for Sapiens"),
        FakeChapter("text/Chapter09.xhtml", long_text, title="In Praise of Idleness"),
    ]
    rows = [(s.display_title, s.is_included, s.reason, s.is_short) for s in SectionClassifier().describe(files)]
    assert rows == [
        ("Cover", False, "too short", True),
        ("A Note on the Anniversary Edition", True, "a note on", False),
        ("Timeline of History", False, "not recognised", False),
        ("1. An Animal of No Significance", True, "chapter", False),
        ("1. An Animal of No Significance (continued)", True, "chapter", False),
        ("Afterword: The Animal that Became a God", True, "afterword", False),
        ("Notes", False, "notes", False),
        ("Praise for Sapiens", False, "praise", False),
        ("In Praise of Idleness", True, "chapter", False),
    ], rows


def test_everything_is_read_when_no_chapter_is_recognised():
    from audiblez.chapter_selection import SectionClassifier
    files = [FakeChapter("a.xhtml", "x" * 500, title="Strange"), FakeChapter("b.xhtml", "tiny"),
             FakeChapter("c.xhtml", "x" * 500, title="THE FULL PROJECT GUTENBERG LICENSE")]
    sections = SectionClassifier().describe(files)
    assert [s.is_included for s in sections] == [True, False, False]
    assert sections[0].reason == "no chapters recognised"


def test_book_metadata_finds_isbn_and_builds_links():
    from ebooklib import epub
    from audiblez.book_metadata import BookMetadata
    book = epub.EpubBook()
    book.set_identifier("urn:uuid:12345678-1234-1234-1234-123456789012")
    book.add_metadata("DC", "identifier", "urn:isbn:978-0-06-345398-2")
    book.set_title("Sapiens [Tenth Anniversary Edition]")
    book.add_author("Yuval Noah Harari")
    book.set_language("en")
    book.add_metadata("DC", "description", "<p>A <b>brief</b> history.</p>")
    metadata = BookMetadata.from_epub(book)
    assert metadata.isbn == "9780063453982", metadata.isbn
    assert metadata.authors == ["Yuval Noah Harari"]
    assert metadata.description == "A brief history.", metadata.description
    assert metadata.search_title == "Sapiens"
    urls = {link.label: link.url for link in metadata.links()}
    assert urls["The book on Wikipedia"] == "https://en.wikipedia.org/w/index.php?search=Sapiens"
    assert urls["Yuval Noah Harari on Wikipedia"].endswith("search=Yuval+Noah+Harari")
    assert urls["Goodreads (ratings and reviews)"] == "https://www.goodreads.com/search?q=9780063453982"


def test_book_without_isbn_searches_goodreads_by_title():
    from audiblez.book_metadata import BookMetadata
    metadata = BookMetadata(title="Proces", authors=["Franz Kafka"], language="cs")
    urls = {link.label: link.url for link in metadata.links()}
    assert urls["The book on Wikipedia"].startswith("https://cs.wikipedia.org/")
    assert urls["Goodreads (ratings and reviews)"].endswith("q=Proces+Franz+Kafka")


def test_voice_names_and_languages():
    from audiblez.voice_library import Voice, voices_of, LANGUAGES
    george = Voice("bm_george")
    assert george.display_name == "George (male)"
    assert george.language.name == "English (British)"
    assert [voice.id for voice in voices_of("e")] == ["ef_dora", "em_alex", "em_santa"]
    assert all(voices_of(language.code) for language in LANGUAGES), "every language has at least one voice"


def test_settings_are_saved_and_loaded_and_survive_a_broken_file():
    import json, tempfile
    from pathlib import Path
    from audiblez.settings import UserSettings
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "settings.json"
        assert UserSettings.load(path) == UserSettings(), "no file yet -> defaults"

        UserSettings(voice_id="am_michael", speed=1.25, device="cpu", window_size=[800, 600]).save(path)
        loaded = UserSettings.load(path)
        assert (loaded.voice_id, loaded.speed, loaded.device, loaded.window_size) == ("am_michael", 1.25, "cpu", [800, 600])

        path.write_text("{ this is not json", encoding="utf-8")
        assert UserSettings.load(path) == UserSettings(), "broken file -> defaults"

        path.write_text(json.dumps({"speed": "fast", "voice_id": 7, "device": "cpu", "unknown": 1, "speed_x": 2}))
        loaded = UserSettings.load(path)
        assert (loaded.speed, loaded.voice_id, loaded.device) == (1.0, "bm_george", "cpu"), "wrong types -> defaults"

        path.write_text(json.dumps({"speed": 2}))
        assert UserSettings.load(path).speed == 2.0, "a whole number is accepted as a speed"


class FakeHtmlChapter:
    """Just enough of an ebooklib document for the picture text detector."""
    def __init__(self, html):
        self.html = html

    def get_body_content(self):
        return self.html.encode("utf-8")


def test_picture_text_is_found_by_its_position_next_to_pictures():
    from audiblez.picture_text_detector import PictureTextDetector
    story = '<p class="indent">Normal story text that goes on and on.</p>' * 30
    picture_group = ('<div class="full40"><img src="a.jpg"/></div><div class="full40"><img src="b.jpg"/></div>'
                     '<p class="capl0">2. Our siblings, a caption.</p><p class="credit">© Some Agency.</p>')
    inline_picture = '<p class="indent">Story with a small <img src="icon.png"/> picture inside.</p>'
    already_handled = '<div class="full"><img src="map.jpg"/><p class="caption">Map 1. A map.</p></div>'
    page = story + picture_group + story + picture_group + inline_picture + already_handled + story
    groups = PictureTextDetector().find_groups([FakeHtmlChapter(page)])
    found = {(group.css_class, group.kind, group.near_picture_count, group.total_count) for group in groups}
    assert found == {("capl0", "picture captions", 2, 2), ("credit", "picture credits", 2, 2)}, found


def test_story_text_is_never_picture_text_even_in_a_book_full_of_pictures():
    from audiblez.picture_text_detector import PictureTextDetector
    # a technical book: almost every story paragraph sits next to a diagram
    diagram_page = ('<p class="indent">Some explanation of the circuit below, long enough to matter.</p>'
                    '<div><img src="d.png"/></div><p class="indent">More explanation after the diagram.</p>'
                    '<p class="center">or</p><div><img src="e.png"/></div>') * 20
    credits = '<div><img src="p.jpg"/></div><p class="fig-credit">ullstein bild/Getty Images</p>' * 3
    groups = {group.css_class: group.kind for group in PictureTextDetector().find_groups([FakeHtmlChapter(diagram_page + credits)])}
    assert groups == {"center": "short labels", "fig-credit": "picture credits"}, groups


def test_every_extracted_line_remembers_where_it_came_from():
    from audiblez.epub_text_extractor import EpubTextExtractor
    kinds = []
    text = EpubTextExtractor.with_default_rules().extract_text_from_html(
        '<h2 class="chtit">Title</h2><p class="indent">One.</p><p>  </p><p class="capl0">Two.</p>', line_kinds=kinds)
    assert text == "Title.\nOne.\nTwo.\n", text
    assert kinds == [("h2", ("chtit",)), ("p", ("indent",)), ("p", ("capl0",))], kinds


def test_combined_report_adds_up_chapter_reports():
    from audiblez.epub_text_extractor import CleaningReport
    _, first = read_aloud('<p class="note">aaaa</p>')
    _, second = read_aloud('<p class="note">bb</p><p>kept text</p>')
    combined = CleaningReport.combine([first, second])
    assert combined.removed_by_rule["footnote / endnote text"].element_count == 2
    assert combined.removed_by_rule["footnote / endnote text"].characters == 6
    assert combined.kept_characters == len("kept text.")


if __name__ == "__main__":
    all_tests = {name: function for name, function in globals().items() if name.startswith("test_")}
    for name, function in all_tests.items():
        function()
        print("ok  ", name)
    print(f"\nAll {len(all_tests)} checks passed.")
