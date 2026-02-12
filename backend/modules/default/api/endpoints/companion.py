"""
Companion endpoints - Default module (proxy gateway)

Front-end usually talks to the default module at `/api/v1/*`.
This endpoint proxies companion requests to the subject module, similar to `learning.py`.

Tony-first:
- subject in {history, geography, other} -> proxy to tony module.
Other modules are currently stubs (student TODO).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.default.api.deps import get_current_user, get_db
from backend.core.db.models import CompanionConversation, CompanionMessage, User

logger = logging.getLogger(__name__)
router = APIRouter()

# Keep consistent with moduleRouting.js
SUBJECT_TO_MODULE = {
    "chinese": "rpj",
    "english": "rpj",
    "politics": "rpj",
    "economics": "xmx",
    "math": "wzy",
    "physics": "wzy",
    "chemistry": "wzm",
    "history": "tony",
    "geography": "tony",
    "other": "tony",
}

MODULE_PORTS = {
    "rpj": 6001,
    "xmx": 6002,
    "wzy": 6003,
    "wzm": 6004,
    "tony": 6005,
}


async def _proxy(
    *,
    request: Request,
    module: str,
    method: str,
    path: str,
    params: dict,
    json_body: Optional[dict] = None,
) -> Dict[str, Any]:
    import httpx

    port = MODULE_PORTS.get(module)
    if not port:
        raise HTTPException(status_code=502, detail=f"Unknown module port for '{module}'")

    url = f"http://127.0.0.1:{port}/api/v1/companion{path}"
    headers = {}
    auth = request.headers.get("authorization")
    if auth:
        headers["authorization"] = auth

    t0 = time.monotonic()
    try:
        # IMPORTANT: This is an internal localhost proxy call (127.0.0.1 -> module port).
        # In many classroom environments, users set ALL_PROXY/HTTP_PROXY globally.
        # httpx defaults to `trust_env=True` and would route localhost traffic through proxies,
        # causing confusing failures like "Server disconnected without sending a response".
        async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
            if method == "GET":
                resp = await client.get(url, params=params, headers=headers)
            elif method == "DELETE":
                resp = await client.delete(url, params=params, headers=headers)
            else:
                resp = await client.post(url, params=params, json=json_body or {}, headers=headers)
    except Exception as e:
        logger.error(
            "[DEFAULT] proxy companion failed module=%s url=%s err=%r",
            module,
            url,
            e,
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"Failed to proxy companion to module '{module}'")

    dt_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "[DEFAULT] proxy companion ok module=%s method=%s path=%s status=%s dt_ms=%s",
        module,
        method,
        path,
        resp.status_code,
        dt_ms,
    )
    if resp.status_code >= 400:
        # Best-effort: preserve upstream JSON error shape (avoid double-encoding).
        detail: Any = resp.text
        try:
            detail = resp.json()
        except Exception:
            # keep raw text
            pass
        # Log a short preview for debugging.
        preview = (resp.text or "").replace("\n", " ").strip()
        if len(preview) > 500:
            preview = preview[:500] + "...(truncated)"
        logger.error(
            "[DEFAULT] proxy companion upstream error module=%s status=%s dt_ms=%s body=%r",
            module,
            resp.status_code,
            dt_ms,
            preview,
        )
        raise HTTPException(status_code=resp.status_code, detail=detail)
    try:
        return resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"Invalid response from module '{module}'")


async def _proxy_stream(
    *,
    request: Request,
    module: str,
    path: str,
    params: dict,
    json_body: Optional[dict] = None,
) -> StreamingResponse:
    """
    Streaming proxy (SSE passthrough).
    This is used by `/companion/chat/stream` so frontend can render tokens incrementally.
    """
    logger.info("_proxy_stream_ok")
    import httpx

    port = MODULE_PORTS.get(module)
    if not port:
        raise HTTPException(status_code=502, detail=f"Unknown module port for '{module}'")

    url = f"http://127.0.0.1:{port}/api/v1/companion{path}"
    headers = {}
    auth = request.headers.get("authorization")
    if auth:
        logger.info("auth_ok")
        headers["authorization"] = auth

    async def gen():
        t0 = time.monotonic()
        try:
            # Same proxy caveat as above; disable env proxies for localhost module calls.
            async with httpx.AsyncClient(timeout=None, trust_env=False) as client:
                async with client.stream("POST", url, params=params, json=json_body or {}, headers=headers) as resp:
                    dt_ms = int((time.monotonic() - t0) * 1000)
                    logger.info(
                        "[DEFAULT] proxy companion stream open module=%s path=%s status=%s dt_ms=%s",
                        module,
                        path,
                        resp.status_code,
                        dt_ms,
                    )
                    if resp.status_code >= 400:
                        body_text = await resp.aread()
                        preview = (body_text.decode("utf-8", errors="ignore") or "").replace("\n", " ").strip()
                        if len(preview) > 500:
                            preview = preview[:500] + "...(truncated)"
                        logger.error(
                            "[DEFAULT] proxy companion stream upstream error module=%s status=%s body=%r",
                            module,
                            resp.status_code,
                            preview,
                        )
                        # We already started a streaming response (200). Emit a stream error event instead.
                        yield f"data: {json.dumps({'type': 'error', 'message': preview or 'Upstream error', 'status': resp.status_code}, ensure_ascii=False)}\n\n".encode("utf-8")
                        return

                    async for chunk in resp.aiter_bytes():
                        if chunk:
                            yield chunk
        except Exception as e:
            logger.error(
                "[DEFAULT] proxy companion stream failed module=%s url=%s err=%r",
                module,
                url,
                e,
                exc_info=True,
            )
            yield f"data: {json.dumps({'type': 'error', 'message': f'Failed to proxy companion stream to module {module}', 'status': 502}, ensure_ascii=False)}\n\n".encode('utf-8')
            return

    return StreamingResponse(gen(), media_type="text/event-stream")


def _resolve_module(subject: str) -> str:
    s = (subject or "").strip().lower()
    if not s:
        raise HTTPException(status_code=400, detail="subject is required for companion (Tony-first)")
    module = SUBJECT_TO_MODULE.get(s)
    if not module:
        raise HTTPException(status_code=400, detail=f"Unknown subject: {subject}")
    return module
@router.post("/chat")
async def chat(
    request: Request,
    subject: str = Query(..., description="学科"),
    body: Dict[str, Any] = Body(default_factory=dict),  # passthrough
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info("chat_ok")
    _ = (current_user, db)  # keep signature consistent; proxy uses auth header
    module = _resolve_module(subject)
    # Forward subject to module so it can choose subject-specific LoRA (module-sft-<subject>).
    return await _proxy(request=request, module=module, method="POST", path="/chat", params={"subject": subject}, json_body=body or {})


@router.post("/chat/stream")
async def chat_stream(
    request: Request,
    subject: str = Query(..., description="学科"),
    body: Dict[str, Any] = Body(default_factory=dict),  # passthrough
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info("chat_stream_ok")
    _ = (current_user, db)
    module = _resolve_module(subject)
    logger.info("chat_subject: %s", subject)
    logger.info("chat_module: %s", module)
    # Forward subject to module so it can choose subject-specific LoRA (module-sft-<subject>).
    return await _proxy_stream(request=request, module=module, path="/chat/stream", params={"subject": subject}, json_body=body or {})

@router.get("/conversations")
async def list_conversations(
    request: Request,
    subject: str = Query(..., description="学科"),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info("subject: %s", subject)
    _ = request
    module = _resolve_module(subject)
    logger.info("module: %s", module)
    res = await db.execute(
        select(CompanionConversation)
        .where(
            CompanionConversation.user_id == int(current_user.id),
            CompanionConversation.module == str(module),
        )
        .order_by(CompanionConversation.updated_at.desc())
        .limit(int(limit))
    )
    items = []
    for c in res.scalars().all():
        items.append(
            {
                "id": int(c.id),
                "title": c.title,
                "module": c.module,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
        )
    return {"items": items}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: int,
    request: Request,
    subject: str = Query(..., description="学科"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = request
    module = _resolve_module(subject)
    res = await db.execute(
        select(CompanionConversation).where(
            CompanionConversation.id == int(conversation_id),
            CompanionConversation.user_id == int(current_user.id),
            CompanionConversation.module == str(module),
        )
    )
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    rows = await db.execute(
        select(CompanionMessage)
        .where(CompanionMessage.conversation_id == int(conv.id))
        .order_by(CompanionMessage.created_at.asc())
        .limit(500)
    )
    msgs = list(rows.scalars().all())
    return {
        "conversation": {
            "id": int(conv.id),
            "title": conv.title,
            "module": conv.module,
        },
        "messages": [
            {
                "id": int(m.id),
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msgs
        ],
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    request: Request,
    subject: str = Query(..., description="学科"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    module = _resolve_module(subject)
    _ = request
    res = await db.execute(
        select(CompanionConversation).where(
            CompanionConversation.id == int(conversation_id),
            CompanionConversation.user_id == int(current_user.id),
            CompanionConversation.module == str(module),
        )
    )
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await db.execute(delete(CompanionMessage).where(CompanionMessage.conversation_id == int(conv.id)))
    await db.delete(conv)
    logger.info("[DEFAULT] deleted conversation id=%s user_id=%s module=%s", int(conv.id), int(current_user.id), module)
    return {"ok": True, "conversation_id": int(conversation_id)}

