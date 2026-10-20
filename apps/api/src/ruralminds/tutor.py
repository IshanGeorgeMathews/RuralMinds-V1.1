"""What kind of help the student wants, which language to answer in, and the answer's parts.

A study helper has to do more than find a paragraph: "explain it simpler", "give an example",
"tell it as a story" and "quiz me" are normal ways students ask. The mode changes the
instruction we add to the student's message (the system prompt stays the same, so
llama-server keeps reusing its cached prefix). Instruction words are removed before the
textbook search, so "explain as a story why Harappa declined" searches for "Harappa declined".
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path


@cache
def load_prompt(name: str) -> str:
    """Prompt file body after the '---' line; the version line stays out of the prompt."""
    path = Path(__file__).parent / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8").split("\n---\n", 1)[1].strip()


# "solve" comes only from the "Solve step by step" chip, never from detect_mode, so typed
# questions (and the frozen eval) keep the tutor path (numerical.py, DECISIONS 2026-10-20).
MODES = ("explain", "simpler", "example", "story", "quiz", "summary", "solve")

# Phrases that ask for a kind of help, in English, Malayalam and Manglish. Order matters:
# the first matching mode wins ("explain as a story" is a story, not a plain explanation).
_MODE_PATTERNS: list[tuple[str, str]] = [
    ("summary", r"summar|summery|overview|in short|key points|saaramsham|churukk|ചുരുക്ക|സംഗ്രഹ|സാരാംശ"),
    ("quiz", r"quiz|test me|ask me questions|chodyangal chodikk|ചോദ്യങ്ങൾ ചോദിക്ക|പരീക്ഷിക്ക"),
    ("story", r"\bstory\b|\bstories\b|\bkadha\b|\bkatha\b|കഥ"),
    ("example", r"example|real[- ]?(?:world|life)|daily[- ]?life|everyday|udaharan|ഉദാഹരണ"),
    (
        "simpler",
        (
            r"simpl|easy words|easier|didn'?t understand|did not understand|don'?t understand"
            r"|not clear|manass?ilay?illa|manassilakunnilla|മനസ്സിലായില്ല|മനസ്സിലാകുന്നില്ല|ലളിതമായി"
        ),
    ),
]
_COMPILED = [(mode, re.compile(pattern, re.IGNORECASE)) for mode, pattern in _MODE_PATTERNS]

# Words that only describe the request, not the topic. Removed before searching the book.
_INSTRUCTION_WORDS = re.compile(
    r"\b(?:please|pls|can you|could you|explain|explanation|describe|tell me|tell|give me|give"
    r"|using|use|with|an?|as|in|simple|simpler|simply|easy|easier|words?|story|stories|example"
    r"|examples|real[- ]?(?:world|life)|daily[- ]?life|everyday|ignore the text|ignore the book|because|i"
    r"|didn'?t|did not|don'?t|understand|understood|yet|again|more|for me|me|to|learn|fast"
    r"|quickly|summari[sz]e|summary|entire|whole|quiz|test|questions?|kadha|katha|udaharanam"
    r"|paranju tharamo|parayamo|onnu|manass?ilay?illa|this|that|it|chapter|lesson|on|about)\b",
    re.IGNORECASE,
)

_CHAPTER_NUMBER = re.compile(r"(?:chapter|ch\.?|adhyayam|അധ്യായം)\s*(\d{1,2})", re.IGNORECASE)


def detect_mode(question: str) -> str:
    for mode, pattern in _COMPILED:
        if pattern.search(question):
            return mode
    return "explain"


def topic_query(question: str) -> str:
    """The question without request words, for the textbook search."""
    cleaned = _INSTRUCTION_WORDS.sub(" ", question)
    # Drop what is left of the request: lone punctuation such as ".", "-" or "?".
    return " ".join(word for word in cleaned.split() if any(ch.isalnum() for ch in word))


def chapter_in(question: str) -> int | None:
    match = _CHAPTER_NUMBER.search(question)
    return int(match.group(1)) if match else None


# ---------- language ----------
# Common Malayalam words typed in Latin letters. Two hits (or one hit plus a Malayalam case
# ending) mark the question as Manglish rather than English.
_MANGLISH_WORDS = frozenset(
    [
        "enthanu",
        "entha",
        "enthu",
        "enthaanu",
        "aanu",
        "anu",
        "alle",
        "ennu",
        "ennal",
        "engane",
        "enganeya",
        "evide",
        "evideyanu",
        "aaranu",
        "aara",
        "aaru",
        "eppol",
        "eppozhanu",
        "ethu",
        "ethokke",
        "ethanu",
        "enthokke",
        "enthukond",
        "enthukondu",
        "undayirunnu",
        "undu",
        "illa",
        "paranju",
        "parayamo",
        "tharamo",
        "onnu",
        "kurichu",
        "patti",
        "ulla",
        "ninnum",
        "vendi",
        "manassilayilla",
        "manasilayilla",
        "cheyyunnathu",
        "cheythu",
        "cheyyuka",
        "nammude",
        "avarude",
        "ivide",
        "athinte",
        "ithinte",
        "prathyekatha",
        "karanam",
        "karanangal",
    ]
)
_MANGLISH_ENDINGS = re.compile(r"[a-z]{3,}(?:inte|ude|ile|il|kal|ukal|ennu|aanu|anu)\b")
_LATIN_WORD = re.compile(r"[A-Za-z']+")
# English words that happen to end like Malayalam case endings.
_ENGLISH_ENDING_OK = frozenset({"until", "evil", "civil", "soil", "oil", "coil", "april", "pupil"})


def question_language(text: str) -> str:
    """'ml' (Malayalam script), 'manglish' (Malayalam in Latin letters) or 'en'."""
    malayalam = sum("\u0d00" <= ch <= "\u0d7f" for ch in text)
    latin = sum(ch.isascii() and ch.isalpha() for ch in text)
    if malayalam > latin:
        return "ml"
    words = [word.lower() for word in _LATIN_WORD.findall(text)]
    hits = sum(word in _MANGLISH_WORDS for word in words)
    endings = sum(
        bool(_MANGLISH_ENDINGS.fullmatch(word)) for word in words if word not in _ENGLISH_ENDING_OK
    )
    if hits >= 2 or (hits >= 1 and endings >= 1) or (hits >= 1 and len(words) <= 3):
        return "manglish"
    return "en"


def answer_language(setting: str, question: str) -> str:
    """The student's "Answer in" setting; Auto follows the question (Manglish -> Malayalam)."""
    if setting in ("en", "ml"):
        return setting
    return "en" if question_language(question) == "en" else "ml"


