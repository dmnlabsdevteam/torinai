#!/bin/bash
#
# Setup Tor for Dark Web Access
# ==============================
# Installs and configures Tor SOCKS5 proxy for TorinAI dark web detection
#

echo "🧅 Setting up Tor for dark web access..."
echo

# Detect OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    echo "📍 Detected macOS"
    echo "Installing Tor via Homebrew..."

    if ! command -v brew &> /dev/null; then
        echo "❌ Homebrew not installed. Install from https://brew.sh"
        exit 1
    fi

    brew install tor

    echo "Starting Tor service..."
    brew services start tor

    echo "✅ Tor installed and started"
    echo "   SOCKS5 proxy running on localhost:9050"

elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    echo "📍 Detected Linux"
    echo "Installing Tor..."

    sudo apt-get update
    sudo apt-get install -y tor

    echo "Starting Tor service..."
    sudo systemctl start tor
    sudo systemctl enable tor

    echo "✅ Tor installed and started"
    echo "   SOCKS5 proxy running on localhost:9050"

else
    echo "❌ Unsupported OS: $OSTYPE"
    echo "   Please install Tor manually"
    exit 1
fi

echo
echo "🧪 Testing Tor connection..."
sleep 3

# Test Tor connection
if nc -z localhost 9050 2>/dev/null; then
    echo "✅ Tor is running on localhost:9050"
    echo
    echo "🔍 Testing .onion access..."

    # Test with curl through Tor proxy
    if command -v curl &> /dev/null; then
        echo "   Attempting to connect to Tor check service..."
        curl --socks5 localhost:9050 --socks5-hostname localhost:9050 \
             -m 10 https://check.torproject.org/ 2>&1 | grep -i "Congratulations" && \
        echo "   ✅ Tor is working! You can access .onion sites" || \
        echo "   ⚠️  Tor connection test failed, but service is running"
    fi
else
    echo "❌ Tor is not running on localhost:9050"
    echo "   Try: brew services restart tor (Mac) or sudo systemctl restart tor (Linux)"
    exit 1
fi

echo
echo "================================================================"
echo "✅ TOR SETUP COMPLETE"
echo "================================================================"
echo "TorinAI can now access:"
echo "  • Clearnet paste sites (Pastebin, psbdmp.ws, etc.)"
echo "  • .onion hidden services (dark web paste sites, markets)"
echo "  • Dark web breach databases"
echo
echo "Run your dark web detection test now!"
echo "================================================================"
