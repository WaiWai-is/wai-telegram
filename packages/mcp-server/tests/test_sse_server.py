import json

from starlette.testclient import TestClient
from telegram_wai_mcp.sse_server import create_app

BASE_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "host": "telegram.waiwai.is",
}


def _initialize(client: TestClient, headers: dict[str, str], path: str = "/mcp") -> str:
    response = client.post(
        path,
        headers=headers,
        content=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0.1"},
                },
            }
        ),
    )
    assert response.status_code == 200
    session_id = response.headers.get("mcp-session-id")
    assert session_id
    return session_id


def test_initialize_binds_session_to_api_key() -> None:
    with TestClient(create_app()) as client:
        session_id = _initialize(client, {**BASE_HEADERS}, "/mcp?key=wai_test")

        session_headers = {
            **BASE_HEADERS,
            "mcp-session-id": session_id,
            "mcp-protocol-version": "2025-03-26",
        }

        initialized = client.post(
            "/mcp",
            headers=session_headers,
            content=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        )
        assert initialized.status_code == 202

        tools_list = client.post(
            "/mcp",
            headers=session_headers,
            content=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                }
            ),
        )
        assert tools_list.status_code == 200
        assert tools_list.headers.get("mcp-session-id") == session_id
        assert '"name":"get_data_status"' in tools_list.text


def test_bearer_token_can_initialize_session() -> None:
    with TestClient(create_app()) as client:
        session_id = _initialize(
            client,
            {**BASE_HEADERS, "authorization": "Bearer wai_test"},
            "/mcp",
        )

        tools_list = client.post(
            "/mcp",
            headers={
                **BASE_HEADERS,
                "mcp-session-id": session_id,
                "mcp-protocol-version": "2025-03-26",
            },
            content=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                }
            ),
        )
        assert tools_list.status_code == 200


def test_allowed_origin_header_is_accepted() -> None:
    with TestClient(create_app()) as client:
        session_id = _initialize(
            client,
            {
                **BASE_HEADERS,
                "origin": "https://telegram.waiwai.is",
            },
            "/mcp?key=wai_test",
        )
        assert session_id