# ---------- what we add to the student's message per mode ----------
_INSTRUCTIONS = {
    "explain": "Explain this simply, in your own words.",
    "simpler": (
        "The student did not understand the last explanation. Explain it again much more simply,"
        " in a different way, with very short sentences, and add an EXAMPLE."
    ),
    "example": "Explain this simply, then give one EXAMPLE from everyday life in Kerala.",
    "story": (
        "Explain this as a short, simple story a 13-year-old would enjoy. Every fact about the"
        " topic in the story must come from the sources, with its marker."
    ),
    "quiz": (
        "Write 3 short questions to test the student on this topic, as a numbered list, each"
        ' question followed by its source marker. Then a line starting "ANSWERS:" and the 3'
        " short answers as a numbered list, each with its source marker. Do not write EXAMPLE"
        " or CHECK."
    ),
    "summary": 'Give the main ideas from these sources as 4 to 6 short "- " bullet points.',
    # Used only when the calculator could not solve the problem: explain the method, and leave
    # the numbers to the student rather than let a small model do arithmetic.
    "solve": (
        "The student wants to solve this problem. Explain the rule or method from the sources"
        " step by step. Do not calculate anything and do not write any number that is not in"
        " the question. Never say what the result is or which choice is right (which is first,"
        " bigger or faster): the student will work it out."
    ),
}
# A cap, not a target: the prompt asks for ~90 words (EN) / ~60 (ML). Malayalam needs
# about 3x the tokens per word, so the caps leave room for it.
MAX_TOKENS = {
    "explain": 320,
    "simpler": 320,
    "example": 360,
    "story": 420,
    "quiz": 320,
    "summary": 320,
    "solve": 320,
}


def instruction(mode: str) -> str:
    return _INSTRUCTIONS.get(mode, _INSTRUCTIONS["explain"])


# ---------- the answer's parts ----------
_LABEL = re.compile(
    r"^[ \t]*[*_#]*[ \t]*(EXAMPLE|ഉദാഹരണം|CHECK|Check yourself|സ്വയം പരിശോധിക്കാം|ANSWERS|ഉത്തരങ്ങൾ)"
    r"[ \t]*[*_]*[ \t]*[:：][*_]*",
    re.IGNORECASE | re.MULTILINE,
)
_LABEL_KIND = {
    "example": "example",
    "ഉദാഹരണം": "example",
    "check": "check",
    "check yourself": "check",
    "സ്വയം പരിശോധിക്കാം": "check",
    "answers": "answers",
    "ഉത്തരങ്ങൾ": "answers",
}


