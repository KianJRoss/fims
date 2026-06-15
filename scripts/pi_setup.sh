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

# ── 6. Force display resolution for headless VNC ─────────────────────────────
# Without a monitor attached, Pi defaults to 640x480. Force 1920x1080.
log "Configuring headless display resolution for VNC..."

# Pi OS Bookworm uses /boot/firmware/config.txt; older uses /boot/config.txt
if [ -f /boot/firmware/config.txt ]; then
    CONFIG=/boot/firmware/config.txt
else
    CONFIG=/boot/config.txt
fi

# Only add if not already set
if ! grep -q "hdmi_force_hotplug" "$CONFIG"; then
    sudo tee -a "$CONFIG" > /dev/null << 'EOF'

# Force HDMI output and resolution even with no monitor attached (for VNC)
hdmi_force_hotplug=1
hdmi_group=2
hdmi_mode=82
# hdmi_mode=82 = 1920x1080 60Hz
# Change to hdmi_mode=85 for 1280x720, or 87 for custom below
#hdmi_cvt=1920 1080 60 6 0 0 0
EOF
    log "Headless resolution set to 1920x1080 in $CONFIG."
else
    log "hdmi_force_hotplug already set in $CONFIG, skipping."
fi

# For Pi OS Bookworm: also set via wayfire/wlr if Wayland is in use
if command -v wlr-randr &>/dev/null 2>&1; then
    warn "Wayland detected — resolution is set via $CONFIG and takes effect on reboot."
fi

# ── 7. VNC setup ─────────────────────────────────────────────────────────────
log "Configuring RealVNC server..."

# Enable via raspi-config (works on all Pi OS Desktop versions)
if command -v raspi-config &>/dev/null; then
    sudo raspi-config nonint do_vnc 0 2>/dev/null && log "VNC enabled via raspi-config." || true
fi

# Enable and start the RealVNC systemd service
if systemctl list-unit-files 2>/dev/null | grep -q vncserver-x11-serviced; then
    sudo systemctl enable vncserver-x11-serviced
    sudo systemctl restart vncserver-x11-serviced
    log "RealVNC service enabled and started."
elif systemctl list-unit-files 2>/dev/null | grep -q vncserver-virtuald; then
    # Newer Pi OS uses vncserver-virtuald for virtual displays
    sudo systemctl enable vncserver-virtuald
    sudo systemctl restart vncserver-virtuald
    log "RealVNC virtual display service enabled and started."
else
    warn "RealVNC service not found by expected name. Trying manual enable..."
    sudo systemctl enable --now "$(systemctl list-unit-files | grep -i vnc | awk '{print $1}' | head -1)" 2>/dev/null || \
        warn "Could not auto-enable VNC service. Run: sudo raspi-config → Interface Options → VNC"
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
