#!/usr/bin/env bash
# Instala o SIGMA Studio para o usuário atual, sem root.
#
#   ./instalar.sh            → ~/.local/share/sigma-studio + atalho no menu
#   PREFIX=/opt ./instalar.sh → outro lugar (precisa de permissão de escrita)
set -euo pipefail

aqui="$(cd "$(dirname "$0")" && pwd)"
prefixo="${PREFIX:-$HOME/.local/share}"
destino="$prefixo/sigma-studio"
bin="$HOME/.local/bin"
desktop="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icones="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"

echo "SIGMA Studio → $destino"
rm -rf "$destino"
mkdir -p "$destino" "$bin" "$desktop" "$icones"
cp -a "$aqui/app/." "$destino/"
cp "$aqui/sigma-studio.png" "$icones/sigma-studio.png"

ln -sf "$destino/sigma-studio" "$bin/sigma-studio"

cat > "$desktop/sigma-studio.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=SIGMA Studio
GenericName=Analisador de impedância
Comment=Controle e aquisição do HP/Agilent 4294A via AR488
Exec=$destino/sigma-studio
Icon=sigma-studio
Terminal=false
Categories=Science;Engineering;Electronics;
Keywords=4294A;impedância;GPIB;AR488;dielétrico;
StartupWMClass=sigma-studio
DESKTOP

command -v update-desktop-database >/dev/null && update-desktop-database "$desktop" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t -f "${icones%/256x256/apps}" 2>/dev/null || true

echo "pronto: 'sigma-studio' no terminal, ou o atalho no menu."
case ":$PATH:" in
  *":$bin:"*) ;;
  *) echo "aviso: $bin não está no PATH; o atalho do menu funciona do mesmo jeito." ;;
esac
if ! id -nG "$USER" | tr ' ' '\n' | grep -qx dialout; then
  echo
  echo "a porta da interface AR488 é root:dialout e você não está no grupo:"
  echo "    sudo usermod -aG dialout $USER     (e faça logout/login)"
fi
