#!/usr/bin/env bash
# Install the `proxy` command for this user: ~/.local/bin/proxy -> <repo>/proxy
#
# Usage:
#   bash install-cli.sh            create the link (no-op if it already points to this repo)
#   bash install-cli.sh --remove   remove the link, but only if it points to this repo
#
# Host side only: no docker, no ssh. An existing file or a link to another path is never overwritten.
# The rc file (~/.bashrc, ~/.zshrc) is never edited; if ~/.local/bin is not in PATH, the line to add is printed.
set -euo pipefail

SELF="$(readlink -f -- "${BASH_SOURCE[0]}")"
REPO="$(dirname -- "$SELF")"
TARGET="$REPO/proxy"
BIN_DIR="$HOME/.local/bin"
LINK="$BIN_DIR/proxy"

if [ "${1:-}" = "--remove" ]; then
  if [ -L "$LINK" ] && [ "$(readlink -f -- "$LINK")" = "$(readlink -f -- "$TARGET")" ]; then
    rm -- "$LINK"
    echo "Removed: $LINK"
  elif [ -L "$LINK" ] || [ -e "$LINK" ]; then
    echo "Refusing to remove $LINK: it is not a link to this repo ($(readlink -f -- "$LINK" 2>/dev/null || echo "regular file"))." >&2
    exit 1
  else
    echo "Nothing to remove: $LINK does not exist."
  fi
  exit 0
fi

mkdir -p -- "$BIN_DIR"

if [ -L "$LINK" ]; then
  if [ "$(readlink -f -- "$LINK")" = "$(readlink -f -- "$TARGET")" ]; then
    echo "Already installed: $LINK -> $TARGET"
  else
    echo "Refusing to overwrite $LINK: it is a link to $(readlink -f -- "$LINK"). Remove it by hand if you want this repo." >&2
    exit 1
  fi
elif [ -e "$LINK" ]; then
  echo "Refusing to overwrite $LINK: it is a regular file. Move or remove it by hand." >&2
  exit 1
else
  ln -s -- "$TARGET" "$LINK"
  echo "Installed: $LINK -> $TARGET"
fi

case ":$PATH:" in
  *":$BIN_DIR:"*) echo "Now run: proxy status" ;;
  *)
    echo "$BIN_DIR is not in PATH. Add this line to ~/.bashrc or ~/.zshrc, then open a new terminal:"
    echo '  export PATH="$HOME/.local/bin:$PATH"'
    ;;
esac
