"""Cosmos DB service for conversation, message, and skill persistence.

Uses Azure Managed Identity for passwordless authentication when a Cosmos DB
endpoint is configured. When no endpoint is configured (``is_local_mode``),
persistence falls back to a local SQLite database so the full backend is
usable for development without any Azure dependency.

Partition keys: conversations -> /userId, messages -> /conversationId, skills -> /name
"""

import contextlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import aiosqlite
from azure.cosmos.aio import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError
from azure.identity.aio import DefaultAzureCredential

from app.config import Settings
from app.models import Conversation, Message

logger = logging.getLogger(__name__)

# Log a warning if a Cosmos operation takes longer than this (ms)
_SLOW_OPERATION_THRESHOLD_MS = 500


class CosmosService:
    """Manages conversation, message, and skill persistence.

    Backed by Azure Cosmos DB in production, or a local SQLite database when
    ``settings.cosmos_db_endpoint`` is empty. The public API is identical
    between the two backends.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: CosmosClient | None = None
        self._conversations_container: Any = None
        self._messages_container: Any = None
        self._settings_container: Any = None
        self._sessions_container: Any = None
        self._sqlite_db: aiosqlite.Connection | None = None

    def _using_sqlite(self) -> bool:
        """Return True when the SQLite backend is active."""
        return self._sqlite_db is not None

    async def initialize(self) -> None:
        """Initialize the configured backend.

        If ``settings.cosmos_db_endpoint`` is set, initialises an Azure Cosmos
        DB client with managed identity. Otherwise, opens a local SQLite
        database at ``{local_data_dir}/kratos.db`` and creates the schema on
        first run.
        """
        if not self.settings.cosmos_db_endpoint:
            await self._sqlite_initialize()
            return

        credential = DefaultAzureCredential()
        self._client = CosmosClient(self.settings.cosmos_db_endpoint, credential=credential)

        database = self._client.get_database_client(self.settings.cosmos_db_database)
        self._conversations_container = database.get_container_client("conversations")
        self._messages_container = database.get_container_client("messages")

        # Settings container — stores system prompt and other config
        try:
            self._settings_container = database.get_container_client("settings")
            await self._settings_container.read()
        except Exception:
            logger.warning("Settings container not found in Cosmos — using defaults")
            self._settings_container = None

        # Sessions container — stores SDK session ID ↔ conversation ID mapping
        try:
            self._sessions_container = database.get_container_client("sessions")
            await self._sessions_container.read()
        except Exception:
            logger.warning("Sessions container not found in Cosmos — session resume disabled")
            self._sessions_container = None

        logger.info("Cosmos DB initialized -- database=%s", self.settings.cosmos_db_database)

    async def close(self) -> None:
        """Release backend resources (currently: the SQLite connection)."""
        if self._sqlite_db is not None:
            try:
                await self._sqlite_db.close()
            finally:
                self._sqlite_db = None

    # ─── SQLite backend ───────────────────────────────────────────────────────

    _SQLITE_TABLES = ("conversations", "messages", "settings", "session_mappings")

    async def _sqlite_initialize(self) -> None:
        """Open the local SQLite database and create the schema if missing."""
        data_dir = Path(self.settings.local_data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = data_dir / "kratos.db"

        db = await aiosqlite.connect(str(db_path), isolation_level=None)
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")

        for table in self._SQLITE_TABLES:
            await db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id TEXT NOT NULL,
                    partition_key TEXT NOT NULL,
                    data TEXT NOT NULL,
                    PRIMARY KEY (id, partition_key)
                )
                """
            )
        await db.execute("CREATE INDEX IF NOT EXISTS idx_conversations_pk ON conversations(partition_key)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_messages_pk ON messages(partition_key, data)")
        await db.commit()

        self._sqlite_db = db
        logger.info("Cosmos local (SQLite) backend at %s", db_path)

    async def _sqlite_upsert(self, table: str, item_id: str, partition_key: str, doc: dict[str, Any]) -> None:
        """Insert or replace a JSON document in ``table``."""
        assert self._sqlite_db is not None
        await self._sqlite_db.execute(
            f"INSERT OR REPLACE INTO {table} (id, partition_key, data) VALUES (?, ?, ?)",  # noqa: S608
            (item_id, partition_key, json.dumps(doc)),
        )
        await self._sqlite_db.commit()

    async def _sqlite_read(self, table: str, item_id: str, partition_key: str) -> dict[str, Any] | None:
        """Read a single JSON document by ``(id, partition_key)``."""
        assert self._sqlite_db is not None
        cursor = await self._sqlite_db.execute(
            f"SELECT data FROM {table} WHERE id = ? AND partition_key = ?",  # noqa: S608
            (item_id, partition_key),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return json.loads(row[0]) if row else None

    async def _sqlite_query_by_partition(self, table: str, partition_key: str) -> list[dict[str, Any]]:
        """Return every JSON document in ``table`` with the given partition key."""
        assert self._sqlite_db is not None
        cursor = await self._sqlite_db.execute(
            f"SELECT data FROM {table} WHERE partition_key = ?",  # noqa: S608
            (partition_key,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [json.loads(r[0]) for r in rows]

    async def _sqlite_query_all(self, table: str) -> list[dict[str, Any]]:
        """Return every JSON document in ``table`` regardless of partition."""
        assert self._sqlite_db is not None
        cursor = await self._sqlite_db.execute(f"SELECT data FROM {table}")  # noqa: S608
        rows = await cursor.fetchall()
        await cursor.close()
        return [json.loads(r[0]) for r in rows]

    async def _sqlite_delete(self, table: str, item_id: str, partition_key: str) -> None:
        """Delete a document from ``table`` by ``(id, partition_key)``."""
        assert self._sqlite_db is not None
        await self._sqlite_db.execute(
            f"DELETE FROM {table} WHERE id = ? AND partition_key = ?",  # noqa: S608
            (item_id, partition_key),
        )
        await self._sqlite_db.commit()

    async def _sqlite_truncate(self, table: str) -> None:
        """Delete all rows from ``table``."""
        assert self._sqlite_db is not None
        await self._sqlite_db.execute(f"DELETE FROM {table}")  # noqa: S608
        await self._sqlite_db.commit()

    # ─── Conversations ────────────────────────────────────────────────────────

    async def upsert_conversation(self, conversation: Conversation) -> None:
        if self._using_sqlite():
            doc = conversation.model_dump(mode="json")
            await self._sqlite_upsert("conversations", conversation.id, conversation.userId, doc)
            return
        if not self._conversations_container:
            return
        start = time.monotonic()
        try:
            await self._conversations_container.upsert_item(conversation.model_dump(mode="json"))
        except CosmosHttpResponseError as exc:
            logger.error("Cosmos upsert_conversation failed: status=%s, message=%s", exc.status_code, exc.message)
            raise
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            if elapsed_ms > _SLOW_OPERATION_THRESHOLD_MS:
                logger.warning("Slow Cosmos operation: upsert_conversation took %.0f ms", elapsed_ms)

    async def get_conversation(self, conversation_id: str, user_id: str) -> Conversation | None:
        if self._using_sqlite():
            row = await self._sqlite_read("conversations", conversation_id, user_id)
            return Conversation(**row) if row else None
        if not self._conversations_container:
            return None
        try:
            item = await self._conversations_container.read_item(item=conversation_id, partition_key=user_id)
            return Conversation(**item)
        except Exception:
            return None

    async def list_conversations(self, user_id: str) -> list[Conversation]:
        if self._using_sqlite():
            rows = await self._sqlite_query_by_partition("conversations", user_id)
            conversations = [Conversation(**r) for r in rows]
            conversations.sort(key=lambda c: c.updatedAt, reverse=True)
            return conversations
        if not self._conversations_container:
            return []
        query = "SELECT * FROM c WHERE c.userId = @userId ORDER BY c.updatedAt DESC"
        params: list[dict[str, str]] = [{"name": "@userId", "value": user_id}]
        items = self._conversations_container.query_items(query=query, parameters=params, partition_key=user_id)
        return [Conversation(**item) async for item in items]

    async def delete_conversation(self, conversation_id: str, user_id: str) -> None:
        if self._using_sqlite():
            await self._sqlite_delete("conversations", conversation_id, user_id)
            return
        if not self._conversations_container:
            return
        await self._conversations_container.delete_item(item=conversation_id, partition_key=user_id)

    # ─── Messages ─────────────────────────────────────────────────────────────

    async def upsert_message(self, message: Message) -> None:
        if self._using_sqlite():
            doc = message.model_dump(mode="json")
            await self._sqlite_upsert("messages", message.id, message.conversationId, doc)
            return
        if not self._messages_container:
            return
        start = time.monotonic()
        try:
            await self._messages_container.upsert_item(message.model_dump(mode="json"))
        except CosmosHttpResponseError as exc:
            logger.error("Cosmos upsert_message failed: status=%s, message=%s", exc.status_code, exc.message)
            raise
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            if elapsed_ms > _SLOW_OPERATION_THRESHOLD_MS:
                logger.warning("Slow Cosmos operation: upsert_message took %.0f ms", elapsed_ms)

    async def list_messages(self, conversation_id: str) -> list[Message]:
        if self._using_sqlite():
            rows = await self._sqlite_query_by_partition("messages", conversation_id)
            messages = [Message(**r) for r in rows]
            messages.sort(key=lambda m: m.createdAt)
            return messages
        if not self._messages_container:
            return []
        start = time.monotonic()
        query = "SELECT * FROM c WHERE c.conversationId = @cid ORDER BY c.createdAt ASC"
        params: list[dict[str, str]] = [{"name": "@cid", "value": conversation_id}]
        items = self._messages_container.query_items(query=query, parameters=params, partition_key=conversation_id)
        results = [Message(**item) async for item in items]
        elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms > _SLOW_OPERATION_THRESHOLD_MS:
            logger.warning("Slow Cosmos operation: list_messages took %.0f ms (%d items)", elapsed_ms, len(results))
        return results

    # ─── Settings ─────────────────────────────────────────────────────────────

    async def get_setting(self, setting_id: str) -> dict | None:
        """Read a setting by id. Partition key is /category."""
        if self._using_sqlite():
            return await self._sqlite_read("settings", setting_id, "system")
        if not self._settings_container:
            return None
        try:
            return await self._settings_container.read_item(item=setting_id, partition_key="system")
        except Exception:
            return None

    async def upsert_setting(self, setting: dict) -> dict:
        """Create or update a setting document."""
        if self._using_sqlite():
            setting_id = setting["id"]
            await self._sqlite_upsert("settings", setting_id, "system", setting)
            return setting
        if not self._settings_container:
            return setting
        await self._settings_container.upsert_item(setting)
        return setting

    async def delete_setting(self, setting_id: str) -> None:
        """Delete a setting document by id."""
        if self._using_sqlite():
            await self._sqlite_delete("settings", setting_id, "system")
            return
        if not self._settings_container:
            return
        with contextlib.suppress(Exception):
            await self._settings_container.delete_item(item=setting_id, partition_key="system")

    # ─── Sessions (SDK session ID mapping) ────────────────────────────────────

    async def upsert_session_mapping(self, conversation_id: str, agent_session_id: str) -> None:
        """Store the gateway agent session ID for a conversation."""
        doc = {
            "id": conversation_id,
            "conversationId": conversation_id,
            "agentSessionId": agent_session_id,
        }
        if self._using_sqlite():
            await self._sqlite_upsert("session_mappings", conversation_id, conversation_id, doc)
            return
        if not self._sessions_container:
            return
        await self._sessions_container.upsert_item(doc)

    async def get_session_mapping(self, conversation_id: str) -> str | None:
        """Return the gateway agent session ID for a conversation, or None."""
        if self._using_sqlite():
            row = await self._sqlite_read("session_mappings", conversation_id, conversation_id)
            return row.get("agentSessionId") if row else None
        if not self._sessions_container:
            return None
        try:
            item = await self._sessions_container.read_item(item=conversation_id, partition_key=conversation_id)
            return item.get("agentSessionId")
        except Exception:
            return None

    async def delete_session_mapping(self, conversation_id: str) -> None:
        """Delete the session mapping for a conversation."""
        if self._using_sqlite():
            await self._sqlite_delete("session_mappings", conversation_id, conversation_id)
            return
        if not self._sessions_container:
            return
        with contextlib.suppress(Exception):
            await self._sessions_container.delete_item(item=conversation_id, partition_key=conversation_id)

    async def delete_all_session_mappings(self) -> None:
        """Delete all stored gateway session mappings (called on prompt/config resets)."""
        if self._using_sqlite():
            await self._sqlite_truncate("session_mappings")
            return
        if not self._sessions_container:
            return
        try:
            items = self._sessions_container.query_items(
                query="SELECT c.id, c.conversationId FROM c",
                enable_cross_partition_query=True,
            )
            async for item in items:
                with contextlib.suppress(Exception):
                    await self._sessions_container.delete_item(item=item["id"], partition_key=item["conversationId"])
        except Exception:
            logger.warning("Failed to purge all session mappings from Cosmos", exc_info=True)
