from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import String, Float, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Trace(Base):
    __tablename__ = "traces"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(20))
    user_input: Mapped[str] = mapped_column(Text)
    final_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    agent_plan: Mapped[Optional[Dict]] = mapped_column(JSONB, nullable=True)
    tokens_prompt_total: Mapped[int] = mapped_column(Integer, default=0)
    tokens_completion_total: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    user_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class Span(Base):
    __tablename__ = "spans"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("traces.id"))
    parent_span_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    span_type: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_: Mapped[Dict] = mapped_column("metadata", JSONB, default=dict)


class LLMCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    span_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("spans.id"))
    model: Mapped[str] = mapped_column(String(100))
    messages: Mapped[Any] = mapped_column(JSONB)
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tokens_prompt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_completion: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    temperature: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    span_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("spans.id"))
    tool_name: Mapped[str] = mapped_column(String(100))
    tool_source: Mapped[str] = mapped_column(String(30))
    input_args: Mapped[Dict] = mapped_column(JSONB, default=dict)
    output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    healing_strategy: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    known_fix_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RagDocument(Base):
    __tablename__ = "rag_documents"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(255))
    doc_type: Mapped[str] = mapped_column(String(50))
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    format: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    word_count_approx: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(100))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RagRetrieval(Base):
    __tablename__ = "rag_retrievals"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    span_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("spans.id"))
    query: Mapped[str] = mapped_column(Text)
    filter_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    k_requested: Mapped[int] = mapped_column(Integer, default=5)
    results_count: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[Any] = mapped_column(JSONB, default=list)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EventRecord(Base):
    __tablename__ = "events"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trace_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("traces.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(20))
    event_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    topic: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[Dict] = mapped_column(JSONB, default=dict)
    metadata_: Mapped[Dict] = mapped_column("metadata", JSONB, default=dict)
    route_matched: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    display_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    key_prefix: Mapped[str] = mapped_column(String(13))
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class TokenQuota(Base):
    __tablename__ = "token_quotas"
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    daily_tokens: Mapped[int] = mapped_column(Integer, default=100000)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
