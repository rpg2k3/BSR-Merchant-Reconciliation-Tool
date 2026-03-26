#!/bin/bash
set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  BSR Merchant Reconciliation Tool"
echo "  Build Script"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Check Python
python3 --version || { echo "ERROR: Python3 not found"; exit 1; }

# 2. Install/upgrade dependencies
echo "> Installing dependencies..."
pip install pyqt6 pandas openpyxl numpy anthropic pyinstaller --quiet --break-system-packages 2>/dev/null \
  || pip install pyqt6 pandas openpyxl numpy anthropic pyinstaller --quiet

# 3. Clean previous build
echo "> Cleaning previous build..."
rm -rf dist/ build/ __pycache__/

# 4. Run PyInstaller
echo "> Building with PyInstaller..."
pyinstaller BSR_Recon.spec --clean --noconfirm

# 5. Create data folder structure next to executable
echo "> Creating data folders..."
mkdir -p dist/BSR_Recon/Transactions/MTN
mkdir -p dist/BSR_Recon/Transactions/Airtel
mkdir -p dist/BSR_Recon/Statements
mkdir -p dist/BSR_Recon/Reports/Karibu/MTN
mkdir -p dist/BSR_Recon/Reports/Karibu/Airtel
mkdir -p dist/BSR_Recon/Reconciliation
mkdir -p dist/BSR_Recon/Backups

# 6. Add .gitkeep files so folders are not empty
touch dist/BSR_Recon/Transactions/MTN/.gitkeep
touch dist/BSR_Recon/Transactions/Airtel/.gitkeep
touch dist/BSR_Recon/Statements/.gitkeep
touch dist/BSR_Recon/Reports/Karibu/MTN/.gitkeep
touch dist/BSR_Recon/Reports/Karibu/Airtel/.gitkeep
touch dist/BSR_Recon/Reconciliation/.gitkeep
touch dist/BSR_Recon/Backups/.gitkeep

# 7. Create a launcher script next to the executable
cat > dist/BSR_Recon/launch.sh << 'LAUNCHER'
#!/bin/bash
cd "$(dirname "$0")"
./BSR_Recon
LAUNCHER
chmod +x dist/BSR_Recon/launch.sh

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ Build complete!"
echo "  Run with: ./dist/BSR_Recon/BSR_Recon"
echo "  Or:       ./dist/BSR_Recon/launch.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
