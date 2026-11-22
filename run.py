#!/usr/bin/env python3
"""Start Kiosk Player. Gebruik `run.py set-password` om het wachtwoord te wijzigen."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.server import main  # noqa: E402

if __name__ == "__main__":
    main()
