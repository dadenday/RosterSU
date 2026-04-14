#!/bin/bash
# ==========================================
# RosterSU Auto-Update Script
# ==========================================
# Usage: ./update.sh [--yes]
#
# Features:
# - Check for updates
# - Backup current code
# - Pull latest changes
# - Install new dependencies
# - Rollback on failure
#
# Options:
#   --yes    Skip confirmation prompt (for non-interactive use)
# ==========================================

set -e

# Parse arguments
AUTO_CONFIRM=false
for arg in "$@"; do
    case "$arg" in
        --yes|-y) AUTO_CONFIRM=true ;;
    esac
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${SCRIPT_DIR}/.update_backup"
LOG_FILE="${SCRIPT_DIR}/update.log"

# Functions
log() {
    echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

success() {
    echo -e "${GREEN}[$(date '+%H:%M:%S')] ✓${NC} $1" | tee -a "$LOG_FILE"
}

warning() {
    echo -e "${YELLOW}[$(date '+%H:%M:%S')] ⚠${NC} $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[$(date '+%H:%M:%S')] ✗${NC} $1" | tee -a "$LOG_FILE"
}

info() {
    echo -e "${CYAN}[$(date '+%H:%M:%S')] ℹ${NC} $1" | tee -a "$LOG_FILE"
}

# Check if we're in a git repository
check_git_repo() {
    if [ ! -d "${SCRIPT_DIR}/.git" ]; then
        error "Not a git repository!"
        error "Please clone the repository first:"
        echo "  git clone https://github.com/dadenday/RosterSU.git"
        exit 1
    fi
}

# Check internet connectivity
check_internet() {
    if ! ping -c 1 -W 3 github.com &> /dev/null; then
        error "No internet connection detected"
        error "Please check your network and try again"
        exit 1
    fi
}

# Check for updates
check_updates() {
    log "Checking for updates..."
    
    cd "$SCRIPT_DIR"
    
    # Fetch latest changes without merging
    git fetch origin
    
    # Get current and remote commit hashes
    LOCAL_COMMIT=$(git rev-parse HEAD)
    REMOTE_COMMIT=$(git rev-parse origin/$(git rev-parse --abbrev-ref HEAD))
    
    if [ "$LOCAL_COMMIT" = "$REMOTE_COMMIT" ]; then
        success "You're already on the latest version!"
        exit 0
    fi
    
    # Get version info
    LOCAL_VERSION=$(cat VERSION 2>/dev/null || echo "unknown")
    REMOTE_VERSION=$(git show origin/$(git rev-parse --abbrev-ref HEAD):VERSION 2>/dev/null || echo "unknown")
    
    # Show what's new
    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}📦 Update Available!${NC}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "Current Version: ${YELLOW}${LOCAL_VERSION}${NC}"
    echo -e "Latest Version:  ${GREEN}${REMOTE_VERSION}${NC}"
    echo ""
    echo -e "${BOLD}📝 Recent Changes:${NC}"
    git log HEAD..origin/$(git rev-parse --abbrev-ref HEAD) --oneline --no-merges --pretty=format:"${CYAN}  •${NC} %s" | head -20
    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    
    # Ask for confirmation
    if [ "$AUTO_CONFIRM" = true ]; then
        info "Auto-confirming update (--yes flag)"
    else
        read -p "Do you want to update? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            info "Update cancelled"
            exit 0
        fi
    fi

    return 0
}

# Create backup
create_backup() {
    log "Creating backup..."
    
    # Remove old backup if exists
    if [ -d "$BACKUP_DIR" ]; then
        rm -rf "$BACKUP_DIR"
    fi
    
    # Create new backup
    mkdir -p "$BACKUP_DIR"
    
    # Backup important files (exclude large/temporary files)
    rsync -a \
        --exclude='.git' \
        --exclude='__pycache__' \
        --exclude='.pytest_cache' \
        --exclude='.ruff_cache' \
        --exclude='*.pyc' \
        --exclude='.update_backup' \
        --exclude='update.log' \
        --exclude='roster_history.db' \
        --exclude='roster_history.db-wal' \
        --exclude='roster_history.db-shm' \
        --exclude='quarantine' \
        --exclude='processed_archive' \
        "${SCRIPT_DIR}/" "$BACKUP_DIR/"
    
    success "Backup created at: $BACKUP_DIR"
}

