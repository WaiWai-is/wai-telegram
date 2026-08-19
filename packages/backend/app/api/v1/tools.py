from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext, get_auth_context
from app.core.database import get_db
from app.services.tool_registry import (
    TOOL_DEFINITIONS,
    ToolInputError,
    execute_data_tool,
    required_scope,
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
            if (scope := required_scope(definition.name)) is None
            or ctx.has_scope(scope)
        ]
    }


@router.post("/{name}")
async def execute_tool(
    name: str,
    payload: ToolExecuteRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    scope = required_scope(name)
    if scope is not None and not ctx.has_scope(scope):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key lacks '{scope}' permission",
        )
    try:
        return await execute_data_tool(db, ctx.user.id, name, payload.arguments)
    except ToolInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
