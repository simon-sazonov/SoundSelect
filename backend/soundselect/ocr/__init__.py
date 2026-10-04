"""Text recognition for photos and scans: getting a picture ready, then reading its words.

``image`` straightens and sizes a photo the same way every time, so the page shown beside a
song is the picture the words were read from. ``engine`` reads the words, each with its box,
on the computer itself (RapidOCR); nothing is sent anywhere.
"""

from .engine import OcrWord, available, read_words
from .image import Prepared, prepare

__all__ = ["OcrWord", "Prepared", "available", "prepare", "read_words"]
