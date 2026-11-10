"""
A/B comparison: your patched original (A) against the new cleaning pipeline (B).
Nothing is synthesised and nothing is written unless you pass --write-texts.

    venv\\Scripts\\python compare_cleaning.py book.epub [--drop-class NAME ...] [--write-texts FOLDER]

It prints three lines:
    A         text the original audiblez\\core.py would read aloud
    B-same    the NEW code but with ONLY the original rules  -> shows code-level differences
              (e.g. text the original read twice because of nested <li><p> tags)
    B-full    the NEW code with all default rules (+ your --drop-class)  -> shows the cleaning gain
With --write-texts FOLDER it also saves chapter texts into FOLDER\\A and FOLDER\\B so you can
compare them in any diff tool, and you can listen-test the chapters you are curious about.
"""
import argparse
from pathlib import Path

from ebooklib import epub

from audiblez.core import find_document_chapters_and_extract_texts, find_good_chapters  # A: the original, untouched
from audiblez_clean.cleaning_rules import CaptionRule, default_text_edits
from audiblez_clean.epub_text_extractor import EpubTextExtractor  # B: the new code

CHARACTERS_PER_AUDIO_MINUTE = 900  # same estimate as the cleaning report


def converted_chapter_texts(extract_function, epub_path, converted_file_names=None):
    """
    Read the book fresh (extraction annotates the book, so never reuse one) and return
    (file names, texts) of the files that audiblez really converts. Pass the names from the
    first run so that A and B are always compared on exactly the same files.
    """
    chapters = extract_function(epub.read_epub(epub_path))
    if converted_file_names is None:
        converted_file_names = [c.get_name() for c in find_good_chapters(chapters)]  # audiblez's own decision
    texts = [c.extracted_text for c in chapters if c.get_name() in converted_file_names]
    return converted_file_names, texts


def describe(label, texts):
    characters = sum(len(text) for text in texts)
    print(f"  {label:<8} {characters:>10,} characters  (about {characters / CHARACTERS_PER_AUDIO_MINUTE / 60:.1f} h)")
    return characters


def save_texts(folder, texts):
    folder.mkdir(parents=True, exist_ok=True)
    for number, text in enumerate(texts):
        (folder / f"chapter_{number:03d}.txt").write_text(text, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("epub_path")
    parser.add_argument("--drop-class", action="append", default=[], metavar="CSS_CLASS")
    parser.add_argument("--write-texts", metavar="FOLDER")
    args = parser.parse_args()

    names, original = converted_chapter_texts(find_document_chapters_and_extract_texts, args.epub_path)
    same_rules_new_code = EpubTextExtractor([CaptionRule()], default_text_edits())
    _, new_same = converted_chapter_texts(same_rules_new_code.extract_chapters, args.epub_path, names)
    full_cleaning = EpubTextExtractor.with_default_rules(args.drop_class)
    _, new_full = converted_chapter_texts(full_cleaning.extract_chapters, args.epub_path, names)

    print(f"\n{Path(args.epub_path).name[:70]}")
    print(f"  (only the {len(names)} files that audiblez really converts)")
    chars_a = describe("A", original)
    chars_same = describe("B-same", new_same)
    chars_full = describe("B-full", new_full)
    print(f"\n  code-level difference (A -> B-same): {chars_same - chars_a:+,} characters")
    print(f"  cleaning gain         (B-same -> B-full): {chars_full - chars_same:+,} characters "
          f"= about {(chars_same - chars_full) / CHARACTERS_PER_AUDIO_MINUTE:.0f} minutes less audio")

    different = [n for n, (a, b) in enumerate(zip(original, new_same)) if a != b]
    print(f"  chapters where A and B-same differ: {len(different)} of {len(original)}")
    if args.write_texts:
        save_texts(Path(args.write_texts) / "A", original)
        save_texts(Path(args.write_texts) / "B", new_full)
        print(f"  texts saved under {args.write_texts}\\A and \\B")


if __name__ == "__main__":
    main()
