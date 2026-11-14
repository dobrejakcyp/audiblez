#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# audiblez - A program to convert e-books into audiobooks using
# Kokoro-82M model for high-quality text-to-speech synthesis.
# by Claudio Santini 2025 - https://claudio.uk
#
# Changes in this fork (github.com/dobrejakcyp/audiblez) compared to v0.4.9:
#   - Deciding WHAT text is read aloud moved out to cleaning_rules.py, epub_text_extractor.py and
#     chapter_selection.py; the cover lookup moved to book_metadata.py.
#   - main() got two new optional arguments: `text_extractor` and `stop_requested`.
#   - Voice synthesis, ffmpeg and m4b creation are otherwise unchanged.
# The original code is in the git history (tag v0.4.9).
import functools
import os
import traceback
from glob import glob

import torch.cuda
import spacy
import ebooklib
import soundfile
import numpy as np
import time
import shutil
import subprocess
import platform
import re
from io import StringIO
from types import SimpleNamespace
from tabulate import tabulate
from pathlib import Path
from string import Formatter
from kokoro import KPipeline
from ebooklib import epub
from pick import pick

from audiblez.book_metadata import audiobook_file_name, find_cover, readable_author_name
from audiblez.chapter_selection import find_good_chapters
from audiblez.epub_text_extractor import CleaningReport, EpubTextExtractor
from audiblez.spoken_blocks import PAUSE_AROUND_HEADING, SpokenBlock, spoken_blocks

sample_rate = 24000


def load_spacy():
    if not spacy.util.is_package("xx_ent_wiki_sm"):
        print("Downloading Spacy model xx_ent_wiki_sm...")
        spacy.cli.download("xx_ent_wiki_sm")


def set_espeak_library():
    """Find the espeak library path"""
    try:

        if os.environ.get('ESPEAK_LIBRARY'):
            library = os.environ['ESPEAK_LIBRARY']
        elif platform.system() == 'Darwin':
            from subprocess import check_output
            try:
                cellar = Path(check_output(["brew", "--cellar"], text=True).strip())
                pattern = cellar / "espeak-ng" / "*" / "lib" / "*.dylib"
                if not (library := next(iter(glob(str(pattern))), None)):
                    raise RuntimeError("No espeak-ng library found; please set the path manually")
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                raise RuntimeError("Cannot locate Homebrew Cellar. Is 'brew' installed and in PATH?") from e
        elif platform.system() == 'Linux':
            library = glob('/usr/lib/*/libespeak-ng*')[0]
        elif platform.system() == 'Windows':
            library = 'C:\\Program Files*\\eSpeak NG\\libespeak-ng.dll'
        else:
            print('Unsupported OS, please set the espeak library path manually')
            return
        print('Using espeak library:', library)
        from phonemizer.backend.espeak.wrapper import EspeakWrapper
        EspeakWrapper.set_library(library)
    except Exception:
        traceback.print_exc()
        print("Error finding espeak-ng library:")
        print("Probably you haven't installed espeak-ng.")
        print("On Mac: brew install espeak-ng")
        print("On Linux: sudo apt install espeak-ng")


class ConversionStopped(Exception):
    """Raised between two sentences when the user pressed Stop (see `stop_requested` in main)."""


def main(file_path, voice, pick_manually, speed, output_folder='.',
         max_chapters=None, max_sentences=None, selected_chapters=None, post_event=None,
         text_extractor=None, stop_requested=None, work_folder=None):
    """
    output_folder: where the finished .m4b is saved.
    work_folder: where the chapter .wav files and the helper files for ffmpeg go while the audiobook
        is made (the window uses the book's own "work" folder, see library.py). Default: output_folder.
        After a successful run it is removed if it is empty and not the output folder itself.
    stop_requested: an optional threading.Event. When it is set, the conversion stops before the
        next sentence. Chapters that were already finished stay in the work folder as .wav files,
        and running the same book again continues with the first unfinished chapter.
    """
    def status(message, busy=False):  # busy: phase without a percentage, UI shows an animated bar
        print(message)
        if post_event: post_event('CORE_STATUS', message=message, busy=busy)

    try:
        convert(file_path, voice, pick_manually, speed, output_folder, max_chapters, max_sentences,
                selected_chapters, post_event, text_extractor, stop_requested, status, work_folder)
    except ConversionStopped:
        status('⏹ Stopped. Finished chapters are kept; start again to continue where it stopped.')
        if post_event: post_event('CORE_FINISHED', stopped=True)


