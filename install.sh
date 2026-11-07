#!/usr/bin/env bash
# ==============================================================================
# Heurix (hx) Official Installer
# https://github.com/Naveen-Boddepalli/heurix
# ==============================================================================

set -euo pipefail

BOLD="$(tput bold 2>/dev/null || printf '')"
GREEN="$(tput setaf 2 2>/dev/null || printf '')"
CYAN="$(tput setaf 6 2>/dev/null || printf '')"
YELLOW="$(tput setaf 3 2>/dev/null || printf '')"
RED="$(tput setaf 1 2>/dev/null || printf '')"
RESET="$(tput sgr0 2>/dev/null || printf '')"

printf "%b" "${CYAN}${BOLD}"
cat << 'EOF'
  _    _                 _      
 | |  | |               (_)     
 | |__| | ___ _   _ _ __ ___  __
 |  __  |/ _ \ | | | '__| \ \/ /
 | |  | |  __/ |_| | |  | |>  < 
 |_|  |_|\___|\__,_|_|  |_/_/\_\
EOF
printf "%b\n" "${RESET}"
echo "${BOLD}Heurix (hx) Installer${RESET} — Deterministic Codebase Scanner & YAML Synthesizer"
echo "------------------------------------------------------------------"

# 1. Check Python installation (>= 3.10)
if ! command -v python3 >/dev/null 2>&1; then
    echo "${RED}Error: python3 is required but not installed.${RESET}"
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "${RED}Error: Python 3.10 or higher is required (found Python ${PY_VERSION}).${RESET}"
    exit 1
fi

INSTALL_DIR="${HOME}/.local/share/heurix"
BIN_DIR="${HOME}/.local/bin"
VENV_DIR="${INSTALL_DIR}/venv"

mkdir -p "${INSTALL_DIR}"
mkdir -p "${BIN_DIR}"

# 2. Check if pipx is available, prefer pipx for clean CLI management
if command -v pipx >/dev/null 2>&1; then
    echo "📦 Detected ${CYAN}pipx${RESET}. Installing / upgrading Heurix..."
    pipx install heurix --force || pipx upgrade heurix
else
    echo "📦 Creating isolated virtual environment in ${CYAN}${VENV_DIR}${RESET}..."
    python3 -m venv "${VENV_DIR}"
    
    echo "⬇️  Installing latest Heurix package from PyPI..."
    "${VENV_DIR}/bin/pip" install --upgrade pip --quiet
    "${VENV_DIR}/bin/pip" install --upgrade heurix --quiet

    ln -sf "${VENV_DIR}/bin/hx" "${BIN_DIR}/hx"
    ln -sf "${VENV_DIR}/bin/heurix" "${BIN_DIR}/heurix"
fi

echo ""
echo "${GREEN}${BOLD}✔ Successfully installed Heurix!${RESET}"
echo "  Binaries linked to: ${CYAN}${BIN_DIR}/hx${RESET} and ${CYAN}${BIN_DIR}/heurix${RESET}"

# 3. PATH check
case ":${PATH}:" in
    *:"${BIN_DIR}":*) ;;
    *)
        echo ""
        echo "${YELLOW}${BOLD}Notice:${RESET} ${BIN_DIR} is not in your current PATH."
        echo "Add the following line to your shell profile (~/.zshrc, ~/.bashrc, etc.):"
        echo "  ${CYAN}export PATH=\"\${HOME}/.local/bin:\${PATH}\"${RESET}"
        echo ""
        ;;
esac

echo "Run ${CYAN}hx --help${RESET} to get started!"
