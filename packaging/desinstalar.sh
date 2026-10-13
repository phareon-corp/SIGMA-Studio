#!/usr/bin/env bash
# Remove o que instalar.sh colocou. Não toca em configuração nem em dados:
# ~/.config/ia4294, ~/.local/state/ia4294 e ~/Documentos/ia4294 ficam.
set -euo pipefail

prefixo="${PREFIX:-$HOME/.local/share}"
dados="${XDG_DATA_HOME:-$HOME/.local/share}"
rm -rf "$prefixo/sigma-studio"
rm -f "$HOME/.local/bin/sigma-studio"
rm -f "$dados/applications/sigma-studio.desktop"
rm -f "$dados/icons/hicolor/256x256/apps/sigma-studio.png"
echo "SIGMA Studio removido. Configuração, logs e dados exportados continuam onde estavam."
