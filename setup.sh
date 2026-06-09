#!/bin/bash
# Julius Health — one-time Mac setup script
# Run this once: bash setup.sh

set -e
echo ""
echo "Julius Health — Setup"
echo "======================================"
echo ""

# ── 1. Create project folder ─────────────────────────────────────────────────
HEALTH_DIR="$HOME/julius-health"
mkdir -p "$HEALTH_DIR"
cp sync.py "$HEALTH_DIR/sync.py"
echo "✓ Created $HEALTH_DIR"

# ── 2. Collect credentials ───────────────────────────────────────────────────
echo ""
echo "Enter your Garmin Connect credentials:"
read -p "  Garmin email:    " GARMIN_EMAIL
read -s -p "  Garmin password: " GARMIN_PASSWORD
echo ""
echo ""
echo "Enter your GitHub personal access token:"
echo "  (github.com → Settings → Developer settings → Personal access tokens → Tokens classic)"
echo "  Required scopes: repo"
read -s -p "  GitHub token: " GITHUB_TOKEN
echo ""

# ── 3. Save credentials to .env file (not in repo) ───────────────────────────
ENV_FILE="$HEALTH_DIR/.env"
cat > "$ENV_FILE" << EOF
GARMIN_EMAIL=$GARMIN_EMAIL
GARMIN_PASSWORD=$GARMIN_PASSWORD
GITHUB_TOKEN=$GITHUB_TOKEN
GITHUB_REPO=juliuskvx/julius-health
EOF
chmod 600 "$ENV_FILE"
echo "✓ Credentials saved to $ENV_FILE (private, chmod 600)"

# ── 4. Create wrapper script that loads .env ─────────────────────────────────
WRAPPER="$HEALTH_DIR/run_sync.sh"
cat > "$WRAPPER" << 'WRAPPER_EOF'
#!/bin/bash
set -a
source "$HOME/julius-health/.env"
set +a
/opt/homebrew/bin/python3 "$HOME/julius-health/sync.py" >> "$HOME/julius-health/sync.log" 2>&1
WRAPPER_EOF
chmod +x "$WRAPPER"
echo "✓ Created run_sync.sh wrapper"

# ── 5. Schedule 9am daily via launchd ────────────────────────────────────────
PLIST="$HOME/Library/LaunchAgents/com.julius.health.plist"
cat > "$PLIST" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.julius.health</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$HOME/julius-health/run_sync.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>9</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>RunAtLoad</key>
  <false/>
  <key>StandardOutPath</key>
  <string>$HOME/julius-health/sync.log</string>
  <key>StandardErrorPath</key>
  <string>$HOME/julius-health/sync.log</string>
</dict>
</plist>
PLIST_EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "✓ Scheduled: sync will run every day at 9:00am"

# ── 6. Test run ───────────────────────────────────────────────────────────────
echo ""
echo "Running sync now to test your credentials..."
echo ""
set -a
source "$ENV_FILE"
set +a
/opt/homebrew/bin/python3 "$HEALTH_DIR/sync.py"

echo ""
echo "======================================"
echo "Setup complete!"
echo ""
echo "Your dashboard: https://juliuskvx.github.io/julius-health"
echo "Sync log:       $HOME/julius-health/sync.log"
echo "Next auto-sync: tomorrow at 9:00am"
echo ""
