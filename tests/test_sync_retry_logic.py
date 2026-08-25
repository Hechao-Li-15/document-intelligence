from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from document_intelligence.database import Base
from document_intelligence.models import DriveFile
from document_intelligence.sync import sync_folder


def test_sync_folder_retries_failed_document_without_skipping(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        document = DriveFile(
            drive_file_id="file-123",
            name="report.pdf",
            mime_type="application/pdf",
            modified_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            folder_id="folder-1",
            last_synced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            processing_status="Failed",
            processing_error="Configuration error while retrying document extraction.",
        )
        session.add(document)
        session.commit()

        monkeypatch.setattr(
            "document_intelligence.sync.list_supported_files",
            lambda service, folder_id: [{
                "id": "file-123",
                "name": "report.pdf",
                "mimeType": "application/pdf",
                "modifiedTime": "2024-01-01T00:00:00Z",
            }],
        )

        monkeypatch.setattr(
            "document_intelligence.sync.process_pending_documents",
            lambda service, session_obj, folder_id: 0,
        )

        summary = sync_folder(None, session, "folder-1")
        session.refresh(document)

        assert summary.skipped_files == 0
        assert document.processing_status == "Pending extraction"
        assert document.processing_error is None
