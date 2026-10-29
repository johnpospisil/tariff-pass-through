"""Check that every X post in x.md fits in 280 characters (URLs count as 23, as X shortens them)."""

import re
import sys
from pathlib import Path

LIMIT, URL_LEN = 280, 23


def posts(md: str) -> list[tuple[str, str]]:
    """(label, text) for each '**n/**' post and the single post."""
    out = []
    for m in re.finditer(r"\*\*(\d+/)\*\*\n(.*?)(?=\n\*\*\d+/\*\*|\n## |\Z)", md, re.S):
        out.append((m.group(1), m.group(2).strip()))
    single = md.split("## Single post", 1)
    if len(single) == 2:
        out.append(("single", single[1].split("\n", 1)[1].strip()))
    return out


def length(text: str) -> int:
    return len(re.sub(r"https?://\S+", "x" * URL_LEN, text))


if __name__ == "__main__":
    md = Path(__file__).with_name("x.md").read_text()
    bad = 0
    for label, text in posts(md):
        n = length(text)
        bad += n > LIMIT
        print(f"{label:>7} {n:4d} {'OVER' if n > LIMIT else 'ok'}")
    sys.exit(1 if bad else 0)
