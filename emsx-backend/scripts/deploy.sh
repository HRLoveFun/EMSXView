#!/bin/bash
# EMSX Trading Platform - Deployment Script
# Usage: ./deploy.sh [install|start|stop|restart|status|logs|update|backup]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
ENV_FILE="$PROJECT_DIR/.env"

# Functions
print_header() {
    echo -e "${BLUE}============================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}============================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    # Support both 'docker compose' (v2) and 'docker-compose' (v1)
    if docker compose version &> /dev/null 2>&1; then
        COMPOSE_CMD="docker compose"
    elif command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
    else
        print_error "Docker Compose is not installed."
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        print_error "Docker daemon is not running. Please start Docker."
        exit 1
    fi
    
    print_success "Docker environment check passed (using: $COMPOSE_CMD)"
}

check_env_file() {
    if [ ! -f "$ENV_FILE" ]; then
        print_warning ".env file not found, creating from template..."
        cp "$PROJECT_DIR/.env.example" "$ENV_FILE"
        print_warning "Please edit $ENV_FILE with your configuration before continuing"
        exit 1
    fi
    print_success "Environment file found"
}

check_bloomberg() {
    print_header "Checking Bloomberg Terminal Connection"
    
    # Get Bloomberg host from env
    BLOOMBERG_HOST=$(grep BLOOMBERG_HOST "$ENV_FILE" | cut -d '=' -f2 | tr -d ' ')
    BLOOMBERG_PORT=$(grep BLOOMBERG_PORT "$ENV_FILE" | cut -d '=' -f2 | tr -d ' ')
    
    echo "Bloomberg Host: $BLOOMBERG_HOST"
    echo "Bloomberg Port: $BLOOMBERG_PORT"
    
    # Try to connect to Bloomberg port
    if timeout 5 bash -c "cat < /dev/null > /dev/tcp/$BLOOMBERG_HOST/$BLOOMBERG_PORT" 2>/dev/null; then
        print_success "Bloomberg Terminal is reachable"
    else
        print_error "Cannot connect to Bloomberg Terminal at $BLOOMBERG_HOST:$BLOOMBERG_PORT"
        echo "Please ensure:"
        echo "  1. Bloomberg Terminal is running and logged in"
        echo "  2. API access is enabled in Bloomberg"
        echo "  3. Firewall allows connection on port $BLOOMBERG_PORT"
        exit 1
    fi
}

install() {
    print_header "EMSX Trading Platform - Installation"
    
    check_docker
    
    # Create necessary directories
    mkdir -p "$PROJECT_DIR/logs"
    
    # Check/create .env file
    check_env_file
    
    # Build Docker images (frontend + backend)
    print_header "Building Docker Images"
    $COMPOSE_CMD -f "$COMPOSE_FILE" build
    
    print_success "Installation complete!"
    echo ""
    echo "Next steps:"
    echo "  1. Edit $ENV_FILE with your configuration"
    echo "  3. Run: ./deploy.sh start"
}

start() {
    print_header "Starting EMSX Trading Platform"
    
    check_docker
    check_env_file
    check_bloomberg
    
    # Start services (docker compose builds images if needed)
    print_header "Starting Services"
    $COMPOSE_CMD -f "$COMPOSE_FILE" up -d --build
    
    # Wait for services to be ready
    echo "Waiting for services to start..."
    sleep 10
    
    # Check health
    if curl -sf http://localhost:3000/api/health > /dev/null 2>&1; then
        print_success "Backend API is healthy"
    else
        print_error "Backend API health check failed"
        echo "Check logs with: ./deploy.sh logs"
        exit 1
    fi
    
    print_success "EMSX Trading Platform is running!"
    echo ""
    echo "Access URLs:"
    echo "  Frontend: http://localhost:80"
    echo "  API:      http://localhost:3000  (internal, proxied via Nginx)"
    echo "  Health:   http://localhost/api/health"
}

stop() {
    print_header "Stopping EMSX Trading Platform"
    $COMPOSE_CMD -f "$COMPOSE_FILE" down
    print_success "Services stopped"
}

restart() {
    print_header "Restarting EMSX Trading Platform"
    stop
    start
}

status() {
    print_header "Service Status"
    $COMPOSE_CMD -f "$COMPOSE_FILE" ps
    
    echo ""
    print_header "Health Check"
    curl -s http://localhost/api/health | python3 -m json.tool 2>/dev/null || \
        curl -s http://localhost/api/health
    echo ""
}

logs() {
    if [ -z "$2" ]; then
        $COMPOSE_CMD -f "$COMPOSE_FILE" logs -f
    else
        $COMPOSE_CMD -f "$COMPOSE_FILE" logs -f "$2"
    fi
}

update() {
    print_header "Updating EMSX Trading Platform"
    $COMPOSE_CMD -f "$COMPOSE_FILE" build --no-cache
    $COMPOSE_CMD -f "$COMPOSE_FILE" up -d
    print_success "Update complete"
}

backup() {
    print_header "Backing up configuration"
    
    BACKUP_DIR="$PROJECT_DIR/backup/$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    
    cp "$ENV_FILE" "$BACKUP_DIR/"
    cp -r "$PROJECT_DIR/config" "$BACKUP_DIR/"
    
    print_success "Backup saved to $BACKUP_DIR"
}

# Main command handler
case "${1:-}" in
    install)
        install
        ;;
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs "$@"
        ;;
    update)
        update
        ;;
    backup)
        backup
        ;;
    *)
        echo "EMSX Trading API - Deployment Script"
        echo ""
        echo "Usage: $0 [command]"
        echo ""
        echo "Commands:"
        echo "  install    - First-time installation"
        echo "  start      - Start all services"
        echo "  stop       - Stop all services"
        echo "  restart    - Restart all services"
        echo "  status     - Check service status"
        echo "  logs       - View logs (optionally: logs [service])"
        echo "  update     - Update to latest version"
        echo "  backup     - Backup configuration"
        echo ""
        echo "Examples:"
        echo "  $0 install"
        echo "  $0 start"
        echo "  $0 logs backend"
        exit 1
        ;;
esac
