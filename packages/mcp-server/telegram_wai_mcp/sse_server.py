"""
SSE Server for remote MCP connections (Claude.ai, etc.).

Runs the MCP server over HTTP/SSE transport so it can be used
as a remote connector from Claude.ai web interface.

Usage:
    TELEGRAM_AI_URL=https://telegram.waiwai.is \
    telegram-wai-mcp-sse --port 8808 --host 127.0.0.1

The API key is passed via query parameter on the /sse endpoint:
    GET /sse?key=wai_xxx
"""

import argparse
import logging
import os

import uvicorn
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from telegram_wai_mcp.client import TelegramAIClient
from telegram_wai_mcp.server import server

logger = logging.getLogger(__name__)

sse = SseServerTransport("/messages/")


async def handle_sse(request: Request) -> Response:
    """SSE endpoint — client connects here to start MCP session."""
    api_key = request.query_params.get("key", "")
    if not api_key:
        return Response("Missing 'key' query parameter", status_code=401)

    # Inject per-session client with the caller's API key
    from telegram_wai_mcp import server as srv

    base_url = os.environ.get("TELEGRAM_AI_URL", "http://localhost:8000")
    srv.client = TelegramAIClient(base_url=base_url, api_key=api_key)

    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())
    return Response()


app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse.handle_post_message),
    ],
)


def main():
    parser = argparse.ArgumentParser(description="MCP SSE Server for Telegram WAI")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8808, help="Port to listen on")
    args = parser.parse_args()

    root_path = os.environ.get("MCP_ROOT_PATH", "")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", root_path=root_path)


if __name__ == "__main__":
    main()
