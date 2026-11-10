"""
voice_library.py - the languages and voices Kokoro offers, and ready-made voice samples.

A VOICE SAMPLE is a short WAV file ("Hello, I am George ...") made ONCE per voice and kept in
the voice_samples folder next to the venv. After that, listening to a voice is instant: no model
loading, no GPU, no internet.

Make all samples in one go (a few minutes; voices that are not on this computer yet are
downloaded once from Hugging Face, about 0.5 MB each). Run from C:\\Users\\lukas\\audiblez:

    venv\\Scripts\\python -m audiblez.voice_library
"""
from dataclasses import dataclass
from pathlib import Path

from audiblez.voices import voices as VOICE_IDS_BY_LANGUAGE

MODEL_NAME = "Kokoro-82M"
KOKORO_REPOSITORY = "hexgrad/Kokoro-82M"  # where Kokoro downloads its model and voices from (Hugging Face)
SAMPLE_RATE = 24000  # Kokoro always produces 24 kHz audio
SAMPLE_FOLDER = Path(__file__).resolve().parent.parent / "voice_samples"


@dataclass(frozen=True)
class Language:
    code: str  # Kokoro's one-letter code; it is also the first letter of every voice of this language
    name: str
    sample_sentence: str  # {name} is replaced by the voice's name
    required_module: str = ""  # extra Python package this language needs, if any

    @property
    def is_installed(self):
        import importlib.util
        return not self.required_module or importlib.util.find_spec(self.required_module) is not None


LANGUAGES = [
    Language("a", "English (American)", "Hello, I am {name}. This is how I sound when I read a book to you."),
    Language("b", "English (British)", "Hello, I am {name}. This is how I sound when I read a book to you."),
    Language("e", "Spanish", "Hola, soy {name}. Así sueno cuando te leo un libro."),
    Language("f", "French", "Bonjour, je suis {name}. Voici ma voix quand je vous lis un livre."),
    Language("h", "Hindi", "नमस्ते, मैं {name} हूँ। जब मैं आपको किताब पढ़कर सुनाता हूँ, तो मेरी आवाज़ ऐसी होती है।"),
    Language("i", "Italian", "Ciao, sono {name}. Ecco come suono quando ti leggo un libro."),
    Language("j", "Japanese", "こんにちは。本を読むとき、私はこんな声です。", required_module="fugashi"),
    Language("p", "Portuguese (Brazil)", "Olá, eu sou {name}. É assim que eu soo quando leio um livro para você."),
    Language("z", "Chinese (Mandarin)", "你好！这就是我为你读书时的声音。"),
]
LANGUAGE_BY_CODE = {language.code: language for language in LANGUAGES}


@dataclass(frozen=True)
class Voice:
    id: str  # Kokoro's name, e.g. "bm_george": b = British English, m = male, george = the name

    @property
    def language(self):
        return LANGUAGE_BY_CODE[self.id[0]]

    @property
    def name(self):
        return self.id.split("_", 1)[1].capitalize()

    @property
    def gender(self):
        return "female" if self.id[1] == "f" else "male"

    @property
    def display_name(self):
        return f"{self.name} ({self.gender})"

    @property
    def is_downloaded(self):
        """True when the voice file is on this computer (Kokoro keeps them in the Hugging Face cache)."""
        from huggingface_hub import try_to_load_from_cache
        return isinstance(try_to_load_from_cache(KOKORO_REPOSITORY, f"voices/{self.id}.pt"), str)


def voices_of(language_code):
    return [Voice(voice_id) for voice_id in VOICE_IDS_BY_LANGUAGE[language_code]]


def all_voices():
    return [voice for language in LANGUAGES for voice in voices_of(language.code)]


class VoiceSampleLibrary:
    """Finds, plays-ready and (if needed) creates the sample WAV file of each voice."""

    def __init__(self, folder=SAMPLE_FOLDER):
        self.folder = Path(folder)
        self._pipelines = {}  # one Kokoro pipeline per language, loaded only when a sample must be made

    def sample_path(self, voice):
        return self.folder / f"{voice.id}.wav"

    def has_sample(self, voice):
        return self.sample_path(voice).exists()

    def create_sample(self, voice):
        """Synthesise the sample sentence with this voice and save it. Slow the first time (model loading)."""
        sentence = voice.language.sample_sentence.format(name=voice.name)
        return self.speak_to_file(sentence, voice, speed=1.0, file_path=self.sample_path(voice))

    def speak_to_file(self, text, voice, speed, file_path):
        """Read `text` aloud with `voice` and save it as a WAV file. Also used for the text preview."""
        import numpy as np
        import soundfile
        pipeline = self._pipeline_for(voice.language.code)
        audio = np.concatenate([chunk.cpu().numpy() if hasattr(chunk, "cpu") else chunk
                                for _, _, chunk in pipeline(text, voice=voice.id, speed=speed)])
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        soundfile.write(file_path, audio, SAMPLE_RATE)
        return Path(file_path)

    def create_missing_samples(self, report=print):
        """Make every sample that does not exist yet. A failing language is reported, not fatal."""
        created, failed = 0, []
        for language in LANGUAGES:
            for voice in voices_of(language.code):
                if self.has_sample(voice):
                    continue
                try:
                    self.create_sample(voice)
                    created += 1
                    report(f"  made   {voice.id:<14} {language.name}")
                except Exception as error:
                    failed.append(voice.id)
                    report(f"  FAILED {voice.id:<14} {language.name}: {type(error).__name__}: {str(error)[:120]}")
        return created, failed

    def _pipeline_for(self, language_code):
        if language_code not in self._pipelines:
            from kokoro import KPipeline
            self._pipelines[language_code] = KPipeline(lang_code=language_code)
        return self._pipelines[language_code]


if __name__ == "__main__":
    import torch
    if torch.cuda.is_available():
        torch.set_default_device("cuda")
    library = VoiceSampleLibrary()
    print(f"Making voice samples in {library.folder}")
    created, failed = library.create_missing_samples()
    print(f"\nDone: {created} new samples, {len(failed)} failed{': ' + ', '.join(failed) if failed else ''}.")
