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
    assert text == "Page continues.\n", text  # the gap left by the page number becomes one space


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


def test_story_paragraphs_without_a_class_still_count_as_book_text():
    from audiblez.picture_text_detector import PictureTextDetector
    # Many books have plain <p> story paragraphs. They must count as book text, otherwise the
    # captions look like a big part of the book and are wrongly treated as story text.
    story = "<p>A plain story paragraph without any class name, long enough to be real text.</p>" * 30
    pictures = '<div><img src="a.png"/></div><p class="plate">Plate 1. A caption.</p>' * 3
    groups = PictureTextDetector().find_groups([FakeHtmlChapter(story + pictures)])
    assert [group.css_class for group in groups] == ["plate"], groups


def test_every_extracted_line_remembers_where_it_came_from():
    from audiblez.epub_text_extractor import EpubTextExtractor
    kinds = []
    text = EpubTextExtractor.with_default_rules().extract_text_from_html(
        '<h2 class="chtit">Title</h2><p class="indent">One.</p><p>  </p><p class="capl0">Two.</p>', line_kinds=kinds)
    assert text == "Title.\nOne.\nTwo.\n", text
    assert kinds == [("h2", ("chtit",)), ("p", ("indent",)), ("p", ("capl0",))], kinds


def test_version_is_the_same_in_the_package_and_in_pyproject():
    try:
        import tomllib  # part of Python since 3.11
    except ModuleNotFoundError:
        return  # Python 3.10: nothing to read pyproject.toml with, so this check is skipped
    from pathlib import Path
    from audiblez import __version__
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with open(pyproject, "rb") as file:
        packaging_version = tomllib.load(file)["project"]["version"]
    assert __version__ == packaging_version, f"audiblez/__init__.py says {__version__}, pyproject.toml says {packaging_version}"


def test_audiobook_file_names_are_safe_and_come_from_the_book_details():
    from audiblez.book_metadata import audiobook_file_name, safe_file_name
    assert audiobook_file_name("Sapiens: A Brief History", ["Yuval Noah Harari"], "x") == \
        "Yuval Noah Harari - Sapiens - A Brief History"
    assert audiobook_file_name("", [], "Sapiens_ -- Anna's Archive") == "Sapiens_ -- Anna's Archive", "no title: EPUB name"
    assert audiobook_file_name("", [], "") == "audiobook"
    assert safe_file_name('Who? What / Why*  ') == "Who- What - Why-", "forbidden characters become dashes"
    assert safe_file_name("The End.  ") == "The End", "Windows refuses names ending in a dot or space"
    assert safe_file_name("Zločin a trest") == "Zločin a trest", "accented letters are fine"
    assert safe_file_name("CON") == "CON_", "Windows reserves CON"
    assert len(safe_file_name("x" * 500)) == 150


def test_lines_of_one_kind_are_found_across_chapters():
    from audiblez.picture_text_detector import find_lines_of_kind

    class Section:
        def __init__(self, line_kinds):
            self.chapter = type("Chapter", (), {"line_kinds": line_kinds})()

    first = Section([("p", ("indent",)), ("p", ("capl0",)), ("p", ("credit",))])
    empty = Section([])
    second = Section([("p", ("capl0",)), ("p", ("indent",)), ("p", ("capl0", "small"))])
    found = find_lines_of_kind([first, empty, second], "capl0")
    assert [(section is first, line) for section, line in found] == [(True, 1), (False, 0), (False, 2)], found


def test_font_lists_are_cleaned_recommended_and_searchable():
    from audiblez.fonts import clean_font_names, recommended_fonts, search_fonts
    raw = ["Georgia", "@MS Gothic", "Arial", "georgia", "", "  ", "Cambria", "Comic Sans MS", "MS Gothic", "Arial"]
    names = clean_font_names(raw)
    assert "@MS Gothic" not in names and "" not in names, names
    assert names == sorted(set(names), key=str.casefold) and names.count("Arial") == 1, names
    assert recommended_fonts(["Arial", "cambria", "Georgia", "Comic Sans MS"]) == ["Georgia", "cambria"], \
        "only installed serif fonts, in the order of the recommended list, with the installed spelling"
    assert search_fonts(["Georgia", "Cambria", "Book Antiqua"], " geo ") == ["Georgia"]
    assert search_fonts(["Georgia", "Cambria"], "") == ["Georgia", "Cambria"]


