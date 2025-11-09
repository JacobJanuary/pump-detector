#!/bin/bash

# Pump Detection System - Daemon Manager
# Manages detector and validator daemons

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DAEMON_DIR="$PROJECT_DIR/daemons"
LOG_DIR="$PROJECT_DIR/logs"
PID_DIR="$PROJECT_DIR/pids"

# Create necessary directories
mkdir -p "$LOG_DIR" "$PID_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to display usage
usage() {
    echo "Usage: $0 {start|stop|restart|status|logs} {all|detector|validator}"
    echo
    echo "Commands:"
    echo "  start     - Start daemon(s)"
    echo "  stop      - Stop daemon(s)"
    echo "  restart   - Restart daemon(s)"
    echo "  status    - Check daemon(s) status"
    echo "  logs      - Tail daemon logs"
    echo
    echo "Daemons:"
    echo "  all       - Both detector and validator"
    echo "  detector  - Pump detector daemon only"
    echo "  validator - Signal validator daemon only"
    echo
    echo "Examples:"
    echo "  $0 start all        # Start both daemons"
    echo "  $0 status detector  # Check detector status"
    echo "  $0 logs validator   # View validator logs"
    exit 1
}

# Check if daemon is running
is_running() {
    local daemon_name=$1
    local pid_file="$PID_DIR/$daemon_name.pid"

    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ps -p $pid > /dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# Start a daemon
start_daemon() {
    local daemon_name=$1
    local daemon_script="$DAEMON_DIR/${daemon_name}_daemon.py"
    local pid_file="$PID_DIR/$daemon_name.pid"
    local log_file="$LOG_DIR/$daemon_name.log"

    if is_running $daemon_name; then
        echo -e "${YELLOW}⚠️  $daemon_name daemon is already running${NC}"
        return 1
    fi

    if [ ! -f "$daemon_script" ]; then
        echo -e "${RED}❌ Daemon script not found: $daemon_script${NC}"
        return 1
    fi

    echo -e "${GREEN}Starting $daemon_name daemon...${NC}"

    # Start daemon in background
    nohup python3 "$daemon_script" >> "$log_file" 2>&1 &
    local pid=$!

    # Save PID
    echo $pid > "$pid_file"

    # Wait a moment to check if it started successfully
    sleep 2

    if is_running $daemon_name; then
        echo -e "${GREEN}✅ $daemon_name daemon started successfully (PID: $pid)${NC}"
        return 0
    else
        echo -e "${RED}❌ Failed to start $daemon_name daemon${NC}"
        rm -f "$pid_file"
        return 1
    fi
}

# Stop a daemon
stop_daemon() {
    local daemon_name=$1
    local pid_file="$PID_DIR/$daemon_name.pid"

    if ! is_running $daemon_name; then
        echo -e "${YELLOW}⚠️  $daemon_name daemon is not running${NC}"
        return 1
    fi

    local pid=$(cat "$pid_file")
    echo -e "${YELLOW}Stopping $daemon_name daemon (PID: $pid)...${NC}"

    # Send SIGTERM for graceful shutdown
    kill -TERM $pid 2>/dev/null

    # Wait for process to stop
    local count=0
    while [ $count -lt 30 ] && is_running $daemon_name; do
        sleep 1
        count=$((count + 1))
    done

    # Force kill if still running
    if is_running $daemon_name; then
        echo -e "${YELLOW}Force killing $daemon_name daemon...${NC}"
        kill -9 $pid 2>/dev/null
        sleep 1
    fi

    rm -f "$pid_file"
    echo -e "${GREEN}✅ $daemon_name daemon stopped${NC}"
    return 0
}

# Restart a daemon
restart_daemon() {
    local daemon_name=$1
    stop_daemon $daemon_name
    sleep 2
    start_daemon $daemon_name
}

# Check daemon status
check_status() {
    local daemon_name=$1
    local pid_file="$PID_DIR/$daemon_name.pid"

    if is_running $daemon_name; then
        local pid=$(cat "$pid_file")
        echo -e "${GREEN}✅ $daemon_name daemon is running (PID: $pid)${NC}"

        # Show process info
        ps -p $pid -o pid,vsz,rss,pcpu,pmem,etime,comm

        # Show recent log activity
        local log_file="$LOG_DIR/$daemon_name.log"
        if [ -f "$log_file" ]; then
            echo -e "\n${YELLOW}Recent log entries:${NC}"
            tail -5 "$log_file"
        fi
    else
        echo -e "${RED}❌ $daemon_name daemon is not running${NC}"

        # Check for crash
        local log_file="$LOG_DIR/$daemon_name.log"
        if [ -f "$log_file" ]; then
            echo -e "\n${YELLOW}Last log entries:${NC}"
            tail -10 "$log_file" | grep -E "(ERROR|CRITICAL|Fatal)"
        fi
    fi
}

# Show logs
show_logs() {
    local daemon_name=$1
    local log_file="$LOG_DIR/$daemon_name.log"

    if [ ! -f "$log_file" ]; then
        echo -e "${RED}Log file not found: $log_file${NC}"
        return 1
    fi

    echo -e "${GREEN}Tailing $daemon_name logs (Ctrl+C to stop)...${NC}"
    tail -f "$log_file"
}

# Main script logic
if [ $# -ne 2 ]; then
    usage
fi

COMMAND=$1
TARGET=$2

# Determine which daemons to operate on
case $TARGET in
    all)
        DAEMONS=("detector" "validator")
        ;;
    detector)
        DAEMONS=("detector")
        ;;
    validator)
        DAEMONS=("validator")
        ;;
    *)
        echo -e "${RED}Invalid daemon: $TARGET${NC}"
        usage
        ;;
esac

# Execute command
case $COMMAND in
    start)
        for daemon in "${DAEMONS[@]}"; do
            start_daemon $daemon
        done
        ;;
    stop)
        for daemon in "${DAEMONS[@]}"; do
            stop_daemon $daemon
        done
        ;;
    restart)
        for daemon in "${DAEMONS[@]}"; do
            restart_daemon $daemon
        done
        ;;
    status)
        echo -e "${GREEN}=== Pump Detection System Status ===${NC}\n"
        for daemon in "${DAEMONS[@]}"; do
            check_status $daemon
            echo
        done
        ;;
    logs)
        if [ ${#DAEMONS[@]} -gt 1 ]; then
            echo -e "${YELLOW}Please specify a single daemon for logs${NC}"
            exit 1
        fi
        show_logs ${DAEMONS[0]}
        ;;
    *)
        echo -e "${RED}Invalid command: $COMMAND${NC}"
        usage
        ;;
esac

exit 0