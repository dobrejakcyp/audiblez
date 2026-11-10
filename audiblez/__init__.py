"""
audiblez - generate audiobooks from EPUB e-books with the Kokoro-82M voice model.

This is the dobrejakcyp fork of Claudio Santini's audiblez (github.com/santinic/audiblez).
The "+dobrejakcyp" part of the version marks it as a fork build, so it can never be confused
with an official audiblez release (PyPI also refuses such versions, so it cannot be published
under the original name by accident).

Keep __version__ the same as `version` in pyproject.toml; a self-check in
test_cleaning_rules.py fails if they differ.
"""
__version__ = "0.5.0+dobrejakcyp"
