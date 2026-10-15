"""Name and password generators a profile selects by name (`identity.*.generator`)."""

import random
import string
from collections.abc import Callable

from guest_engine.giveaways import find_giveaway

FIRST_NAMES = (
    "Adam", "Alice", "Andrew", "Anna", "Benjamin", "Brian", "Caroline", "Charles", "Chloe",
    "Daniel", "David", "Diana", "Edward", "Elena", "Emily", "Emma", "Eric", "Frank", "George",
    "Grace", "Hannah", "Harry", "Helen", "Henry", "Isabel", "Jack", "James", "Jason", "Jennifer",
    "John", "Joseph", "Julia", "Karen", "Kevin", "Laura", "Lucas", "Lucy", "Maria", "Mark",
    "Martin", "Mary", "Matthew", "Michael", "Michelle", "Nancy", "Nathan", "Nicole", "Oliver",
    "Olivia", "Patrick", "Paul", "Peter", "Rachel", "Rebecca", "Richard", "Robert", "Ryan", "Sarah",
    "Samuel", "Sophie", "Stephen", "Steven", "Susan", "Thomas", "Timothy", "Victoria", "William",
    "Zoe", "Kate", "Linda", "Megan", "Natalie", "Philip", "Simon", "Tom", "Vincent", "Walter",
)  # fmt: skip

PASSWORD_LENGTH = 16
SPECIAL_CHARACTERS = "-_.+=@#%"
PASSWORD_ALPHABET = string.ascii_letters + string.digits + SPECIAL_CHARACTERS
MACHINE_NAME_SUFFIX_LENGTH = 7
UPPER_ALNUM = string.ascii_uppercase + string.digits
MACHINE_NAME_PREFIXES = ("DESKTOP", "LAPTOP")
HOSTNAME_FORM_FACTORS = ("pc", "laptop", "desktop")
FOLDER_NAME_LENGTH = 8
MAX_ATTEMPTS = 50


def _first_name(rng: random.Random) -> str:
    return rng.choice(FIRST_NAMES)


def _first_name_lower(rng: random.Random) -> str:
    return _first_name(rng).lower()


def _computer_name(rng: random.Random) -> str:
    suffix = "".join(rng.choices(UPPER_ALNUM, k=MACHINE_NAME_SUFFIX_LENGTH))
    return f"{rng.choice(MACHINE_NAME_PREFIXES)}-{suffix}"


def _hostname(rng: random.Random) -> str:
    return f"{_first_name_lower(rng)}-{rng.choice(HOSTNAME_FORM_FACTORS)}"


def _folder_name(rng: random.Random) -> str:
    return "".join(rng.choices(string.ascii_lowercase, k=FOLDER_NAME_LENGTH))


def _password(rng: random.Random) -> str:
    one_of_each = [
        rng.choice(string.ascii_lowercase),
        rng.choice(string.ascii_uppercase),
        rng.choice(string.digits),
        rng.choice(SPECIAL_CHARACTERS),
    ]
    rest = rng.choices(PASSWORD_ALPHABET, k=PASSWORD_LENGTH - len(one_of_each))
    characters = one_of_each + rest
    rng.shuffle(characters)
    return "".join(characters)


GENERATORS: dict[str, Callable[[random.Random], str]] = {
    "first_name": _first_name,
    "first_name_lower": _first_name_lower,
    "computer_name": _computer_name,
    "hostname": _hostname,
    "folder_name": _folder_name,
    "password": _password,
}
GENERATOR_NAMES = frozenset(GENERATORS)


def generate(generator: str, rng: random.Random | None = None) -> str:
    """A value from the named generator that contains no giveaway; `rng` makes it deterministic."""
    source = rng or random.SystemRandom()
    for _ in range(MAX_ATTEMPTS):
        value = GENERATORS[generator](source)
        if find_giveaway(value) is None:
            return value
    raise RuntimeError(f"generator {generator!r} kept producing giveaways")