def test_audio_length_is_described_in_minutes_or_hours():
    from audiblez.ui_common import describe_audio_length
    assert describe_audio_length(836_717) == "836,717 characters (about 15.5 hours of audio)"
    assert describe_audio_length(2_629) == "2,629 characters (about 3 minutes of audio)"
    assert describe_audio_length(900) == "900 characters (about 1 minute of audio)"
    assert describe_audio_length(0) == "0 characters (about 0 minutes of audio)"


def test_combined_report_adds_up_chapter_reports():
    from audiblez.epub_text_extractor import CleaningReport
    _, first = read_aloud('<p class="note">aaaa</p>')
    _, second = read_aloud('<p class="note">bb</p><p>kept text</p>')
    combined = CleaningReport.combine([first, second])
    assert combined.removed_by_rule["footnote / endnote text"].element_count == 2
    assert combined.removed_by_rule["footnote / endnote text"].characters == 6
    assert combined.kept_characters == len("kept text.")


def test_library_imports_a_copy_tracks_the_book_and_reads_its_status_from_the_folder():
    import tempfile
    from pathlib import Path
    from audiblez.book_metadata import BookMetadata
    from audiblez.library import BookStatus, Library
    with tempfile.TemporaryDirectory() as temporary:
        downloads, root = Path(temporary) / "Downloads", Path(temporary) / "Library"
        downloads.mkdir()
        original = downloads / "nexus.epub"
        original.write_bytes(b"pretend epub")
        metadata = BookMetadata(title="Nexus", authors=["Yuval Noah Harari"])
        library = Library(root)

        copy = library.copy_into_library(original, metadata)
        assert copy == root / "Yuval Noah Harari - Nexus" / "nexus.epub" and copy.read_bytes() == b"pretend epub"
        assert original.exists(), "importing copies, the original stays"
        assert library.copy_into_library(original, metadata) == copy, "importing again reuses the copy"
        assert library.copy_into_library(copy, metadata) == copy, "a book already in the library stays where it is"

        other_edition = downloads / "nexus-2nd.epub"
        other_edition.write_bytes(b"another file")
        assert library.copy_into_library(other_edition, metadata).parent.name == "Yuval Noah Harari - Nexus (2)"

        assert library.record_imported(copy, metadata, imported_from=original), "a new book"
        assert not library.record_imported(copy, metadata), "importing it again is not a second book"
        assert library.status_of(library.book_for_file(copy)) == BookStatus.IMPORTED
        library.record_opened(copy, metadata, imported_from=original)
        book = library.book_for_file(copy)
        assert (book.display_name, book.imported_from) == ("Yuval Noah Harari - Nexus", str(original))
        assert library.status_of(book) == BookStatus.OPENED

        work = Library.work_folder_for(copy)
        work.mkdir()
        (work / "chapter_1.wav").write_bytes(b"")
        assert library.status_of(book) == BookStatus.PARTLY_MADE, "stopped half way"

        (copy.parent / "Yuval Noah Harari - Nexus.m4b").write_bytes(b"audio")
        library.record_audiobook_made(copy, "Yuval Noah Harari - Nexus.m4b", "bm_george")
        assert library.status_of(book) == BookStatus.AUDIOBOOK_MADE

        reloaded = Library(root)  # everything above was saved in library.json
        assert reloaded.book_for_file(copy).voice == "bm_george"
        assert reloaded.status_of(reloaded.book_for_file(copy)) == BookStatus.AUDIOBOOK_MADE
        (copy.parent / "Yuval Noah Harari - Nexus.m4b").unlink()
        assert reloaded.status_of(reloaded.book_for_file(copy)) == BookStatus.PARTLY_MADE, "status follows the files"
        copy.unlink()
        assert reloaded.status_of(reloaded.book_for_file(copy)) == BookStatus.FILES_MISSING

        (copy.parent / "Yuval Noah Harari - Nexus.m4b").write_bytes(b"audio")
        assert reloaded.status_of(reloaded.book_for_file(copy)) == BookStatus.AUDIOBOOK_MADE, "an audiobook without its EPUB"
        assert not reloaded.has_epub(reloaded.book_for_file(copy)), "...cannot be opened"

        (root / "library.json").write_text("{ broken", encoding="utf-8")
        assert Library(root).books == {}, "a broken library.json is an empty library, not a crash"


