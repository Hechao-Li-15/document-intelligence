"""SQLAlchemy models for synchronized Google Drive metadata."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from document_intelligence.database import Base


class DriveFile(Base):
	"""A supported file discovered in a selected Google Drive folder."""

	__tablename__ = "drive_files"

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	drive_file_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
	name: Mapped[str] = mapped_column(String(500))
	mime_type: Mapped[str] = mapped_column(String(150))
	modified_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
	folder_id: Mapped[str] = mapped_column(String(255), index=True)
	last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
	processing_status: Mapped[str] = mapped_column(String(40), default="Pending extraction")
	processing_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class SyncState(Base):
	"""Last successful synchronization for a Drive folder."""

	__tablename__ = "sync_state"

	folder_id: Mapped[str] = mapped_column(String(255), primary_key=True)
	last_successful_sync: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FinancialRecord(Base):
	"""Normalized financial data extracted from one Drive document."""

	__tablename__ = "financial_records"

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	source_document_id: Mapped[int] = mapped_column(ForeignKey("drive_files.id"), unique=True)
	fund_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
	reporting_period: Mapped[str | None] = mapped_column(String(100), nullable=True)
	return_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
	benchmark_return: Mapped[float | None] = mapped_column(Float, nullable=True)
	assets_under_management: Mapped[float | None] = mapped_column(Float, nullable=True)
	currency: Mapped[str | None] = mapped_column(String(20), nullable=True)
	source_filename: Mapped[str] = mapped_column(String(500))
