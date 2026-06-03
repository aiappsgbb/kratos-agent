"""Traces service — queries App Insights for agent operation waterfalls.

Queries ``dependencies``, ``requests``, and ``traces`` tables via
``LogsQueryClient``.  Spans are classified, depth-computed, and returned
as Pydantic models matching ``app.models.TraceList / TraceOperation``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, timedelta
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, LogsQueryStatus

from app.config import Settings
from app.models import TraceList, TraceLog, TraceOperation, TraceSpan, TraceSummary

logger = logging.getLogger(__name__)


class TracesService:
    def __init__(self, settings: Settings) -> None:
        self._resource_id = (settings.application_insights_resource_id or "").strip()
        self._workspace_id = (settings.application_insights_workspace_id or "").strip()
        self._credential = DefaultAzureCredential()
        self._client = LogsQueryClient(self._credential)

    # ─── Public API ──────────────────────────────────────────────────────────

    async def fetch_operations(
        self,
        *,
        use_case: str | None = None,
        conversation_id: str | None = None,
        eval_run_id: str | None = None,
        lookback_hours: int = 24,
        max_operations: int = 50,
    ) -> TraceList:
        """Return up to ``max_operations`` most-recent operations matching the filter."""
        resource = self._resource_id or self._workspace_id
        if not resource:
            return TraceList(
                operations=[],
                summary=TraceSummary(error="No App Insights resource configured"),
            )

        # Build the WHERE clause for the narrow op-id query
        filter_parts: list[str] = []
        if use_case:
            filter_parts.append(f"tostring(customDimensions['kratos.use_case']) == '{use_case}'")
        if conversation_id:
            filter_parts.append(f"tostring(customDimensions['kratos.conversation_id']) == '{conversation_id}'")
        if eval_run_id:
            filter_parts.append(f"tostring(customDimensions['kratos.eval_run_id']) == '{eval_run_id}'")

        if filter_parts:
            narrow_filter = " and ".join(filter_parts)
        else:
            # No filter — find recent "interesting" operations (agent / LLM spans)
            narrow_filter = (
                "cloud_RoleName == 'agent_framework'"
                " or cloud_RoleName startswith 'AgentService-'"
                " or cloud_RoleName == 'responsesapi'"
                " or isnotempty(tostring(customDimensions['kratos.use_case']))"
            )

        span_kql = _build_span_kql(narrow_filter, lookback_hours, max_operations)
        log_kql = _build_log_kql(narrow_filter, lookback_hours, max_operations)

        try:
            span_resp, log_resp = await asyncio.gather(
                asyncio.to_thread(self._run_query, resource, span_kql, lookback_hours),
                asyncio.to_thread(self._run_query, resource, log_kql, lookback_hours),
            )
        except Exception as exc:
            logger.exception("Failed to query App Insights traces")
            return TraceList(
                operations=[],
                summary=TraceSummary(error=str(exc)),
            )

        spans_tables = _extract_tables(span_resp)
        log_tables = _extract_tables(log_resp)
        logger.info(
            "traces query: filter=%r span_tables=%d span_rows=%d log_tables=%d log_rows=%d",
            narrow_filter[:120],
            len(spans_tables),
            sum(len(getattr(t, "rows", []) or []) for t in spans_tables),
            len(log_tables),
            sum(len(getattr(t, "rows", []) or []) for t in log_tables),
        )

        log_map = _parse_logs(log_tables)
        operations = _parse_spans(spans_tables, log_map, max_operations)
        summary = _build_summary(operations)
        return TraceList(operations=operations, summary=summary)

    async def fetch_operation(
        self,
        operation_id: str,
        *,
        lookback_hours: int = 168,
    ) -> TraceOperation | None:
        """Return a single operation by ID with its full span list."""
        resource = self._resource_id or self._workspace_id
        if not resource:
            return None

        safe_id = operation_id.replace("'", "\\'")
        narrow_filter = f"operation_Id == '{safe_id}'"
        span_kql = _build_span_kql(narrow_filter, lookback_hours, max_ops=1)
        log_kql = _build_log_kql(narrow_filter, lookback_hours, max_ops=1)

        try:
            span_resp, log_resp = await asyncio.gather(
                asyncio.to_thread(self._run_query, resource, span_kql, lookback_hours),
                asyncio.to_thread(self._run_query, resource, log_kql, lookback_hours),
            )
        except Exception:
            logger.exception("Failed to fetch operation %s", operation_id)
            return None

        spans_tables = _extract_tables(span_resp)
        log_tables = _extract_tables(log_resp)

        log_map = _parse_logs(log_tables)
        operations = _parse_spans(spans_tables, log_map, max_ops=1)
        return operations[0] if operations else None

    async def close(self) -> None:
        """Release SDK resources."""
        with contextlib.suppress(Exception):
            self._client.close()

    # ─── Internal ────────────────────────────────────────────────────────────

    def _run_query(self, resource: str, kql: str, hours: int) -> Any:
        """Execute a KQL query synchronously (called via asyncio.to_thread)."""
        ts = timedelta(hours=hours)
        if resource.startswith("/"):
            try:
                return self._client.query_resource(resource_id=resource, query=kql, timespan=ts)
            except TypeError:
                return self._client.query_resource(resource_uri=resource, query=kql, timespan=ts)
        return self._client.query_workspace(workspace_id=resource, query=kql, timespan=ts)


# ─── KQL builders ────────────────────────────────────────────────────────────


def _build_span_kql(narrow_filter: str, lookback_hours: int, max_ops: int) -> str:
    return f"""
