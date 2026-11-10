# -*- coding: utf-8 -*-
"""
Command line for the cleaned-up audiblez copy. Run it from C:\\Users\\lukas\\audiblez with:

    venv\\Scripts\\python -m audiblez_clean.cli book.epub -c -v bm_george            (convert)
    venv\\Scripts\\python -m audiblez_clean.cli book.epub --report                   (inspect cleaning only)
    venv\\Scripts\\python -m audiblez_clean.cli book.epub --report --drop-class para-en --drop-class link_to_text
"""
import argparse
import sys

from audiblez_clean.chapter_selection import find_good_chapters
from audiblez_clean.epub_text_extractor import CleaningReport, EpubTextExtractor
from audiblez_clean.voices import voices, available_voices_str


def build_argument_parser():
    voices_str = ', '.join(voices)
    epilog = ('example:\n' +
              '  python -m audiblez_clean.cli book.epub -v bm_george -c\n\n' +
              'inspect what the cleaning removes, without making any audio:\n' +
              '  python -m audiblez_clean.cli book.epub --report\n\n' +
              'available voices:\n' +
              available_voices_str)
    default_voice = 'bm_george'
    parser = argparse.ArgumentParser(epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('epub_file_path', help='Path to the epub file')
    parser.add_argument('-v', '--voice', default=default_voice, help=f'Choose narrating voice: {voices_str}')
    parser.add_argument('-p', '--pick', default=False, help=f'Interactively select which chapters to read in the audiobook', action='store_true')
    parser.add_argument('-s', '--speed', default=1.0, help=f'Set speed from 0.5 to 2.0', type=float)
    parser.add_argument('-c', '--cuda', default=False, help=f'Use GPU via Cuda in Torch if available', action='store_true')
    parser.add_argument('-o', '--output', default='.', help='Output folder for the audiobook and temporary files', metavar='FOLDER')
    parser.add_argument('--report', default=False, action='store_true',
                        help='Only show what the text cleaning removes and keeps. No audio is made.')
    parser.add_argument('--drop-class', action='append', default=[], metavar='CSS_CLASS',
                        help='Also remove every element with this CSS class (can be repeated). '
                             'Find class names with --report.')
    return parser


def run_cleaning_report(epub_file_path, extractor):
    """
    --report: read the book, clean it, print what happened. Fast, because no voice model is loaded.
    Only the files that audiblez would really convert are counted (see chapter_selection.py).
    """
    from ebooklib import epub
    book = epub.read_epub(epub_file_path)
    all_files = extractor.extract_chapters(book)
    converted_files = find_good_chapters(all_files)
    print(f"\n{len(converted_files)} of {len(all_files)} files in this book would be converted to audio.")
    report = CleaningReport.combine(chapter.cleaning_report for chapter in converted_files)
    report.print_removals(show_samples=True)
    report.print_most_common_kept_elements()


def use_gpu_if_requested(wants_cuda):
    if not wants_cuda:
        return
    import torch.cuda
    if torch.cuda.is_available():
        print('CUDA GPU available')
        torch.set_default_device('cuda')
    else:
        print('CUDA GPU not available. Defaulting to CPU')


def cli_main():
    parser = build_argument_parser()
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)
    args = parser.parse_args()

    extractor = EpubTextExtractor.with_default_rules(extra_class_names=args.drop_class)

    if args.report:
        run_cleaning_report(args.epub_file_path, extractor)
        return

    use_gpu_if_requested(args.cuda)
    from audiblez_clean.core import main  # imported here because loading the voice libraries is slow
    main(args.epub_file_path, args.voice, args.pick, args.speed, args.output, text_extractor=extractor)


if __name__ == '__main__':
    cli_main()
