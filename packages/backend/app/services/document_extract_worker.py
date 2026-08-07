"""Isolated MarkItDown process entrypoint for untrusted Telegram documents."""

import sys
from pathlib import Path

from markitdown import MarkItDown, UnsupportedFormatException


def main() -> int:
    if len(sys.argv) != 3:
        return 2

    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    try:
        converter = MarkItDown(enable_plugins=False)
        content = converter.convert_local(source).text_content.strip()
        if not content:
            print("empty_document", file=sys.stderr)
            return 3
        temporary = destination.with_suffix(f"{destination.suffix}.part")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(destination)
        return 0
    except UnsupportedFormatException:
        print("unsupported_format", file=sys.stderr)
        return 5
    except Exception as exc:
        # Only expose the class; parsers may include document content in messages.
        print(type(exc).__name__, file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
