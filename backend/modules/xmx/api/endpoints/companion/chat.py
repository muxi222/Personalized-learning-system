"""
XMX Companion (小书童) - stub

Contract placeholder for student implementation.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/chat")
async def chat_stub():
    raise HTTPException(status_code=501, detail="Companion is not implemented for XMX module yet (student TODO).")


@router.get("/conversations")
async def list_conversations_stub():
    raise HTTPException(status_code=501, detail="Companion is not implemented for XMX module yet (student TODO).")


@router.get("/conversations/{conversation_id}")
async def get_conversation_stub(conversation_id: int):
    raise HTTPException(status_code=501, detail="Companion is not implemented for XMX module yet (student TODO).")

