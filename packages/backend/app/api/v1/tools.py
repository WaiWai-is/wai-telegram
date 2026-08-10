from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, get_auth_context
from app.core.database import get_db
from app.services.tool_registry import (
    TOOL_DEFINITIONS,
    WRITE_TOOL_NAMES,
    ToolInputError,
    execute_data_tool,
)

router = APIRouter()


class ToolExecuteRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.get("")
async def list_data_tools(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": definition.name,
                "description": definition.description,
                "parameters": definition.parameters,
            }
            for definition in TOOL_DEFINITIONS
            if ctx.has_scope("write") or definition.name not in WRITE_TOOL_NAMES
        ]
    }


@router.post("/{name}")
async def execute_tool(
    name: str,
    payload: ToolExecuteRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    if name in WRITE_TOOL_NAMES and not ctx.has_scope("write"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key lacks 'write' permission",
        )
    try:
        return await execute_data_tool(db, ctx.user.id, name, payload.arguments)
    except ToolInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
