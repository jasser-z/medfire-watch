"""Check repository Markdown links and image files without requesting external URLs."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """Validate local targets in the READMEs, notices and product documentation."""
    files = [
        *ROOT.glob("README*.md"),
        ROOT / "THIRD_PARTY_NOTICES.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "CHANGELOG.md",
        *ROOT.glob("docs/**/*.md"),
    ]
    failures = []
    checked = 0
    images = 0
    for source in files:
        text = source.read_text(encoding="utf-8")
        targets = [(match.group(1), match.group(2)) for match in re.finditer(r"(!?)\[[^\]]*\]\(([^)]+)\)", text)]
        targets.extend(("", match.group(1)) for match in re.finditer(r"^\[[^\]]+\]:\s*(\S+)", text, re.MULTILINE))
        for image_marker, raw_target in targets:
            target = raw_target.split(' "', 1)[0].strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            path = source.parent / unquote(parsed.path)
            checked += 1
            if not path.is_file():
                failures.append(f"{source.relative_to(ROOT)}: missing {target}")
            elif image_marker:
                from PIL import Image

                with Image.open(path) as image:
                    image.verify()
                images += 1
    for failure in failures:
        print(failure)
    print(f"Checked {checked} local links, including {images} readable images, in {len(files)} Markdown files.")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