let matching_ops =
    union dependencies, requests
    | where timestamp > ago({lookback_hours}h)
    | where {narrow_filter}
    | distinct operation_Id
    | take {max_ops * 4};
union dependencies, requests
| where timestamp > ago({lookback_hours}h)
| where operation_Id in (matching_ops)
| summarize arg_max(timestamp, *) by id
| project
    timestamp,
    id,
    operation_Id,
    parentId = operation_ParentId,
    name,
    duration,
    success,
    resultCode,
    spanType = itemType,
    cloud_RoleName,
    dep_type = case(itemType == 'dependency', type, ''),
    dep_target = case(itemType == 'dependency', tostring(target), ''),
    model = tostring(customDimensions['gen_ai.response.model']),
    op_name = tostring(customDimensions['gen_ai.operation.name']),
    input_tokens = toint(customDimensions['gen_ai.usage.input_tokens']),
    output_tokens = toint(customDimensions['gen_ai.usage.output_tokens']),
    tool_name = tostring(customDimensions['gen_ai.tool.name']),
    tool_kind = tostring(customDimensions['gen_ai.tool.kind']),
    error_type = tostring(customDimensions['error.type']),
    kratos_use_case = tostring(customDimensions['kratos.use_case']),
    kratos_conversation_id = tostring(customDimensions['kratos.conversation_id']),
    kratos_eval_run_id = tostring(customDimensions['kratos.eval_run_id']),
    kratos_skill_name = tostring(customDimensions['kratos.skill.name'])
| order by timestamp asc
"""


def _build_log_kql(narrow_filter: str, lookback_hours: int, max_ops: int) -> str:
    return f"""
let matching_ops =
    union dependencies, requests
    | where timestamp > ago({lookback_hours}h)
    | where {narrow_filter}
    | distinct operation_Id
    | take {max_ops * 4};
traces
| where timestamp > ago({lookback_hours}h)
| where operation_Id in (matching_ops)
| where not(message has "Credential.get_token" and message has "succeeded")
    and message !has "acquired a token"
| project
    timestamp,
    operation_Id,
    message = substring(message, 0, 2000),
    severityLevel,
    cloud_RoleName
