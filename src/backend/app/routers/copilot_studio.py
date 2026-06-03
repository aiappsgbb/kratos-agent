"""Copilot Studio bridge — synchronous endpoints for Teams / M365 integration.

These endpoints are independent of the streaming /api/agent/* routes used by
the web frontend.  They accept a plain message, run the agent to completion,
and return the full reply as a single JSON response — which is what the
Copilot Studio REST API plugin model requires.
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request

from app.models import (
    Conversation,
    ConversationStatus,
    CopilotStudioRequest,
    CopilotStudioResponse,
    Message,
    MessageRole,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat", response_model=CopilotStudioResponse)
async def copilot_studio_chat(
    body: CopilotStudioRequest,
    request: Request,
) -> CopilotStudioResponse:
    """Receive a message from Copilot Studio and return the agent's answer.

    If ``conversationId`` is omitted a new conversation is created automatically.
    """
    cosmos = request.app.state.cosmos_service
    foundry_proxy = request.app.state.foundry_proxy

    # Resolve or create conversation
    conversation_id = body.conversationId
    if not conversation_id:
        now = datetime.now(UTC)
        conversation = Conversation(
            id=str(uuid.uuid4()),
            userId="copilot-studio",
            title=body.message[:80],
            useCase=body.useCase,
            status=ConversationStatus.ACTIVE,
            createdAt=now,
            updatedAt=now,
        )
        await cosmos.upsert_conversation(conversation)
        conversation_id = conversation.id

    # Persist the incoming user message
    user_msg = Message(
        id=str(uuid.uuid4()),
        conversationId=conversation_id,
        role=MessageRole.USER,
        content=body.message,
        createdAt=datetime.now(UTC),
    )
    await cosmos.upsert_message(user_msg)

    # Invoke hosted agent and collect the full reply
    parts: list[str] = []
    async for event_dict in foundry_proxy.invoke(
        message=body.message,
        conversation_id=conversation_id,
        use_case=body.useCase,
    ):
        event_name = event_dict.get("event")
        event_data = event_dict.get("data", {})
        if event_name == "content":
            parts.append(event_data.get("content", ""))
        elif event_name == "error":
            logger.error("Agent error (copilot-studio): %s", event_data.get("message", ""))

    full_reply = "".join(parts)

    # Persist assistant response
    assistant_msg = Message(
        id=str(uuid.uuid4()),
        conversationId=conversation_id,
        role=MessageRole.ASSISTANT,
        content=full_reply,
        createdAt=datetime.now(UTC),
    )
    await cosmos.upsert_message(assistant_msg)

    return CopilotStudioResponse(
        conversationId=conversation_id,
        reply=full_reply,
    )
