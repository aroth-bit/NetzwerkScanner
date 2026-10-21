"""Einstiegspunkt fuer PyInstaller (NetzwerkScanner.exe) und direkten Start."""

import sys

from netscanner.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
