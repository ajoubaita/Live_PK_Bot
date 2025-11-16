#!/bin/bash

###############################################################################
# Arbitrage Trading Bot - Startup Script
###############################################################################
# This script launches the arbitrage trading bot in a production environment.
# It handles environment setup, logging, and process management.
#
# Usage:
#   ./startup.sh                    # Start in foreground
#   ./startup.sh --background       # Start in tmux background
#   ./startup.sh --daemon           # Start as systemd service
#   ./startup.sh --stop             # Stop running instance
#   ./startup.sh --status           # Check status
#   ./startup.sh --logs             # View logs
###############################################################################

set -e  # Exit on error

# Configuration
BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$BOT_DIR/venv"
LOG_DIR="/var/log/arbitrage-bot"
DATA_DIR="/var/lib/arbitrage-bot"
PID_FILE="/var/run/arbitrage-bot.pid"
TMUX_SESSION="arbitrage-bot"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

###############################################################################
# Helper Functions
###############################################################################

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_requirements() {
    log_info "Checking requirements..."

    # Check Python version
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed"
        exit 1
    fi

    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
    log_info "Python version: $PYTHON_VERSION"

    # Check virtual environment
    if [ ! -d "$VENV_DIR" ]; then
        log_warning "Virtual environment not found. Creating..."
        python3 -m venv "$VENV_DIR"
    fi

    # Check .env file
    if [ ! -f "$BOT_DIR/.env" ]; then
        log_error ".env file not found. Copy .env.production and configure it."
        exit 1
    fi

    log_info "Requirements check passed ✓"
}

setup_directories() {
    log_info "Setting up directories..."

    # Create log directory
    if [ ! -d "$LOG_DIR" ]; then
        sudo mkdir -p "$LOG_DIR"
        sudo chown -R $USER:$USER "$LOG_DIR"
        log_info "Created log directory: $LOG_DIR"
    fi

    # Create data directory
    if [ ! -d "$DATA_DIR" ]; then
        sudo mkdir -p "$DATA_DIR"
        sudo chown -R $USER:$USER "$DATA_DIR"
        log_info "Created data directory: $DATA_DIR"
    fi

    log_info "Directories setup complete ✓"
}

activate_venv() {
    log_info "Activating virtual environment..."
    source "$VENV_DIR/bin/activate"
}

install_dependencies() {
    log_info "Installing/updating dependencies..."
    activate_venv
    pip install --upgrade pip > /dev/null 2>&1
    pip install -r "$BOT_DIR/requirements.txt" > /dev/null 2>&1
    log_info "Dependencies installed ✓"
}

check_status() {
    # Check if running in tmux
    if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
        log_info "Bot is running in tmux session: $TMUX_SESSION"
        return 0
    fi

    # Check PID file
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            log_info "Bot is running (PID: $PID)"
            return 0
        else
            log_warning "PID file exists but process not found"
            rm -f "$PID_FILE"
        fi
    fi

    log_info "Bot is not running"
    return 1
}

start_foreground() {
    log_info "Starting bot in foreground mode..."
    check_requirements
    setup_directories
    activate_venv

    log_info "Launching trading bot..."
    log_info "Press Ctrl+C to stop"
    echo ""

    cd "$BOT_DIR"
    python3 main.py
}

start_background() {
    log_info "Starting bot in background (tmux)..."

    if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
        log_error "Bot is already running in tmux session: $TMUX_SESSION"
        log_info "Use './startup.sh --stop' to stop it first"
        exit 1
    fi

    check_requirements
    setup_directories

    log_info "Creating tmux session: $TMUX_SESSION"

    # Start bot in tmux
    tmux new-session -d -s "$TMUX_SESSION" -c "$BOT_DIR" \
        "source $VENV_DIR/bin/activate && python3 main.py"

    sleep 2

    if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
        log_info "Bot started successfully ✓"
        log_info ""
        log_info "Useful commands:"
        log_info "  - View logs: tmux attach -t $TMUX_SESSION"
        log_info "  - Detach: Press Ctrl+B then D"
        log_info "  - Stop: ./startup.sh --stop"
        log_info "  - Status: ./startup.sh --status"
    else
        log_error "Failed to start bot"
        exit 1
    fi
}

stop_bot() {
    log_info "Stopping bot..."

    # Stop tmux session
    if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
        tmux send-keys -t "$TMUX_SESSION" C-c
        sleep 2
        tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true
        log_info "Stopped tmux session"
    fi

    # Stop PID-based process
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            kill "$PID"
            sleep 2
            if ps -p "$PID" > /dev/null 2>&1; then
                kill -9 "$PID"
            fi
            log_info "Stopped process (PID: $PID)"
        fi
        rm -f "$PID_FILE"
    fi

    log_info "Bot stopped ✓"
}

view_logs() {
    log_info "Viewing logs (Ctrl+C to exit)..."
    echo ""

    if [ -f "$LOG_DIR/trading_bot.log" ]; then
        tail -f "$LOG_DIR/trading_bot.log"
    elif [ -f "$BOT_DIR/trading_bot.log" ]; then
        tail -f "$BOT_DIR/trading_bot.log"
    else
        log_error "Log file not found"
        exit 1
    fi
}

show_help() {
    cat << EOF
Arbitrage Trading Bot - Startup Script

Usage: $0 [OPTION]

Options:
    (no option)         Start bot in foreground mode (Ctrl+C to stop)
    --background        Start bot in tmux background session
    --daemon            Run as systemd daemon (requires setup)
    --stop              Stop running bot
    --status            Check if bot is running
    --logs              View log files in real-time
    --install           Install dependencies
    --help              Show this help message

Examples:
    $0                      # Start in foreground
    $0 --background         # Start in tmux
    $0 --stop               # Stop bot
    $0 --status             # Check status
    $0 --logs               # View logs

For tmux session:
    - Attach: tmux attach -t $TMUX_SESSION
    - Detach: Press Ctrl+B then D
    - Kill: tmux kill-session -t $TMUX_SESSION

Logs location: $LOG_DIR/trading_bot.log
Data location: $DATA_DIR/trading_bot.db

EOF
}

###############################################################################
# Main Script
###############################################################################

case "${1:-}" in
    --background|-b)
        start_background
        ;;
    --stop|-s)
        stop_bot
        ;;
    --status|-st)
        check_status
        ;;
    --logs|-l)
        view_logs
        ;;
    --install|-i)
        check_requirements
        install_dependencies
        ;;
    --help|-h)
        show_help
        ;;
    "")
        start_foreground
        ;;
    *)
        log_error "Unknown option: $1"
        show_help
        exit 1
        ;;
esac

exit 0