| order by timestamp asc
"""


# ─── Query result helpers ─────────────────────────────────────────────────────


def _extract_tables(resp: Any) -> list:
    """Extract table list from a LogsQueryResult, tolerating partial data.

    The azure-monitor-query SDK returns either a `LogsQueryResult` (status=SUCCESS,
    tables populated) or a `LogsQueryPartialResult` (partial_data populated,
    partial_error set). Either way, we want the tables — only return [] if
    neither shape has any data.
    """
    if resp is None:
        return []
    # SUCCESS path
    if getattr(resp, "status", None) == LogsQueryStatus.SUCCESS:
        return resp.tables or []
    # PARTIAL path
    if hasattr(resp, "partial_data") and resp.partial_data:
        return resp.partial_data
    # Some SDK versions return tables on the object regardless of status
    if getattr(resp, "tables", None):
        return resp.tables
    return []


# ─── Parsers ─────────────────────────────────────────────────────────────────


def _parse_logs(tables: list) -> dict[str, list[TraceLog]]:
    """Return log entries from the traces table, grouped by operation_Id."""
    log_map: dict[str, list[TraceLog]] = {}
    if not tables:
        return log_map
    table = tables[0]
    columns = [c if isinstance(c, str) else c.name for c in table.columns]
    for row in table.rows:
        d = dict(zip(columns, row, strict=False))
        op_id = d.get("operation_Id", "")
        msg = str(d.get("message", ""))
        if not op_id or not msg:
            continue
        log_map.setdefault(op_id, []).append(
            TraceLog(
                timestamp=str(d.get("timestamp", "")),
                message=msg,
                severity=int(d.get("severityLevel") or 1),
                cloud_role=str(d.get("cloud_RoleName") or ""),
            )
        )
    return log_map


def _parse_spans(
    tables: list,
    log_map: dict[str, list[TraceLog]],
    max_ops: int,
) -> list[TraceOperation]:
    """Parse span rows into ``TraceOperation`` objects."""
    if not tables:
        return []

    table = tables[0]
    columns = [c if isinstance(c, str) else c.name for c in table.columns]

    # Group raw rows by operation_Id
    ops_raw: dict[str, list[dict[str, Any]]] = {}
    for row in table.rows:
        d = dict(zip(columns, row, strict=False))
        op_id = str(d.get("operation_Id") or "")
        if not op_id:
            continue
        ops_raw.setdefault(op_id, []).append(d)

    operations: list[TraceOperation] = []
    for op_id, raw_spans in ops_raw.items():
        raw_spans.sort(key=lambda x: str(x.get("timestamp") or ""))

        timestamps_ms = [_ts_to_ms(str(s.get("timestamp") or "")) for s in raw_spans]
        valid_ts = [t for t in timestamps_ms if t is not None]
        op_start_ms = min(valid_ts) if valid_ts else 0.0

        spans: list[TraceSpan] = []
        for i, s in enumerate(raw_spans):
            dur = s.get("duration") or 0
            try:
                dur = float(dur)
            except (ValueError, TypeError):
                dur = 0.0

            ts_ms = timestamps_ms[i]
            offset_ms = round(ts_ms - op_start_ms, 1) if ts_ms is not None and op_start_ms else 0.0
            raw_dict = dict(s)  # pass to classifier
            category = _classify_span(raw_dict)

            attributes: dict[str, str | int | float] = {}
            if s.get("model"):
                attributes["gen_ai.response.model"] = str(s["model"])
            if s.get("op_name"):
                attributes["gen_ai.operation.name"] = str(s["op_name"])
            if s.get("input_tokens") is not None:
                with contextlib.suppress(ValueError, TypeError):
                    attributes["gen_ai.usage.input_tokens"] = int(s["input_tokens"])
            if s.get("output_tokens") is not None:
                with contextlib.suppress(ValueError, TypeError):
                    attributes["gen_ai.usage.output_tokens"] = int(s["output_tokens"])
            if s.get("tool_name"):
                attributes["gen_ai.tool.name"] = str(s["tool_name"])
            if s.get("error_type"):
                attributes["error.type"] = str(s["error_type"])
            if s.get("dep_target"):
                attributes["http.target"] = str(s["dep_target"])
            if s.get("kratos_use_case"):
                attributes["kratos.use_case"] = str(s["kratos_use_case"])
            if s.get("kratos_conversation_id"):
                attributes["kratos.conversation_id"] = str(s["kratos_conversation_id"])
            if s.get("kratos_eval_run_id"):
                attributes["kratos.eval_run_id"] = str(s["kratos_eval_run_id"])
            if s.get("kratos_skill_name"):
                attributes["kratos.skill.name"] = str(s["kratos_skill_name"])

            success_raw = s.get("success", True)
            success = bool(success_raw) if success_raw is not None else True

            spans.append(
                TraceSpan(
                    id=str(s.get("id") or ""),
                    parent_id=str(s.get("parentId") or ""),
                    name=str(s.get("name") or ""),
                    duration_ms=round(dur, 1),
                    offset_ms=max(0.0, offset_ms),
                    timestamp=str(s.get("timestamp") or ""),
                    success=success,
                    result_code=str(s.get("resultCode") or ""),
                    type=str(s.get("spanType") or ""),
                    cloud_role=str(s.get("cloud_RoleName") or ""),
                    category=category,
                    attributes=attributes,
                )
            )

        _compute_depths(spans)

        # Total wall-clock: last span's end relative to op start
        total_dur = max(
            (s.offset_ms + s.duration_ms for s in spans),
            default=0.0,
        )

        # Collect kratos metadata from the first span that has it
        use_case = ""
        conversation_id = ""
        eval_run_id = ""
        for s in raw_spans:
            if not use_case and s.get("kratos_use_case"):
                use_case = str(s["kratos_use_case"])
            if not conversation_id and s.get("kratos_conversation_id"):
                conversation_id = str(s["kratos_conversation_id"])
            if not eval_run_id and s.get("kratos_eval_run_id"):
                eval_run_id = str(s["kratos_eval_run_id"])

        # Skip cosmetic admin-API hits: drop operations that have no kratos
        # use-case attribution AND consist only of HTTP/platform/other spans.
        categories = {s.category for s in spans}
        if not use_case and categories <= {"http", "other", "platform"}:
            continue

        op_ts = str(raw_spans[0].get("timestamp") or "") if raw_spans else ""
        logs = log_map.get(op_id, [])[:30]

        operations.append(
            TraceOperation(
                operation_id=op_id,
                timestamp=op_ts,
                total_duration_ms=round(total_dur, 1),
                span_count=len(spans),
                use_case=use_case,
                conversation_id=conversation_id,
                eval_run_id=eval_run_id,
                spans=spans,
                logs=logs,
            )
        )

    operations.sort(key=lambda o: o.timestamp, reverse=True)
    return operations[:max_ops]


# ─── Span helpers ─────────────────────────────────────────────────────────────


def _classify_span(s: dict[str, Any]) -> str:
    """Classify a raw span dict into a display category."""
    name = str(s.get("name") or "").lower()
    op_name = str(s.get("op_name") or "")
    model = str(s.get("model") or "")
    tool_name = str(s.get("tool_name") or "")
    tool_kind = str(s.get("tool_kind") or "")
    role = str(s.get("cloud_RoleName") or "").lower()
    span_type = str(s.get("spanType") or "").lower()
    dep_type = str(s.get("dep_type") or "").lower()
    skill_name = str(s.get("kratos_skill_name") or "")
    success_raw = s.get("success", True)

    # LLM spans first — gen_ai operation or chat name
    if op_name or model or name.startswith("chat ") or "responses.create" in name:
        return "llm"

    # Agent root invocation
    if role == "agent_framework":
        return "agent"

    # Kratos agent chat endpoint = top-level agent operation
    if role == "kratos-agent-service" and (name == "post /api/agent/chat" or "/api/agent/chat" in name.lower()):
        return "agent"

    # Internal agent spans
    if name.startswith("agent.") or name.startswith("agent_internal."):
        return "agent_internal"

    # Tool spans
    if tool_name or tool_kind == "tool":
        return "tool"

    # Skill spans (kratos-specific)
    if skill_name or name.startswith("skill.") or tool_kind == "skill":
        return "skill"

    # HTTP spans
    if span_type == "request" or name.startswith("http ") or dep_type in ("http", "https"):
        return "http"

    # Platform spans (Foundry / Azure AI Services infrastructure)
    if role == "responsesapi" or role.startswith("agentservice-"):
        return "platform"

    # Error spans
    if success_raw is False:
        return "error"

    return "other"


def _compute_depths(spans: list[TraceSpan]) -> None:
    """Assign ``depth`` to each span by walking the parent-child tree in-place."""
    id_set = {s.id for s in spans}
    id_to_parent = {s.id: s.parent_id for s in spans}
    depth_cache: dict[str, int] = {}

    def _depth(sid: str) -> int:
        if sid in depth_cache:
            return depth_cache[sid]
        pid = id_to_parent.get(sid, "")
        if not pid or pid not in id_set:
            depth_cache[sid] = 0
            return 0
        d = _depth(pid) + 1
        depth_cache[sid] = d
        return d

    for s in spans:
        s.depth = _depth(s.id)


def _build_summary(operations: list[TraceOperation]) -> TraceSummary:
    """Aggregate token counts, latency, and model usage across operations."""
    if not operations:
        return TraceSummary()

    total_tokens = 0
    models: set[str] = set()
    latencies: list[float] = []

    for op in operations:
        latencies.append(op.total_duration_ms)
        for span in op.spans:
            attrs = span.attributes
            inp = int(attrs.get("gen_ai.usage.input_tokens") or 0)
            out = int(attrs.get("gen_ai.usage.output_tokens") or 0)
            total_tokens += inp + out
            model = str(attrs.get("gen_ai.response.model") or "")
            if model:
                models.add(model)

    avg = round(sum(latencies) / len(latencies), 1) if latencies else 0.0
    return TraceSummary(
        total_operations=len(operations),
        avg_latency_ms=avg,
        total_tokens=total_tokens,
        models_used=sorted(models),
    )


# ─── Timestamp helper ─────────────────────────────────────────────────────────


def _ts_to_ms(ts_str: str) -> float | None:
    """Parse an ISO timestamp string to epoch milliseconds, or None on failure."""
    from datetime import datetime

    if not ts_str:
        return None
    try:
        s = ts_str.rstrip("Z")
        if "+" not in s and "-" not in s[10:]:
            s += "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.timestamp() * 1000
    except (ValueError, TypeError):
        return None
