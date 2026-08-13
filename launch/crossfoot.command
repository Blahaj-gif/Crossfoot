#!/bin/bash
# Double-click this (macOS). It sets Crossfoot up the first time and opens the
# window every time after, so nobody has to learn a terminal to look at their
# own receipts.
#
# Deliberately a readable script rather than a signed app bundle: this program
# reads your bank statements, and a file you can open in TextEdit is a better
# trust proposition than a binary you are asked to trust.
cd "$(dirname "$0")/.." || exit 1

if [ ! -x ".venv/bin/python" ]; then
  echo "Setting up Crossfoot. This happens once and takes a minute."
  python3 -m venv .venv || {
    echo
    echo "Python 3 is not installed. Get it from https://python.org/downloads"
    echo "then run this again."
    read -r -p "Press return to close."
    exit 1
  }
  ./.venv/bin/python -m pip install --quiet --upgrade pip
  ./.venv/bin/python -m pip install --quiet -e ".[ui]"
fi

echo "Opening Crossfoot in your browser. Close this window to stop it."
./.venv/bin/python -m crossfoot.cli