def test_status_messages_get_their_colour_from_their_icon_and_success_fades_smoothly():
    import wx
    from audiblez.ui_status_banner import MessageKind, message_kind, mix_colours
    assert message_kind("❌ Could not open book.epub") == MessageKind.ERROR
    assert message_kind("⚠ Imported 3 books, 1 could not be read.") == MessageKind.WARNING
    assert message_kind("✅ Done: book.m4b created") == MessageKind.SUCCESS
    assert message_kind("Reading the book details ...") == MessageKind.INFO
    green, grey = wx.Colour(200, 230, 200), wx.Colour(240, 240, 240)
    assert mix_colours(green, grey, 0.0) == green and mix_colours(green, grey, 1.0) == grey
    assert mix_colours(green, grey, 0.5) == wx.Colour(220, 235, 220), "half way"


class FakeTitledChapter:
    """Just enough of an extracted chapter for the heading and section checks."""
    def __init__(self, title, text, file_name="text.xhtml", title_is_inherited=False):
        self.title, self.extracted_text, self.title_is_inherited = title, text, title_is_inherited
        self.line_kinds = [("p", ())] * len(text.splitlines())
        self.file_name = file_name

    def get_name(self):
        return self.file_name


def test_quotation_marks_are_not_read_and_no_period_is_added_after_an_exclamation():
    text, _ = read_aloud('<p>he said, “Oh, what idiots we have all been!”<sup><a href="#n11">11</a></sup></p>'
                         "<p>the ‘vacuum tube’ lab and Shockley’s office</p>")
    assert text == "he said, Oh, what idiots we have all been!\nthe vacuum tube’ lab and Shockley’s office.\n", text


def test_text_standing_directly_in_a_blockquote_is_read():
    text, _ = read_aloud('<blockquote><span>I was given a lecture by the director.</span>'
                         '<sup><small><a href="#n12">12</a></small></sup></blockquote><p>Next paragraph.</p>')
    assert text == "I was given a lecture by the director.\nNext paragraph.\n", text


def test_chapters_and_parts_get_one_spoken_heading_instead_of_the_printed_one():
    from audiblez.spoken_headings import add_spoken_headings, spoken_heading
    assert spoken_heading("CHAPTER 2 The Computer") == "Chapter 2. The Computer."
    assert spoken_heading("Part I: Cold War Chips") == "Part 1. Cold War Chips."
    assert spoken_heading("Chapter 15: “That Competition Is Tough”") == "Chapter 15. That Competition Is Tough."
    for not_numbered in ("I Was Born", "Civil War", "One Day in May", "1984", "Part of the Problem"):
        assert spoken_heading(not_numbered) == not_numbered + ".", not_numbered

    body = "The first thing they noticed was his restlessness, which everyone in town could see.\n"
    part = FakeTitledChapter("PART ONE", "Part 1.\n")
    first = FakeTitledChapter("One. OIL DROPS", "One.\nOIL DROPS.\n" + body)
    continued = FakeTitledChapter("One. OIL DROPS", body, title_is_inherited=True)
    subtitle = FakeTitledChapter("CHAPTER 1 Ada, Countess of Lovelace",
                           "CHAPTER ONE.\nADA, COUNTESS OF LOVELACE.\nPOETICAL SCIENCE.\n" + body)
    add_spoken_headings([part, first, continued, subtitle], short_page_characters=100)
    assert first.extracted_text == "Part ONE.\nChapter One. OIL DROPS.\n" + body, first.extracted_text
    assert len(first.line_kinds) == 3, "one kind per line, so highlighting still lines up"
    assert continued.extracted_text == body, "a page that continues a chapter gets no heading"
    assert subtitle.extracted_text.startswith("Chapter 1. Ada, Countess of Lovelace.\nPOETICAL SCIENCE.\n"), \
        "a subtitle that is not part of the title is kept"


