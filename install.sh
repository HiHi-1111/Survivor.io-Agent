#!/usr/bin/env sh
set -eu

REPO_ZIP="https://github.com/HiHi-1111/Survivor.io/archive/refs/heads/main.zip"
INSTALL_ROOT="$HOME/Survivor.io-Agent"
TMP_ZIP="${TMPDIR:-/tmp}/survivor-io-agent.zip"
TMP_DIR="${TMPDIR:-/tmp}/survivor-io-agent-extract"

printf '%s\n' "Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
UV="$HOME/.local/bin/uv"
if [ ! -x "$UV" ]; then UV="uv"; fi

printf '%s\n' "Downloading Survivor.io agent..."
rm -rf "$TMP_ZIP" "$TMP_DIR"
mkdir -p "$TMP_DIR"
curl -L "$REPO_ZIP" -o "$TMP_ZIP"

if command -v unzip >/dev/null 2>&1; then
  unzip -q "$TMP_ZIP" -d "$TMP_DIR"
else
  printf '%s\n' "The unzip command is required. Install unzip and run this command again."
  exit 1
fi

rm -rf "$INSTALL_ROOT"
mv "$TMP_DIR/Survivor.io-main" "$INSTALL_ROOT"
cd "$INSTALL_ROOT"

printf '%s\n' "Installing Python and dependencies..."
"$UV" python install 3.12
"$UV" sync

printf 'Paste your OPENAI_API_KEY: '
stty -echo
IFS= read -r OPENAI_API_KEY
stty echo
printf '\n'
printf 'Paste your COMPOSIO_API_KEY: '
stty -echo
IFS= read -r COMPOSIO_API_KEY
stty echo
printf '\n'

cat > .env <<EOF
OPENAI_API_KEY=$OPENAI_API_KEY
COMPOSIO_API_KEY=$COMPOSIO_API_KEY
SURVIVOR_USER_ID=survivor_admin_001
EOF
chmod 600 .env

printf '%s\n' "Installation complete. Starting the agent..."
"$UV" run python agent.py
