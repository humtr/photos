from __future__ import annotations

import sys

from photos.cli import main as cli_main
from photos.gui import main


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "--cli":
        raise SystemExit(cli_main(argv[1:]))
    raise SystemExit(main(argv))