@dataclass
class Sections:
    explanation: str
    example: str = ""
    check: str = ""
    answers: str = ""  # quiz answers, shown only when the student taps


def split_sections(text: str) -> Sections:
    """Split the model's text at the EXAMPLE: / CHECK: / ANSWERS: labels (any order)."""
    matches = list(_LABEL.finditer(text))
    sections = Sections(explanation=text[: matches[0].start()] if matches else text)
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        kind = _LABEL_KIND[match.group(1).lower()]
        body = text[match.end() : end].strip()
        current = getattr(sections, kind)
        setattr(sections, kind, f"{current}\n{body}".strip() if current else body)
    sections.explanation = sections.explanation.strip()
    return sections


# The model saying, in its own words, that the book does not have the answer. Treated like
# NOT_IN_TEXTBOOK, because the rest of such an answer comes from the model's own knowledge.
_ADMITS_MISSING = re.compile(
    r"\b(?:sources?|texts?|textbook|book|passages?)\s+(?:do|does|did)\s*(?:not|n't)\s+"
    r"(?:\w+\s+)?(?:say|state|mention|provide|give|contain|tell|talk|explain|include)"
    r"|\bnot\s+(?:mentioned|given|found|stated|provided)\s+in\s+the\s+(?:sources?|text|book)"
    r"|ഉറവിടങ്ങളിൽ\s*(?:ഇല്ല|പറയുന്നില്ല)|പുസ്തകത്തിൽ\s*(?:ഇല്ല|പറയുന്നില്ല|പരാമർശിക്കുന്നില്ല)",
    re.IGNORECASE,
)


def admits_missing(text: str) -> bool:
    return bool(_ADMITS_MISSING.search(text))


def wrong_script(text: str, language: str) -> bool:
    """True when an answer that should be Malayalam or English is mostly in another script.
    Small models sometimes drift into Hindi (Devanagari); such an answer is not shown."""
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 20:
        return False
    malayalam = sum(0x0D00 <= ord(ch) <= 0x0D7F for ch in letters)
    latin = sum(ch.isascii() for ch in letters)
    expected = malayalam if language == "ml" else latin
    # Malayalam answers keep English names (Harappa, BCE), so only a clear minority fails.
    return expected / len(letters) < 0.5


def third_script(text: str) -> bool:
    """Any letter that is neither Latin nor Malayalam: the single stray Korean or Telugu word
    that wrong_script's majority rule lets through (2/93 dev answers, 19 Oct). Measured by the
    eval; preventing it at generation time is the W4 grammar change."""
    return any(
        ch.isalpha()
        and not ch.isascii()
        and not 0x00C0 <= ord(ch) <= 0x024F
        and not 0x0D00 <= ord(ch) <= 0x0D7F
        for ch in text
    )


# ---------- time-sensitive questions (ANSWER_POLICY §4) ----------
# "Who is the Chief Minister now?" The book names office-holders as of its printing, if at all,
# so the honest answer is "ask your teacher". Neither the gate nor the model refused it on dev.
# All three parts are needed, so "What are the powers of the President?" is still answered.
_ASKS_WHO = re.compile(
    r"\b(?:who|whom|whose|name|aaranu|aaraanu|aara|aaru|aarokke)\b|ആര്|ആരാണ്|ആരൊക്കെ|പേര്",
    re.IGNORECASE,
)
_NOW = re.compile(
    r"\b(?:now|current|currently|present|presently|today|this year|these days|at the moment"
    r"|latest|ippo|ippol|ippozhathe|ippozhulla|ippozhatthe|nilavil|nilavile|innathe)\b"
    r"|ഇപ്പോൾ|ഇപ്പോഴത്തെ|ഇപ്പോഴുള്ള|നിലവിലെ|നിലവിൽ|ഇന്നത്തെ",
    re.IGNORECASE,
)
_OFFICE = re.compile(
    r"\b(?:president|prime minister|pm|chief minister|cm|minister|governor|chief justice"
    r"|speaker|vice president|election commissioner|collector|mayor|mla|mp"
    r"|rashtrapathi|pradhana ?manthri|mukhya ?manthri|manthri)\b"
    r"|രാഷ്ട്രപതി|പ്രധാനമന്ത്രി|മുഖ്യമന്ത്രി|മന്ത്രി|ഗവർണർ|ചീഫ് ജസ്റ്റിസ്|സ്പീക്കർ",
    re.IGNORECASE,
)


def time_sensitive(question: str) -> bool:
    """Asks who holds an office now: refused without a model call (ANSWER_POLICY §4)."""
    return all(pattern.search(question) for pattern in (_ASKS_WHO, _NOW, _OFFICE))
