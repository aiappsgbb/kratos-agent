"""Conversation management endpoints."""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from app.models import (
    Conversation,
    ConversationCreate,
    ConversationList,
    ConversationStatus,
    ConversationUpdate,
    Message,
)
from app.services.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_cosmos(request: Request):  # noqa: ANN202
    return request.app.state.cosmos_service


@router.post("", response_model=Conversation, status_code=201)
async def create_conversation(body: ConversationCreate, request: Request) -> Conversation:
    """Create a new conversation."""
    cosmos = _get_cosmos(request)

    # Re-sync the use-case's skills from blob storage so every new conversation
    # picks up the latest skills, prompts, and MCP config.
    blob_service = request.app.state.blob_skill_service
    apm_service = getattr(request.app.state, "apm_service", None)
    if blob_service and blob_service.is_available:
        try:
            registry = SkillRegistry()
            await registry.load(body.useCase, blob_service, apm_service=apm_service)
            registries: dict[str, SkillRegistry] = request.app.state.registries
            registries[body.useCase] = registry
            logger.info("Re-synced use-case '%s' from blob for new conversation", body.useCase)
        except Exception:
            logger.exception("Failed to re-sync use-case '%s' from blob — using cached version", body.useCase)

    now = datetime.now(UTC)
    conversation = Conversation(
        id=str(uuid.uuid4()),
        userId="default-user",  # Replaced by Entra ID user in production
        title=body.title,
        useCase=body.useCase,
        status=ConversationStatus.ACTIVE,
        createdAt=now,
        updatedAt=now,
    )
    await cosmos.upsert_conversation(conversation)
    return conversation


@router.get("", response_model=ConversationList)
async def list_conversations(request: Request) -> ConversationList:
    """List all conversations for the current user."""
    cosmos = _get_cosmos(request)
    conversations = await cosmos.list_conversations("default-user")
    return ConversationList(conversations=conversations)


@router.get("/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str, request: Request) -> Conversation:
    """Get a single conversation."""
    cosmos = _get_cosmos(request)
    conversation = await cosmos.get_conversation(conversation_id, "default-user")
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get("/{conversation_id}/messages", response_model=list[Message])
async def get_messages(conversation_id: str, request: Request) -> list[Message]:
    """Get all messages for a conversation."""
    cosmos = _get_cosmos(request)
    return await cosmos.list_messages(conversation_id)


@router.patch("/{conversation_id}", response_model=Conversation)
async def update_conversation(conversation_id: str, body: ConversationUpdate, request: Request) -> Conversation:
    """Update a conversation's mutable fields (currently: title)."""
    cosmos = _get_cosmos(request)
    conversation = await cosmos.get_conversation(conversation_id, "default-user")
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if body.title is not None:
        conversation.title = body.title
    conversation.updatedAt = datetime.now(UTC)
    await cosmos.upsert_conversation(conversation)
    return conversation


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, request: Request) -> None:
    """Delete a conversation and its messages."""
    cosmos = _get_cosmos(request)
    await cosmos.delete_conversation(conversation_id, "default-user")
