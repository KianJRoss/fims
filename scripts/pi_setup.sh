#!/bin/bash
# FIMS Raspberry Pi 4B Setup Script
# Run this once via SSH after a fresh Pi OS install.
# Usage: bash pi_setup.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[FIMS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERR]${NC} $1"; exit 1; }

log "=== FIMS Pi Setup ==="
log "Running as: $(whoami) on $(hostname)"

# ── 1. System update ─────────────────────────────────────────────────────────
log "Updating system packages..."
sudo apt-get update -qq
sudo apt-get upgrade -y -qq

# ── 2. Install dependencies ───────────────────────────────────────────────────
log "Installing dependencies..."
sudo apt-get install -y -qq \
    curl git ca-certificates gnupg lsb-release \
    apt-transport-https software-properties-common

# ── 3. Install Docker ─────────────────────────────────────────────────────────
if command -v docker &>/dev/null; then
    log "Docker already installed: $(docker --version)"
else
    log "Installing Docker..."
    curl -fsSL https://get.docker.com | sudo sh
    log "Docker installed: $(docker --version)"
fi

# Add current user to docker group (no sudo needed for docker commands)
if ! groups | grep -q docker; then
    sudo usermod -aG docker "$USER"
    warn "Added $USER to docker group. This takes effect on next login."
    warn "If docker commands fail, run: newgrp docker"
fi

# ── 4. Verify Docker Compose ──────────────────────────────────────────────────
log "Docker Compose version: $(docker compose version)"

# ── 5. Enable swap (helps during the first docker build) ─────────────────────
SWAPFILE=/swapfile
if [ ! -f "$SWAPFILE" ]; then
    log "Creating 2GB swapfile (helps during docker build)..."
    sudo fallocate -l 2G "$SWAPFILE"
    sudo chmod 600 "$SWAPFILE"
    sudo mkswap "$SWAPFILE"
    sudo swapon "$SWAPFILE"
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    log "Swap enabled."
else
    log "Swapfile already exists, skipping."
fi

# ── 6. VNC setup ─────────────────────────────────────────────────────────────
log "Checking VNC status..."

if systemctl list-units --type=service 2>/dev/null | grep -q vncserver-x11-serviced; then
    # RealVNC (comes with Pi OS Desktop)
    if sudo systemctl is-enabled vncserver-x11-serviced &>/dev/null; then
        log "RealVNC (Pi OS Desktop) is already enabled."
    else
        log "Enabling RealVNC server..."
        sudo systemctl enable vncserver-x11-serviced
        sudo systemctl start vncserver-x11-serviced
        log "RealVNC enabled and started."
    fi
elif command -v vncserver &>/dev/null; then
    log "VNC server found (non-RealVNC). Assuming already configured."
else
    warn "No VNC server found. Installing TigerVNC for headless use..."
    sudo apt-get install -y -qq tigervnc-standalone-server
    # Create a minimal VNC startup
    mkdir -p ~/.vnc
    cat > ~/.vnc/xstartup << 'EOF'
#!/bin/sh
xsetroot -solid grey
x-terminal-emulator -geometry 80x24+10+10 -ls -title "$VNCDESKTOP Desktop" &
x-window-manager &
EOF
    chmod +x ~/.vnc/xstartup
    warn "TigerVNC installed. Set a password with: vncpasswd"
    warn "Then start with: vncserver :1 -geometry 1280x720 -depth 24"
fi

# ── 7. Configure VNC to survive reboot ───────────────────────────────────────
# Ensure RealVNC auto-starts if present
if command -v raspi-config &>/dev/null; then
    sudo raspi-config nonint do_vnc 0 2>/dev/null && log "VNC enabled via raspi-config." || true
fi

# ── 8. Clone / update FIMS repo ──────────────────────────────────────────────
REPO_DIR="$HOME/fims"
REPO_URL="https://github.com/KianJRoss/fims.git"

if [ -d "$REPO_DIR/.git" ]; then
    log "FIMS repo already exists, pulling latest..."
    git -C "$REPO_DIR" pull
else
    log "Cloning FIMS repo..."
    git clone "$REPO_URL" "$REPO_DIR"
fi

# ── 9. Start FIMS stack ───────────────────────────────────────────────────────
log "Building and starting FIMS (this takes 5-15 min on first run)..."
cd "$REPO_DIR"

# Use newgrp to apply docker group without re-login
newgrp docker << 'DOCKERCMD'
cd ~/fims
docker compose pull --quiet || true
docker compose up -d --build
DOCKERCMD

log "Waiting for services to be healthy..."
sleep 10
docker compose ps

# ── 10. Auto-start on boot (systemd) ─────────────────────────────────────────
log "Setting up FIMS auto-start service..."
sudo tee /etc/systemd/system/fims.service > /dev/null << EOF
[Unit]
Description=FIMS Fireworks Store Management System
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$REPO_DIR
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300
User=$USER
Group=docker

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable fims.service
log "FIMS will now auto-start on every boot."

# ── 11. Print connection info ─────────────────────────────────────────────────
IP=$(hostname -I | awk '{print $1}')
log ""
log "=========================================="
log "  FIMS Setup Complete!"
log "=========================================="
log "  Web UI:    http://$IP"
log "  API:       http://$IP/api/docs"
log "  VNC:       $IP:5900  (or use RealVNC Viewer)"
log "  SSH:       ssh $(whoami)@$IP"
log ""
log "  To check status:  docker compose -C ~/fims ps"
log "  To view logs:     docker compose -C ~/fims logs -f"
log "  To update:        cd ~/fims && git pull && docker compose up -d --build"
log "=========================================="
