"""Recognises the toy media of the fake profile: any file called *.fake."""

needs_mount = False


def inspect(path, context):
    if path.suffix != ".fake":
        return None
    return {
        "kind": "installer",
        "variants": [{"index": 1, "name": "Basic"}, {"index": 2, "name": "Plus"}],
        "version": "1.0",
        "build": 1,
        "language": "en-US",
        "arch": "x64",
    }
