#!/bin/bash
set -e

# Must be run after build.sh
if [ ! -f "dist/BSR_Recon/BSR_Recon" ]; then
    echo "ERROR: Build not found. Run ./build.sh first."
    exit 1
fi

INSTALL_DIR="/opt/BSR_Recon"
ICON_DIR="/usr/share/pixmaps"
DESKTOP_DIR="/usr/share/applications"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  BSR Recon Tool — System Install"
echo "  Requires sudo"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Copy app to /opt
echo "> Installing to $INSTALL_DIR ..."
sudo rm -rf "$INSTALL_DIR"
sudo cp -r dist/BSR_Recon "$INSTALL_DIR"
sudo chmod +x "$INSTALL_DIR/BSR_Recon"

# 2. Copy icon
echo "> Installing icon..."
sudo cp assets/icon.png "$ICON_DIR/bsr_recon.png"

# 3. Create .desktop file
echo "> Creating desktop entry..."
sudo tee "$DESKTOP_DIR/bsr_recon.desktop" > /dev/null << DESKTOP
[Desktop Entry]
Version=1.0
Name=BSR Reconciliation Tool
GenericName=Merchant Reconciliation
Comment=Bunyonyi Safaris Resort - MTN and Airtel merchant reconciliation
Exec=$INSTALL_DIR/BSR_Recon
Icon=bsr_recon
Terminal=false
Type=Application
Categories=Office;Finance;Accounting;
Keywords=reconciliation;merchant;MTN;Airtel;BSR;accounting;
StartupNotify=true
StartupWMClass=BSR_Recon
DESKTOP

# 4. Update desktop database
echo "> Updating application database..."
sudo update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

# 5. Data folders now live in ~/.local/share/BSR_Recon/ (created at first launch)
#    Remove stale data dirs from install location if present
for dir in Transactions Statements Reports Reconciliation Backups; do
    sudo rm -rf "$INSTALL_DIR/$dir"
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Installation complete!"
echo "  Find 'BSR Reconciliation Tool' in your"
echo "  applications menu under Office/Finance"
echo "  Or run: $INSTALL_DIR/BSR_Recon"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