def convert(file_path, voice, pick_manually, speed, output_folder, max_chapters, max_sentences,
            selected_chapters, post_event, text_extractor, stop_requested, status, work_folder=None):
    """The original body of main(); moved here so main() can catch ConversionStopped in one place."""

    if post_event: post_event('CORE_STARTED')
    status('Loading language model…', busy=True)
    load_spacy()
    output_folder = Path(output_folder).resolve()  # relative paths break ffmpeg concat (issue #133)
    output_folder.mkdir(parents=True, exist_ok=True)
    work_folder = Path(work_folder).resolve() if work_folder else output_folder
    work_folder.mkdir(parents=True, exist_ok=True)

    extension = '.epub'
    book = epub.read_epub(file_path)
    meta_title = book.get_metadata('DC', 'title')
    title = meta_title[0][0] if meta_title else ''
    meta_creator = book.get_metadata('DC', 'creator')
    creator = readable_author_name(meta_creator[0][0]) if meta_creator else ''  # "Gertner, Jon" -> "Jon Gertner"

    # The audiobook is named "Author - Title.m4b" from the book's details, not after the EPUB file
    # (see book_metadata.audiobook_file_name). `filename` keeps the form "<name>.epub" because the
    # functions below derive the names of the .wav, .txt and .m4b files from it.
    filename = audiobook_file_name(title, [creator] if creator else [], fallback=Path(file_path).stem) + extension

    cover_maybe = find_cover(book)
    cover_image = cover_maybe.get_content() if cover_maybe else b""
    if cover_maybe:
        print(f'Found cover image {cover_maybe.file_name} in {cover_maybe.media_type} format')

    if text_extractor is None:
        text_extractor = EpubTextExtractor.with_default_rules()
    document_chapters = text_extractor.extract_chapters(book)

    if not selected_chapters:
        if pick_manually is True:
            selected_chapters = pick_chapters(document_chapters)
        else:
            selected_chapters = find_good_chapters(document_chapters)
    print_selected_chapters(document_chapters, selected_chapters)
    # Only the chapters that will really be converted count in the cleaning report
    CleaningReport.combine(c.cleaning_report for c in selected_chapters).print_removals(show_samples=False)
    texts = [c.extracted_text for c in selected_chapters]

    has_ffmpeg = shutil.which('ffmpeg') is not None
    if not has_ffmpeg:
        print('\033[91m' + 'ffmpeg not found. Please install ffmpeg to create mp3 and m4b audiobook files.' + '\033[0m')

    stats = SimpleNamespace(
        total_chars=sum(map(len, texts)),
        processed_chars=0,
        chars_per_sec=500 if torch.cuda.is_available() else 50,  # initial guess, replaced by measured speed
        synth_chars=0, synth_start=0, chapter='')
    print('Started at:', time.strftime('%H:%M:%S'))
    print(f'Total characters: {stats.total_chars:,}')
    print('Total words:', len(' '.join(texts).split()))
    eta = strfdelta((stats.total_chars - stats.processed_chars) / stats.chars_per_sec)
    print(f'Estimated time remaining (assuming {stats.chars_per_sec} chars/sec): {eta}')
    status('Loading voice model…', busy=True)
    set_espeak_library()
    pipeline = KPipeline(lang_code=voice[0])  # a for american or b for british etc.
    stats.synth_start = time.time()

    chapter_wav_files = []
    chapter_titles = {}
    for i, chapter in enumerate(selected_chapters, start=1):
        if max_chapters and i > max_chapters: break
        stats.chapter = f'{i} of {len(selected_chapters)}'
        text = chapter.extracted_text
        xhtml_file_name = chapter.get_name().replace(' ', '_').replace('/', '_').replace('\\', '_')
        chapter_wav_path = work_folder / filename.replace(extension, f'_chapter_{i}_{voice}_{xhtml_file_name}.wav')
        chapter_wav_files.append(chapter_wav_path)
        chapter_titles[chapter_wav_path] = chapter.title
        if Path(chapter_wav_path).exists():
            print(f'File for chapter {i} already exists. Skipping')
            stats.processed_chars += len(text)
            if post_event:
                post_event('CORE_CHAPTER_FINISHED', chapter_index=chapter.chapter_index)
            continue
        if len(text.strip()) < 10:
            print(f'Skipping empty chapter {i}')
            chapter_wav_files.remove(chapter_wav_path)
            continue
        # Headings are spoken on their own with silence around them (see spoken_blocks.py)
        blocks = spoken_blocks(text, getattr(chapter, 'line_kinds', None))
        if i == 1:
            blocks.insert(0, SpokenBlock(f'{title} – {creator}.\n', PAUSE_AROUND_HEADING))  # intro text
        start_time = time.time()
        if post_event: post_event('CORE_CHAPTER_STARTED', chapter_index=chapter.chapter_index)
        audio_segments = []
        for block in blocks:
            block_audio = gen_audio_segments(
                pipeline, block.text, voice, speed, stats, post_event=post_event, max_sentences=max_sentences,
                stop_requested=stop_requested)
            audio_segments += block_audio
            if block_audio and block.pause_after:
                audio_segments.append(silence(block.pause_after))
        if audio_segments:
            final_audio = np.concatenate(audio_segments)
            soundfile.write(chapter_wav_path, final_audio, sample_rate)
            end_time = time.time()
            delta_seconds = end_time - start_time
            chars_per_sec = len(text) / delta_seconds
            print('Chapter written to', chapter_wav_path)
            if post_event: post_event('CORE_CHAPTER_FINISHED', chapter_index=chapter.chapter_index)
            print(f'Chapter {i} read in {delta_seconds:.2f} seconds ({chars_per_sec:.0f} characters per second)')
        else:
            print(f'Warning: No audio generated for chapter {i}')
            chapter_wav_files.remove(chapter_wav_path)

    # The window waits for CORE_FINISHED, so it is sent on every path, and says whether the .m4b exists.
    m4b_created = False
    if has_ffmpeg:
        status('Creating the .m4b file: joining chapters and compressing audio (can take several minutes)…', busy=True)
        create_index_file(title, creator, chapter_wav_files, work_folder, chapter_titles)
        m4b_created = create_m4b(chapter_wav_files, filename, cover_image, output_folder, work_folder)
        if m4b_created:
            remove_if_empty(work_folder, keep=output_folder)
            status(f'✅ Done: {filename.replace(".epub", ".m4b")} created')
        else:
            status('❌ Creating the .m4b file failed, see the console window for details')
    else:
        status('❌ ffmpeg is not installed, so the chapters could not be joined into an .m4b file')
    if post_event: post_event('CORE_FINISHED', failed=not m4b_created)