def test_sections_are_recognised_by_numbered_titles_front_matter_and_copyright_text():
    from audiblez.chapter_selection import SectionClassifier
    story = "Real chapter text. " * 20
    sections = SectionClassifier().describe([
        FakeTitledChapter("", "THE PUBLISHER.\nAll rights reserved. " + story, file_name="split_001.html"),
        FakeTitledChapter("", "CONTENTS.\nOne. OIL DROPS.\n" + story, file_name="split_002.html"),
        FakeTitledChapter("Copyright", "All rights reserved. " + story, file_name="split_003.html"),
        FakeTitledChapter("1. 1953", story, file_name="epub_c01_r1.htm"),
        FakeTitledChapter("Selected Bibliography", story, file_name="split_005.html"),
        FakeTitledChapter("Photo Credits", "Page 3: All rights reserved. " + story, file_name="split_006.html"),
    ])
    assert [(s.is_included, s.reason) for s in sections] == [
        (False, "front matter"), (False, "front matter"), (False, "copyright"), (True, "chapter"),
        (False, "selected bibliography"), (False, "copyright")], [(s.is_included, s.reason) for s in sections]


def test_quoted_extracts_are_announced_but_a_whole_indented_page_is_not():
    story = "<p>" + "Plain story text around the quotation. " * 6 + "</p>"
    text, _ = read_aloud(story + "<blockquote><p>I was given a lecture.</p><p>It went on.</p></blockquote>" + story)
    lines = text.splitlines()
    assert lines[1:5] == ["Quote.", "I was given a lecture.", "It went on.", "End quote."], lines
    indented, _ = read_aloud("<blockquote><p>" + "A whole chapter indented with a blockquote. " * 10 + "</p></blockquote>")
    assert "Quote." not in indented, "a blockquote that is most of the page is not a quotation"


def test_author_names_are_put_in_reading_order():
    from audiblez.book_metadata import readable_author_name
    assert readable_author_name("Gertner, Jon") == "Jon Gertner"
    assert readable_author_name("Le Guin, Ursula K.") == "Ursula K. Le Guin"
    for unchanged in ("Walter Isaacson", "Isaacson Walter", "King, Martin Luther, Jr.", "Ford, Jr."):
        assert readable_author_name(unchanged) == unchanged, unchanged


def test_search_finds_every_place_in_the_book_and_goes_round():
    from audiblez.book_search import find_in_book, next_match
    from audiblez.chapter_selection import BookSection
    sections = [BookSection(FakeTitledChapter(title, text), title, True, "chapter", False)
                for title, text in [("One", "The Transistor was new.\n"), ("Two", "No match here.\n"),
                                    ("Three", "A transistor, then another transistor.\n")]]
    matches = find_in_book(sections, "transistor")
    assert [(m.section.display_title, m.start) for m in matches] == [("One", 4), ("Three", 2), ("Three", 27)]
    assert next_match(matches, sections, (sections[1], 0)) == 1, "the next place after section Two"
    assert next_match(matches, sections, (sections[2], 27)) == 0, "after the last place it starts again"
    assert next_match(matches, sections, (sections[0], 4), forward=False) == 2, "before the first: the last"
    assert find_in_book(sections, "   ") == [] and next_match([], sections, (sections[0], 0)) is None


