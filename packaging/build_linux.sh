#!/usr/bin/env bash
# Build do SIGMA Studio para Linux x86_64: PyInstaller → tarball com instalador.
#
#     packaging/build_linux.sh [--sem-testes]
#
# Sai em dist/sigma-studio-<versão>-linux-x86_64.tar.gz, que contém a pasta
# congelada, instalar.sh e desinstalar.sh. A instalação é por usuário (~/.local),
# sem root: o app só precisa da porta serial, e para isso o que falta é o grupo
# dialout, não privilégio de administrador.
set -euo pipefail

cd "$(dirname "$0")/.."
raiz="$PWD"
versao="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/ia4294/__init__.py)"
alvo="sigma-studio-${versao}-linux-x86_64"
py="${PYTHON:-$raiz/.venv/bin/python}"
echo "== SIGMA Studio ${versao} → Linux ==  $raiz"

[ -x "$py" ] || { echo "sem interpretador em $py (defina PYTHON=...)" >&2; exit 1; }
"$py" -m PyInstaller --version >/dev/null 2>&1 || "$py" -m pip install -q "pyinstaller>=6.6"

if [ "${1:-}" != "--sem-testes" ]; then
  QT_QPA_PLATFORM=offscreen IA4294_REDUCED_MOTION=1 "$py" -m pytest -q
fi

"$py" packaging/make_icon.py
rm -rf build dist
"$py" -m PyInstaller --noconfirm packaging/sigma-studio.spec
[ -x dist/sigma-studio/sigma-studio ] || { echo "o PyInstaller não gerou o executável" >&2; exit 1; }

# fumaça: abre no simulador, desenha e sai sozinho
QT_QPA_PLATFORM=offscreen IA4294_REDUCED_MOTION=1 IA4294_HOME="$(mktemp -d)" \
  timeout 180 dist/sigma-studio/sigma-studio --sim --sim-speed 0.02 --screenshot dist/fumaca.png
[ -s dist/fumaca.png ] || { echo "o executável abriu mas não desenhou a janela" >&2; exit 1; }
echo "fumaça ok: dist/fumaca.png"

# o pacote: a pasta congelada + os dois scripts + o ícone
rm -rf "dist/$alvo"
mkdir -p "dist/$alvo"
cp -a dist/sigma-studio "dist/$alvo/app"
cp packaging/sigma-studio.png "dist/$alvo/"
cp packaging/instalar.sh packaging/desinstalar.sh "dist/$alvo/"
chmod +x "dist/$alvo/instalar.sh" "dist/$alvo/desinstalar.sh"
cp README.md "dist/$alvo/LEIAME.md"
tar -C dist -czf "dist/${alvo}.tar.gz" "$alvo"
rm -rf "dist/$alvo"

echo "pacote: dist/${alvo}.tar.gz  ($(du -h "dist/${alvo}.tar.gz" | cut -f1))"
echo "instala com:  tar xzf ${alvo}.tar.gz && ${alvo}/instalar.sh"
