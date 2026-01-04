"""
XMX Module - Not Implemented Stub (Teaching)

TODO(student): Implement XMX module APIs and agents.
All XMX API routes return HTTP 501 until implemented.
"""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def not_implemented(request: Request, path: str):
    raise HTTPException(status_code=501, detail="Not Implemented (XMX module TODO)")


