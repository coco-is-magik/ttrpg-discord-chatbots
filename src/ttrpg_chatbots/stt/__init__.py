"""Speech-to-text with a measured engine choice.

``resolve_recognizer()`` times every engine that can run on this machine against a
deterministic clip, keeps the fastest loaded, and caches the decision per machine
fingerprint. Pass ``engine=`` (or set ``TTRPG_STT_ENGINE``) to override the race.
"""

from ttrpg_chatbots.stt.probe import Measurement, Resolution, measure, resolve_recognizer
from ttrpg_chatbots.stt.recognizer import EngineUnavailable, SpeechRecognizer
from ttrpg_chatbots.stt.types import SAMPLE_RATE, AudioClip

__all__ = [
    "AudioClip",
    "EngineUnavailable",
    "Measurement",
    "Resolution",
    "SAMPLE_RATE",
    "SpeechRecognizer",
    "measure",
    "resolve_recognizer",
]