# Rollback to backup
rollback() {
    error "Update failed! Rolling back to previous version..."
    
    if [ -d "$BACKUP_DIR" ]; then
        # Restore from backup
        rsync -a \
            --exclude='.git' \
            "${BACKUP_DIR}/" "${SCRIPT_DIR}/"
        success "Rollback completed!"
    else
        error "No backup found! Manual recovery may be needed."
    fi
    
    exit 1
}

# Pull updates
pull_updates() {
    log "Pulling latest changes..."
    
    cd "$SCRIPT_DIR"
    
    # Pull with rebase to keep history clean
    if git pull origin $(git rev-parse --abbrev-ref HEAD) --rebase; then
        success "Successfully pulled latest changes!"
    else
        error "Failed to pull updates"
        rollback
    fi
}

# Install dependencies
install_dependencies() {
    log "Checking dependencies..."
    
    cd "$SCRIPT_DIR"
    
    if [ -f "requirements.txt" ]; then
        # Check if pip is available
        if ! command -v pip3 &> /dev/null && ! command -v pip &> /dev/null; then
            warning "pip not found, skipping dependency installation"
            warning "Please run manually: pip3 install -r requirements.txt"
            return 0
        fi
        
        # Install/upgrade dependencies
        if pip3 install -q -r requirements.txt 2>>"$LOG_FILE" || \
           pip install -q -r requirements.txt 2>>"$LOG_FILE"; then
            success "Dependencies installed successfully!"
        else
            warning "Some dependencies may have failed to install"
            warning "Check the log file for details: $LOG_FILE"
        fi
    fi
}

# Clean up old cache
cleanup() {
    log "Cleaning up..."
    
    # Remove Python cache
    find "${SCRIPT_DIR}" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "${SCRIPT_DIR}" -name "*.pyc" -delete 2>/dev/null || true
    
    success "Cleanup completed!"
}

# Show final status
show_status() {
    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}✓ Update completed successfully!${NC}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    
    # Show new version
    if [ -f "${SCRIPT_DIR}/VERSION" ]; then
        info "Current version: $(cat ${SCRIPT_DIR}/VERSION)"
    fi
    
    # Show recent commits
    echo ""
    info "Latest changes:"
    cd "$SCRIPT_DIR"
    git log --oneline -5 --no-merges --pretty=format:"${CYAN}  •${NC} %s"
    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    
    # Restart reminder
    info "💡 Remember to restart the app to apply updates!"
    echo "   Stop the current server (Ctrl+C) and run:"
    echo "   ${GREEN}python3 roster_single_user.py${NC}"
    echo ""
}

# Main execution
main() {
    echo ""
    echo -e "${BOLD}╔═══════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║${NC}       ${CYAN}RosterSU Auto-Update${NC}                  ${BOLD}║${NC}"
    echo -e "${BOLD}╚═══════════════════════════════════════════╝${NC}"
    echo ""
    
    # Initialize log
    echo "=== Update started at $(date) ===" > "$LOG_FILE"
    
    # Pre-flight checks
    check_git_repo
    check_internet
    
    # Check for updates
    check_updates
    
    # Create backup before updating
    create_backup
    
    # Pull updates
    pull_updates
    
    # Install dependencies
    install_dependencies
    
    # Clean up
    cleanup
    
    # Show success message
    show_status
    
    # Keep backup for a few days
    log "Backup kept at: $BACKUP_DIR (safe to delete if everything works)"
}

# Run main function
main "$@"
