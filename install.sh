#!/bin/bash
# Pump Detection System Installation Script

set -e

echo "🚀 Pump Detection System - Installation"
echo "======================================="

PROJECT_DIR="/home/elcrypto/pump_detector"

# 1. Check prerequisites
echo "📋 Checking prerequisites..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed"
    exit 1
fi

# Check PostgreSQL
if ! command -v psql &> /dev/null; then
    echo "❌ PostgreSQL client is not installed"
    exit 1
fi

# Check database connection
if ! psql -d fox_crypto_new -c "SELECT 1" > /dev/null 2>&1; then
    echo "❌ Cannot connect to database fox_crypto_new"
    exit 1
fi

echo "✅ Prerequisites check passed"

# 2. Install Python dependencies
echo ""
echo "📦 Installing Python dependencies..."
pip3 install --user -r $PROJECT_DIR/requirements.txt || echo "⚠️ Some packages may already be installed"

# 3. Setup database (already exists)
echo ""
echo "🗄️ Database setup..."
echo "✅ Schema 'pump' already exists with 10 tables"

# Load OI integration if not exists
if ! psql -d fox_crypto_new -c "\df pump.analyze_oi_patterns" 2>&1 | grep -q "analyze_oi_patterns"; then
    echo "Adding OI integration functions..."
    psql -d fox_crypto_new < $PROJECT_DIR/scripts/oi_integration.sql
fi

# 4. Setup systemd services (for reference)
echo ""
echo "🔧 Systemd service files created in: $PROJECT_DIR/systemd/"
echo "To install systemd services (requires sudo):"
echo "  sudo cp $PROJECT_DIR/systemd/*.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable pump-detector pump-validator pump-spot-futures"
echo "  sudo systemctl start pump-detector pump-validator pump-spot-futures"

# 5. Setup crontab
echo ""
echo "⏰ Crontab configuration..."
echo "To install cron jobs:"
echo "  crontab $PROJECT_DIR/crontab"

# 6. Create necessary directories
echo ""
echo "📁 Creating directories..."
mkdir -p $PROJECT_DIR/{logs,pids,reports,backups}
echo "✅ Directories created"

# 7. Make scripts executable
echo ""
echo "🔨 Making scripts executable..."
chmod +x $PROJECT_DIR/scripts/*.sh
chmod +x $PROJECT_DIR/scripts/*.py
chmod +x $PROJECT_DIR/daemons/*.py
chmod +x $PROJECT_DIR/api/*.py
echo "✅ Scripts are executable"

# 8. Test system
echo ""
echo "🧪 Running system test..."
python3 $PROJECT_DIR/scripts/test_system.py 2>&1 | head -30

# 9. Summary
echo ""
echo "========================================="
echo "✅ INSTALLATION COMPLETE"
echo "========================================="
echo ""
echo "📋 Quick Start Guide:"
echo ""
echo "1. Start daemons manually:"
echo "   $PROJECT_DIR/scripts/manage_daemons.sh start all"
echo ""
echo "2. Monitor system:"
echo "   python3 $PROJECT_DIR/scripts/monitor_dashboard.py"
echo ""
echo "3. Start Web API:"
echo "   python3 $PROJECT_DIR/api/web_api.py"
echo ""
echo "4. Check logs:"
echo "   tail -f $PROJECT_DIR/logs/*.log"
echo ""
echo "5. Test system:"
echo "   python3 $PROJECT_DIR/scripts/test_system.py"
echo ""
echo "📁 System location: $PROJECT_DIR"
echo "📊 Database: fox_crypto_new.pump schema"
echo "📝 Config: $PROJECT_DIR/config/settings.py"
echo ""
echo "For systemd installation (production), run with sudo:"
echo "   sudo $PROJECT_DIR/scripts/install_systemd.sh"
echo ""
echo "🎉 Happy pump hunting!"