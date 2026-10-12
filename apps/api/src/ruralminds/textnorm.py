"""Text normalisation shared by ingestion (book text) and retrieval (student questions).

Both sides must go through the same function, or identical-looking words stop matching.
"""

import unicodedata

# Malayalam "chillu" letters have two encodings that render identically: the old sequence
# consonant + virama + ZWJ (what Tesseract emits) and the atomic code points from Unicode 5.1
# (what phone keyboards type). We store and search the atomic form.
_VIRAMA_ZWJ = "\u0d4d\u200d"
_CHILLU = {
    "\u0d23": "\u0d7a",  # ണ് -> ൺ
    "\u0d28": "\u0d7b",  # ന് -> ൻ
    "\u0d30": "\u0d7c",  # ര് -> ർ
    "\u0d32": "\u0d7d",  # ല് -> ൽ
    "\u0d33": "\u0d7e",  # ള് -> ൾ
    "\u0d15": "\u0d7f",  # ക് -> ൿ
}
_OLD_CHILLU = {base + _VIRAMA_ZWJ: atomic for base, atomic in _CHILLU.items()}

# ZWNJ after a word-final virama only changes how the glyph is drawn, not the word.
_RENDER_ONLY = dict.fromkeys(map(ord, "\u200c"))


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    for old, atomic in _OLD_CHILLU.items():
        text = text.replace(old, atomic)
    return text.translate(_RENDER_ONLY)


# Common Malayalam case/plural endings, longest first. Stripping them from *question* words lets
# a prefix search find the book's form: ഭിംബേഡ്കയുടെ -> ഭിംബേഡ്ക*, ചുമതലകൾ -> ചുമതല*.
_ML_SUFFIXES = sorted(
    [
        "ത്തിന്റെ",
        "ത്തിലെ",
        "ത്തിൽ",
        "ത്തിന്",
        "ിലേക്ക്",
        "ിന്റെ",
        "യുടെ",
        "ുടെ",
        "ന്റെ",
        "യിലെ",
        "യിൽ",
        "ിലെ",
        "ിൽ",
        "ങ്ങൾ",
        "ുകൾ",
        "കൾ",
        "ക്ക്",
        "ിന്",
        "ോട്",
        "യും",
        "ും",
        "യെ",
        "െ",
        "ം",
    ],
    key=len,
    reverse=True,
)
MIN_STEM = 3


def malayalam_stem(word: str) -> str:
    for suffix in _ML_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= MIN_STEM:
            return word[: -len(suffix)]
    return word