def remove_if_empty(folder, keep):
    """Remove the work folder once the audiobook is made, unless it still holds something or is `keep`."""
    if folder != keep:
        try:
            folder.rmdir()  # only works on an empty folder, so nothing can be lost here
        except OSError:
            pass


def find_document_chapters_and_extract_texts(book):
    """Kept for code written against audiblez v0.4.9 (e.g. the tests in test/): cleans the book with the
    default rules and returns its chapters, each with .extracted_text and .title."""
    return EpubTextExtractor.with_default_rules().extract_chapters(book)


def print_selected_chapters(document_chapters, chapters):
    ok = 'X' if platform.system() == 'Windows' else '✅'
    print(tabulate([
        [i, c.get_name(), len(c.extracted_text), ok if c in chapters else '', chapter_beginning_one_liner(c)]
        for i, c in enumerate(document_chapters, start=1)
    ], headers=['#', 'Chapter', 'Text Length', 'Selected', 'First words']))


def silence(seconds):
    """`seconds` of silence in the audio format Kokoro produces."""
    return np.zeros(int(sample_rate * seconds), dtype=np.float32)


@functools.lru_cache(maxsize=1)
def sentence_splitter():
    """spaCy's sentence splitter, loaded once (a chapter is spoken in several blocks)."""
    nlp = spacy.load('xx_ent_wiki_sm')
    nlp.add_pipe('sentencizer')
    return nlp


