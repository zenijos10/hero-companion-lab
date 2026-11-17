"""Context keys from the command line: "k1,k2,..." or "@file" (one key per
line, or comma-separated). A wave of ~1,900 keys is ~170k characters, far past
Windows' 32k command-line limit, so long key lists travel as a file."""


def parse(arg):
    """The keys an --keys argument names, in order, without blanks."""
    text = arg or ""
    if text.startswith("@"):
        with open(text[1:], encoding="utf-8") as f:
            text = f.read()
    return [k.strip() for k in text.replace("\n", ",").split(",") if k.strip()]


def write(path, keys):
    """A key file `parse("@" + path)` reads back."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(keys) + "\n")
