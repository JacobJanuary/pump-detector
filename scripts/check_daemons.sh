#!/bin/bash
# Health check script for pump detection daemons

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_DIR="$PROJECT_DIR/pids"
LOG_DIR="$PROJECT_DIR/logs"

# Check detector daemon
check_daemon() {
    local daemon_name=$1
    local pid_file="$PID_DIR/$daemon_name.pid"

    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ! ps -p $pid > /dev/null 2>&1; then
            echo "$(date): $daemon_name daemon crashed, restarting..." >> "$LOG_DIR/health_check.log"
            # Restart using manage script
            "$PROJECT_DIR/scripts/manage_daemons.sh" start $daemon_name
        fi
    else
        echo "$(date): $daemon_name PID file missing, starting daemon..." >> "$LOG_DIR/health_check.log"
        "$PROJECT_DIR/scripts/manage_daemons.sh" start $daemon_name
    fi
}

# Check all daemons
check_daemon "detector"
check_daemon "validator"

# Check database connection
psql -d fox_crypto_new -c "SELECT 1" > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "$(date): Database connection failed!" >> "$LOG_DIR/health_check.log"
fi