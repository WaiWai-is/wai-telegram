"""
Streamable HTTP Server for remote MCP connections (Claude.ai, etc.).

Runs the MCP server over Streamable HTTP transport so it can be used
as a remote connector from Claude.ai web interface. Also supports
legacy SSE transport for backward compatibility.

Usage:
    TELEGRAM_AI_URL=https://telegram.waiwai.is \
    telegram-wai-mcp-sse --port 8808 --host 127.0.0.1

The API key is passed via query parameter:
    POST /sse?key=wai_xxx  (Streamable HTTP)
    GET  /sse?key=wai_xxx  (Legacy SSE)
"""

import argparse
import contextlib
import logging
import os

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount

from telegram_wai_mcp import server as srv
from telegram_wai_mcp.client import TelegramAIClient
from telegram_wai_mcp.server import server

logger = logging.getLogger(__name__)

# Domain used for DNS rebinding protection when behind reverse proxy
DOMAIN = os.environ.get("MCP_ALLOWED_HOST", "telegram.waiwai.is")

# Create FastMCP wrapper and inject our existing low-level server
mcp = FastMCP(
    "telegram-wai-mcp",
    streamable_http_path="/sse",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[DOMAIN, "127.0.0.1:8808", "localhost:8808"],
    ),
)
mcp._mcp_server = server


class ApiKeyMiddleware:
    """ASGI middleware to extract API key and inject per-session client."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            request = Request(scope)
            api_key = request.query_params.get("key", "")
            if not api_key:
                response = Response("Missing 'key' query parameter", status_code=401)
                await response(scope, receive, send)
                return
            base_url = os.environ.get("TELEGRAM_AI_URL", "http://localhost:8000")
            srv.client = TelegramAIClient(base_url=base_url, api_key=api_key)
        await self.app(scope, receive, send)


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with mcp.session_manager.run():
        yield


inner_app = Starlette(
    routes=[
        Mount("/", app=mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)

app = ApiKeyMiddleware(inner_app)


def main():
    parser = argparse.ArgumentParser(description="MCP HTTP Server for Telegram WAI")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8808, help="Port to listen on")
    args = parser.parse_args()

    root_path = os.environ.get("MCP_ROOT_PATH", "")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", root_path=root_path)


if __name__ == "__main__":
    main()
