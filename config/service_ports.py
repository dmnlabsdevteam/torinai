#!/usr/bin/env python3
"""
Service Port Configuration (TorinAI)
Centralized port configuration for all TorinAI services
Last updated: December 30, 2025
"""

# ============================================================================
# CORE TORINAI SERVICES (Autonomous System)
# ============================================================================
# Main TorinAI autonomous system API

# Core Services
TORIN_API_PORT = 8007           # Main TorinAI API (autonomous system, legacy compatibility)
# LLM & AI Services
OLLAMA_PORT = 11434             # Ollama LLM server (local inference)
SLACK_WEBHOOK_PORT = 8005       # Slack webhook receiver (notifications)
WEBSOCKET_PORT = 8009           # WebSocket server (real-time updates)

# ============================================================================
# APPLICATION SERVICES (Chat Apps & APIs)
# ============================================================================
# iOS App (TorinChat) and Employee Portal (TorinPlus)
IOS_API_PORT = 8010             # Frontend server - Public iOS app (TorinChat)
BACKEND_API_PORT = 8011         # Backend server - Employee portal admin (TorinPlus)

# Legacy/Additional Ports
BACKEND_PORT = 8000             # Legacy backend port
FRONTEND_PORT = 8001            # Legacy frontend port

# ============================================================================
# AI & INFRASTRUCTURE SERVICES
# ============================================================================
CORE_AI_PORT = 8090             # Core AI service endpoint

# Cloud & Storage
CLOUD_STORAGE_PORT = 8012       # Cloud storage API endpoint

# Message Queue (NATS)
NATS_PORT = 4222                # NATS messaging port
NATS_HTTP_PORT = 8222           # NATS HTTP monitoring port

# Cache (Redis)
REDIS_PORT = 6379               # Redis cache port

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_service_url(host: str, port: int) -> str:
    """Generate service URL from host and port"""
    if port == 443:
        return f"https://{host}"
    return f"http://{host}:{port}"


def get_all_ports() -> dict:
    """Get dictionary of all configured service ports"""
    ports = {
        "torin_api": TORIN_API_PORT,
        "ollama": OLLAMA_PORT,
        "slack_webhook": SLACK_WEBHOOK_PORT,
        "websocket": WEBSOCKET_PORT,
        "ios_api": IOS_API_PORT,
        "backend_api": BACKEND_API_PORT,
        "backend": BACKEND_PORT,
        "frontend": FRONTEND_PORT,
        "core_ai": CORE_AI_PORT,
        "cloud_storage": CLOUD_STORAGE_PORT,
        "nats": NATS_PORT,
        "nats_http": NATS_HTTP_PORT,
        "redis": REDIS_PORT
    }

    port_map = {}
    for service, port in ports.items():
        if port in port_map:
            print(f"WARNING: Port {port} is used by both {port_map[port]} and {service}")
        else:
            port_map[port] = service

    return ports


if __name__ == "__main__":
    print("TorinAI Service Port Configuration")
    print("=" * 60)
    print(f"Main API Port:        {TORIN_API_PORT}")
    print(f"Ollama LLM Port:      {OLLAMA_PORT}")
    print(f"Slack Webhook Port:   {SLACK_WEBHOOK_PORT}")
    print(f"WebSocket Port:       {WEBSOCKET_PORT}")
    print("=" * 60)

    all_ports = get_all_ports()
    if all_ports:
        print("\nAll Configured Ports:")
        for service, port in sorted(all_ports.items(), key=lambda x: x[1]):
            print(f"  {service:20s}: {port}")
    else:
        print("\nNo port conflicts detected!")

    print("\nService URLs (localhost):")
    print(f"  TorinAI API:  http://localhost:{TORIN_API_PORT}")
