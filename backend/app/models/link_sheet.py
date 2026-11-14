"""链接库使用不可变修订，任务只引用修订和候选文件。"""
from sqlalchemy import Column, String, Integer, BigInteger, Boolean, DateTime, Text, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from .database import Base
from datetime import datetime


class LinkSheetImport(Base):
    __tablename__ = "link_sheet_imports"
    id = Column(String(32), primary_key=True)
    file_name = Column(Text, nullable=False)
    file_sha256 = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, index=True)
    statistics = Column(JSONB, nullable=False, default=dict)
    error = Column(Text, nullable=False, default="")
    affected_circles = Column(JSONB, nullable=False, default=list)
    materialization_targets = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now)


class LinkSheetRevision(Base):
    __tablename__ = "link_sheet_revisions"
    id = Column(String(32), primary_key=True)
    import_id = Column(String(32), ForeignKey("link_sheet_imports.id"), nullable=False, index=True)
    rjcode = Column(String(10), nullable=False, index=True)
    source_row = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    metadata_json = Column(JSONB, nullable=False)
    groups = Column(JSONB, nullable=False)
    errors = Column(JSONB, nullable=False)
    change_kind = Column(String(24), nullable=False, default="pending")
    reuse_revision_id = Column(String(32), ForeignKey("link_sheet_revisions.id"), index=True)
    __table_args__ = (Index("ix_link_sheet_revision_batch_code", "import_id", "rjcode"),)


class LinkSheetFile(Base):
    __tablename__ = "link_sheet_files"
    revision_id = Column(String(32), ForeignKey("link_sheet_revisions.id", ondelete="CASCADE"), primary_key=True)
    id = Column(String(32), primary_key=True)
    name = Column(Text, nullable=False)
    url = Column(Text, nullable=False)
    size_bytes = Column(BigInteger)
    raw_size = Column(Text, nullable=False)
    ordinal = Column(Integer, nullable=False)
    excluded = Column(Boolean, nullable=False)


class LinkSheetCurrent(Base):
    __tablename__ = "link_sheet_current"
    rjcode = Column(String(10), primary_key=True)
    revision_id = Column(String(32), ForeignKey("link_sheet_revisions.id"), nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=True)
