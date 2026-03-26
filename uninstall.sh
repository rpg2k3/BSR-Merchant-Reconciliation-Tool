#!/bin/bash
echo "> Removing BSR Reconciliation Tool..."
sudo rm -rf /opt/BSR_Recon
sudo rm -f /usr/share/pixmaps/bsr_recon.png
sudo rm -f /usr/share/applications/bsr_recon.desktop
sudo update-desktop-database /usr/share/applications 2>/dev/null || true
echo "✓ Uninstalled successfully."