def test_every_line_stays_one_line_so_the_colours_match_the_text():
    kinds = []
    from audiblez.epub_text_extractor import EpubTextExtractor
    text = EpubTextExtractor.with_default_rules().extract_text_from_html(
        "<p>A paragraph written\non two source lines.</p><p>line one<br/>line two</p>", line_kinds=kinds)
    assert text == "A paragraph written on two source lines.\nline one line two.\n", text
    assert len(kinds) == len(text.split("\n")[:-1]) == 2


def test_subheadings_in_capitals_are_recognised_but_code_and_notation_are_not():
    from audiblez.epub_text_extractor import EpubTextExtractor, SUBHEADING
    paragraph = "<p>" + "The personal computer was made possible by many advances. " * 3 + "</p>"
    for html, expected in [("<p>THE CULTURAL BREW</p>", True), ("<p>“AS WE MAY THINK”</p>", True),
                           ("<h3>The Luxury Trap</h3>", True), ("<p>STOP!</p>", False),
                           ("<p>STATUS_OK = 0,</p>", False), ("<p>E4 F2 G2 H2</p>", False),
                           ("<p>A normal short line.</p>", False)]:
        kinds = []
        EpubTextExtractor.with_default_rules().extract_text_from_html(html + paragraph, line_kinds=kinds)
        assert (kinds[0][0] in (SUBHEADING, "h3")) == expected, html  # a real <h3> keeps its own tag


def test_headings_are_spoken_as_separate_blocks_with_a_pause_around_them():
    from audiblez.spoken_blocks import PAUSE_AROUND_HEADING, spoken_blocks
    text = "Chapter 8. The Personal Computer.\nFirst paragraph.\nSecond paragraph.\nTHE CULTURAL BREW.\nMore text.\n"
    kinds = [("spoken heading", ()), ("p", ()), ("p", ()), ("subheading", ()), ("p", ())]
    blocks = [(block.text, block.pause_after) for block in spoken_blocks(text, kinds)]
    assert blocks == [("Chapter 8. The Personal Computer.\n", PAUSE_AROUND_HEADING),
                      ("First paragraph.\nSecond paragraph.\n", PAUSE_AROUND_HEADING),
                      ("THE CULTURAL BREW.\n", PAUSE_AROUND_HEADING), ("More text.\n", 0.0)], blocks
    assert [(b.text, b.pause_after) for b in spoken_blocks(text, kinds[:2])] == [(text, 0.0)], \
        "edited text whose kinds no longer match: one block, as before"


def test_a_poem_printed_line_by_line_is_read_as_flowing_text():
    before = "<p>" + "He captured the new mood in a short poem, which began like this. " * 2 + "</p>"
    poem = ('<p class="first">Down by the river</p><p class="verse">the boats are sleeping,</p>'
            '<p class="verse">the gulls are keeping</p><p class="verse">watch on the shore.</p>')
    text, _ = read_aloud(before + poem + "<p>THE NEXT SECTION</p>" + before)
    lines = text.splitlines()
    assert lines[1] == "Down by the river the boats are sleeping, the gulls are keeping watch on the shore.", lines
    code = "<p class='c'>int x = 0;</p><p class='c'>x = x + 1;</p><p class='c'>return x;</p>"
    assert len(read_aloud(code)[0].splitlines()) == 3, "code is not verse"
    items = "<ul><li>Apples</li><li>Pears</li><li>Plums</li></ul>"
    assert read_aloud(items)[0] == "Apples.\nPears.\nPlums.\n", "list items stay separate"
    table = "<table><tr><td><p>Ancient Athens</p></td><td><p>Rome</p></td><td><p>Carthage</p></td></tr></table>"
    assert len(read_aloud(table)[0].splitlines()) == 3, "table cells stay separate"


if __name__ == "__main__":
    all_tests = {name: function for name, function in globals().items() if name.startswith("test_")}
    for name, function in all_tests.items():
        function()
        print("ok  ", name)
    print(f"\nAll {len(all_tests)} checks passed.")
