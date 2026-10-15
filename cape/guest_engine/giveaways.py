"""The one list of words that tell a sample what the machine is.

Long words are unlikely to occur by accident, so they are refused anywhere in the text. Short words
(`cape` is inside `landscape` and `escape`) are refused only as a whole token or path component.
"""

import re

SUBSTRING_GIVEAWAYS = ("tartarus", "sandbox", "malware", "virus", "cuckoo")
TOKEN_GIVEAWAYS = ("cape", "test", "admin")
TOKEN_PREFIX_GIVEAWAYS = ("analy",)

# Capitals not starting a Capitalised word (an acronym), a Capitalised or lower-case word, digits.
_TOKEN = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")


def tokens(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN.findall(text)]


def find_giveaway(text: str) -> str | None:
    """The giveaway word `text` contains, or None. Case-insensitive."""
    lowered = text.lower()
    for word in SUBSTRING_GIVEAWAYS:
        if word in lowered:
            return word
    for token in tokens(text):
        if token in TOKEN_GIVEAWAYS:
            return token
        for prefix in TOKEN_PREFIX_GIVEAWAYS:
            if token.startswith(prefix):
                return prefix
    return None
