#!/bin/bash
# Spindle Installation Script (by Petacomm)

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${CYAN}${BOLD}"
printf '%s\n' " ____  ____ ___ _   _ ____  _     _____ "
printf '%s\n' "/ ___||  _ \\_ _| \\ | |  _ \\| |   | ____|"
printf '%s\n' "\\___ \\| |_) | ||  \\| | | | | |   |  _|  "
printf '%s\n' " ___) |  __/| || |\\  | |_| | |___| |___ "
printf '%s\n' "|____/|_|  |___|_| \\_|____/|_____|_____|"
echo -e "${NC}"
echo "  by Petacomm — AI-Powered Linux Management"
echo ""

echo -n "  Checking Python3... "
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}not found!${NC}"
    echo "  Installing Python3..."
    sudo apt-get update -qq && sudo apt-get install -y python3 python3-pip
else
    VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    echo -e "${GREEN}✓ $VERSION${NC}"
fi

echo -n "  Checking pip... "
if ! command -v pip3 &>/dev/null; then
    echo -e "${YELLOW}installing...${NC}"
    sudo apt-get install -y python3-pip -qq
else
    echo -e "${GREEN}✓${NC}"
fi

echo -n "  Installing dependencies... "
pip3 install rich psutil -q --break-system-packages 2>/dev/null || pip3 install rich psutil -q
echo -e "${GREEN}✓${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo -n "  Installing Spindle... "

sudo mkdir -p /usr/local/lib/spindle
sudo cp -r "$SCRIPT_DIR/core" /usr/local/lib/spindle/
sudo cp "$SCRIPT_DIR/spindle.py" /usr/local/lib/spindle/

sudo tee /usr/local/bin/spindle > /dev/null <<'EOF'
#!/usr/bin/env python3
import sys
sys.path.insert(0, '/usr/local/lib/spindle')
from spindle import main
main()
EOF

sudo chmod +x /usr/local/bin/spindle
echo -e "${GREEN}✓${NC}"

echo -n "  Testing... "
if spindle help &>/dev/null; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}error!${NC}"
    exit 1
fi

echo ""
echo -e "  ${GREEN}✓ Spindle installed successfully!${NC}"
echo ""
echo "  Usage:"
echo -e "  ${YELLOW}spindle status${NC}           System status"
echo -e "  ${YELLOW}spindle health${NC}           Health score"
echo -e "  ${YELLOW}spindle ls services${NC}      List services"
echo -e "  ${YELLOW}spindle login${NC}            Set API key"
echo -e "  ${YELLOW}spindle info${NC}             About Spindle"
echo -e "  ${YELLOW}spindle -r \"...\"${NC}         Ask AI"
echo -e "  ${YELLOW}spindle config${NC}           Show/change model"
echo -e "  ${YELLOW}spindle clear${NC}            Clear conversation memory"
echo -e "  ${YELLOW}spindle help${NC}             All commands"
echo ""
