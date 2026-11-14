# Changelog

Versions of the dobrejakcyp fork of [Audiblez](https://github.com/santinic/audiblez). The `+dobrejakcyp` label marks
a fork build, so it cannot be confused with an official Audiblez release.

## 0.6.0+dobrejakcyp — 2026-11-14

### Library
- **Import** replaces Open: books are copied into one library folder (default `Documents\Audiobook Library`), each in
  its own folder next to its audiobook; the original file is never changed. Several books can be imported at once.
- **Library window** (Ctrl+L): every book with its status (imported, opened, partly made, audiobook made) and dates,
  kept in `library.json`; the status is read from the book's folder, so it is always true.
- Chapter `.wav` files go into the book's `work` folder and are removed when the audiobook is done.
- Author names written "Surname, First" are put in reading order for file and folder names.

### What you hear
- Every chapter starts with a **spoken heading** ("Chapter One. Oil Drops."), and parts are announced ("Part 1.").
- Quoted extracts are framed by **"Quote." and "End quote."**.
- **Pauses** before and after headings and subheadings, including subheadings written as plain capitals.
- A poem printed line by line is read as **flowing text**.
- Quotation marks are no longer given to the voice (it sometimes made a sound on them).

### The window
- **Search the book** (Ctrl+F) across all sections, with ◀ ▶ and "3 of 41".
- The text is **coloured by kind**: headings, quotations, picture text.
- A bigger **status banner**: errors flash red, warnings amber, successes fade from green.

### Fixed
- The progress bar kept moving after the audiobook was finished.
- Text standing directly in a `<blockquote>` or `<div>` was silently left out (quoted letters, interviews).
- Books whose chapter files have unusual names were read as their preface only (*Turing's Cathedral*);
  numbered chapter titles are now recognised.
- Title pages, copyright pages named after the publisher, untitled contents pages, "Selected Bibliography" and
  "Sources" were read aloud.
- A paragraph with a line break inside it moved the picture-text highlighting to the wrong lines.
- Damaged EPUBs are reported in plain words instead of a Python traceback.

## 0.5.0+dobrejakcyp — 2026-11-10

First release of the fork, based on Audiblez 0.4.9 by Claudio Santini: text cleaning (footnotes, note markers,
index, contents, page numbers, captions), chapter selection by the table of contents, picture text found by its
position, a new window with tool column and book card, instant voice samples, Stop and resume, `Author - Title.m4b`
file names, uv instead of Poetry.
