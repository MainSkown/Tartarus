"""The one list of words that tell a sample what the machine is.

Long words are unlikely to occur by accident, so they are refused anywhere in the text. Short words
(`cape` is inside `landscape` and `escape`) are refused only as a whole token or path component.
Ordinary words that contain a long one (`antivirus`) are listed in LEGITIMATE_WORDS and ignored.
"""

import re

SUBSTRING_GIVEAWAYS = ("tartarus", "sandbox", "malware", "virus", "cuckoo")
TOKEN_GIVEAWAYS = ("cape", "test", "admin")
TOKEN_PREFIX_GIVEAWAYS = ("analy",)
# A guest's own security service is named "... Antivirus Service" in English.
LEGITIMATE_WORDS = ("antivirus",)

# Capitals not starting a Capitalised word (an acronym), a Capitalised or lower-case word, digits.
_TOKEN = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")


_WORD = re.compile(r"[^\W_]+")


def tokens(text: str) -> list[str]:
    """Words of `text`. Camel-case is split only in plain ASCII words: cutting a word such as the
    Polish `testów` at its accented letter would leave a bare `test` that is not in the text."""
    found: list[str] = []
    for word in _WORD.findall(text):
        found.extend(_TOKEN.findall(word) if word.isascii() else [word])
    return [token.lower() for token in found]


def lowered_without_legitimate_words(text: str) -> str:
    """`text` in lower case with each legitimate word replaced by a space, so that what is left
    of `antivirusvirus` is still a bare `virus` and the parts around a word are not glued."""
    lowered = text.lower()
    for word in LEGITIMATE_WORDS:
        lowered = lowered.replace(word, " ")
    return lowered


def find_giveaway(text: str) -> str | None:
    """The giveaway word `text` contains, or None. Case-insensitive."""
    searchable = lowered_without_legitimate_words(text)
    for word in SUBSTRING_GIVEAWAYS:
        if word in searchable:
            return word
    for token in tokens(text):
        if token in TOKEN_GIVEAWAYS:
            return token
        for prefix in TOKEN_PREFIX_GIVEAWAYS:
            if token.startswith(prefix):
                return prefix
    return None
