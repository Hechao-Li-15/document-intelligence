"""SQLAlchemy models for synchronized Google Drive metadata."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
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


class SyncState(Base):
	"""Last successful synchronization for a Drive folder."""

	__tablename__ = "sync_state"

	folder_id: Mapped[str] = mapped_column(String(255), primary_key=True)
	last_successful_sync: Mapped[datetime] = mapped_column(DateTime(timezone=True))