def gen_audio_segments(pipeline, text, voice, speed, stats=None, max_sentences=None, post_event=None,
                       stop_requested=None):
    audio_segments = []
    doc = sentence_splitter()(text)
    sentences = list(doc.sents)
    for i, sent in enumerate(sentences):
        if max_sentences and i > max_sentences: break
        if stop_requested is not None and stop_requested.is_set():
            raise ConversionStopped()  # the unfinished chapter is NOT saved, so no half chapters are left
        for gs, ps, audio in pipeline(sent.text, voice=voice, speed=speed, split_pattern=r'\n\n\n'):
            audio_segments.append(audio)
        if stats:
            stats.processed_chars += len(sent.text)
            stats.synth_chars += len(sent.text)  # excludes skipped chapters, so the speed below is real
            elapsed = time.time() - stats.synth_start
            if elapsed > 10:  # past model warm-up
                stats.chars_per_sec = stats.synth_chars / elapsed
            stats.progress = min(100, stats.processed_chars * 100 // stats.total_chars)
            stats.eta = strfdelta((stats.total_chars - stats.processed_chars) / stats.chars_per_sec)
            if post_event: post_event('CORE_PROGRESS', stats=stats)
            print(f'Estimated time remaining: {stats.eta}')
            print('Progress:', f'{stats.progress}%\n')
    return audio_segments


def gen_text(text, voice='af_heart', output_file='text.wav', speed=1, play=False):
    lang_code = voice[:1]
    pipeline = KPipeline(lang_code=lang_code)
    load_spacy()
    audio_segments = gen_audio_segments(pipeline, text, voice=voice, speed=speed);
    final_audio = np.concatenate(audio_segments)
    soundfile.write(output_file, final_audio, sample_rate)
    if play:
        subprocess.run(['ffplay', '-autoexit', '-nodisp', output_file])


def chapter_beginning_one_liner(c, chars=20):
    s = c.extracted_text[:chars].strip().replace('\n', ' ').replace('\r', ' ')
    return s + '…' if len(s) > 0 else ''


def pick_chapters(chapters):
    # Display the document name, the length and first 50 characters of the text
    chapters_by_names = {
        f'{c.get_name()}\t({len(c.extracted_text)} chars)\t[{chapter_beginning_one_liner(c, 50)}]': c
        for c in chapters}
    title = 'Select which chapters to read in the audiobook'
    ret = pick(list(chapters_by_names.keys()), title, multiselect=True, min_selection_count=1)
    selected_chapters_out_of_order = [chapters_by_names[r[0]] for r in ret]
    selected_chapters = [c for c in chapters if c in selected_chapters_out_of_order]
    return selected_chapters


def strfdelta(tdelta, fmt='{D:02}d {H:02}h {M:02}m {S:02}s'):
    remainder = int(tdelta)
    f = Formatter()
    desired_fields = [field_tuple[1] for field_tuple in f.parse(fmt)]
    possible_fields = ('W', 'D', 'H', 'M', 'S')
    constants = {'W': 604800, 'D': 86400, 'H': 3600, 'M': 60, 'S': 1}
    values = {}
    for field in possible_fields:
        if field in desired_fields and field in constants:
            values[field], remainder = divmod(remainder, constants[field])
    return f.format(fmt, **values)


def concat_wavs_with_ffmpeg(chapter_files, work_folder, filename):
    wav_list_txt = Path(work_folder) / filename.replace('.epub', '_wav_list.txt')
    with open(wav_list_txt, 'w', encoding='utf-8') as f:
        for wav_file in chapter_files:
            f.write(f"file '{wav_file}'\n")
    concat_file_path = Path(work_folder) / filename.replace('.epub', '.tmp.mp4')
    subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', wav_list_txt, '-c', 'copy', concat_file_path])
    Path(wav_list_txt).unlink()
    return concat_file_path


def create_m4b(chapter_files, filename, cover_image, output_folder, work_folder=None):
    """Join the chapters into output_folder/<name>.m4b. Helper files are made in work_folder (default: output_folder)."""
    work_folder = work_folder or output_folder
    concat_file_path = concat_wavs_with_ffmpeg(chapter_files, work_folder, filename)
    final_filename = Path(output_folder) / filename.replace('.epub', '.m4b')
    chapters_txt_path = Path(work_folder) / "chapters.txt"
    print('Creating M4B file...')

    if cover_image:
        cover_file_path = Path(work_folder) / 'cover'
        with open(cover_file_path, 'wb') as f:
            f.write(cover_image)
        cover_image_args = ["-i", f'{cover_file_path}', "-map", "2:v"]
    else:
        cover_image_args = []

    proc = subprocess.run([
        'ffmpeg',
        '-y',  # overwrite output file without asking
        '-i', f'{concat_file_path}',  # input 0 file (audio)
        '-i', f'{chapters_txt_path}',  # input 1 file (chapters)
        *cover_image_args,  # cover image
        '-map', '0:a',  # audio from input 0 (mapping all of input 0 duplicated the audio when a cover was added)
        '-map_metadata', '1',  # map metadata from input 1
        '-c:a', 'aac', '-b:a', '64k',  # compress audio; copying stored raw PCM wav (huge files)
        '-c:v', 'copy',  # copy video codec
        '-disposition:v', 'attached_pic',  # attach cover image
        '-movflags', '+faststart',  # index/chapters at file start; some players (e.g. Voice) miss them after a >2GB mdat
        '-f', 'mp4',  # format
        f'{final_filename}'  # output file
    ])
    Path(concat_file_path).unlink()
    if proc.returncode == 0 and final_filename.exists() and final_filename.stat().st_size > 0:
        print(f'{final_filename} created. Enjoy your audiobook.')
        for f in [*chapter_files, chapters_txt_path, *([cover_file_path] if cover_image else [])]:
            Path(f).unlink(missing_ok=True)
        print('Removed the intermediary .wav chapter files.')
        return True
    print(f'Creating {final_filename} failed; the .wav chapter files are kept, rerun to retry without regenerating them.')
    return False


def probe_duration(file_name):
    args = ['ffprobe', '-i', file_name, '-show_entries', 'format=duration', '-v', 'quiet', '-of', 'default=noprint_wrappers=1:nokey=1']
    proc = subprocess.run(args, capture_output=True, text=True, check=True)
    return float(proc.stdout.strip())


def ffmetadata_escape(s):
    return re.sub(r'([=;#\\\n])', r'\\\1', s)


def create_index_file(title, creator, chapter_mp3_files, folder, chapter_titles=None):
    """Write folder/chapters.txt: the book's title, author and chapter marks for ffmpeg."""
    chapter_titles = chapter_titles or {}
    with open(Path(folder) / "chapters.txt", "w", encoding="utf-8") as f:
        f.write(f";FFMETADATA1\ntitle={ffmetadata_escape(title)}\nartist={ffmetadata_escape(creator)}\n\n")
        start = 0
        i = 0
        for c in chapter_mp3_files:
            duration = probe_duration(c)
            end = start + (int)(duration * 1000)
            name = ffmetadata_escape(chapter_titles.get(c) or f'Chapter {i + 1}')
            f.write(f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={start}\nEND={end}\ntitle={name}\n\n")
            i += 1
            start = end


def unmark_element(element, stream=None):
    """auxiliarry function to unmark markdown text"""
    if stream is None:
        stream = StringIO()
    if element.text:
        stream.write(element.text)
    for sub in element:
        unmark_element(sub, stream)
    if element.tail:
        stream.write(element.tail)
    return stream.getvalue()


def unmark(text):
    """Unmark markdown text"""
    Markdown.output_formats["plain"] = unmark_element  # patching Markdown
    __md = Markdown(output_format="plain")
    __md.stripTopLevelTags = False
    return __md.convert(text)
