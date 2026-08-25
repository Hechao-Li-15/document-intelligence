"""Incremental synchronization of supported Google Drive files."""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from sqlalchemy.orm import Session

from document_intelligence.extraction import extract_financial_record, extract_pdf_text
from document_intelligence.google_drive import download_file
from document_intelligence.models import DriveFile, SyncState


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "text/csv",
    "text/html",
}


@dataclass
class SyncSummary:
    """Counts returned to the Streamlit UI after a sync attempt."""

    total_files: int = 0
    new_files: int = 0
    updated_files: int = 0
    skipped_files: int = 0
    failed_files: int = 0


def list_supported_files(service, folder_id: str) -> list[dict[str, str]]:
    """List supported, non-trashed files in one Drive folder."""
    mime_types = " or ".join(
        f"mimeType = '{mime_type}'" for mime_type in SUPPORTED_MIME_TYPES
    )
    query = f"'{folder_id}' in parents and trashed = false and ({mime_types})"
    files = []
    page_token = None
    while True:
        response = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                orderBy="name",
                pageSize=1000,
                pageToken=page_token,
            )
            .execute()
        )
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return files


def _parse_modified_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def process_document(service, session: Session, document: DriveFile) -> None:
    """Download and extract one PDF, updating its persisted processing state."""
    print(f"PROCESSING: {document.name}", flush=True)
    logger.info("PROCESSING: %s", document.name)
    document.processing_status = "Processing"
    document.processing_error = None
    print(f"RETRYING: {document.name}", flush=True)
    logger.info("RETRYING: %s", document.name)

    print(f"DOWNLOADING: {document.name} from Google Drive", flush=True)
    logger.info("DOWNLOADING: %s from Google Drive", document.name)
    content = download_file(service, document.drive_file_id)
    print(f"DOWNLOADED: {document.name}", flush=True)
    logger.info("DOWNLOADED: %s", document.name)

    print(f"EXTRACTING PDF TEXT: {document.name}", flush=True)
    logger.info("EXTRACTING PDF TEXT: %s", document.name)
    extracted_text = extract_pdf_text(content)
    print(f"TEXT EXTRACTED: {len(extracted_text)} characters", flush=True)
    logger.info("TEXT EXTRACTED: %d characters", len(extracted_text))

    print(f"LLM EXTRACTION STARTED for {document.name}", flush=True)
    logger.info("LLM EXTRACTION STARTED for %s", document.name)
    extracted = extract_financial_record(extracted_text, document.name)
    print(f"LLM EXTRACTION COMPLETED for {document.name}", flush=True)
    logger.info("LLM EXTRACTION COMPLETED for %s", document.name)

    from document_intelligence.models import FinancialRecord

    record = session.query(FinancialRecord).filter_by(
        source_document_id=document.id
    ).one_or_none()
    if record is None:
        record = FinancialRecord(source_document_id=document.id)
        session.add(record)
    for field in (
        "fund_name", "reporting_period", "return_percentage", "benchmark_return",
        "assets_under_management", "currency", "source_filename",
    ):
        setattr(record, field, getattr(extracted, field))
    session.flush()
    print(f"FINANCIAL RECORD SAVED for {document.name}", flush=True)
    logger.info("FINANCIAL RECORD SAVED for %s", document.name)
    document.processing_status = "Successfully processed"
    document.processing_error = None
    print(f"STATUS UPDATED: {document.name} -> Successfully processed", flush=True)
    logger.info("STATUS UPDATED: %s -> Successfully processed", document.name)


def process_pending_documents(service, session: Session, folder_id: str) -> int:
    """Process every PDF awaiting extraction or retrying after a failure."""
    pending_documents = session.query(DriveFile).filter(
        DriveFile.mime_type == "application/pdf",
        DriveFile.processing_status.in_(
            ("Pending extraction", "Failed")
        ),
    ).all()
    print(f"DOCUMENTS FOUND FOR EXTRACTION: {len(pending_documents)}", flush=True)
    logger.info("DOCUMENTS FOUND FOR EXTRACTION: %d", len(pending_documents))
    failures = 0
    for document in pending_documents:
        print(f"PROCESSING PENDING DOCUMENT: {document.name}", flush=True)
        logger.info("PROCESSING PENDING DOCUMENT: %s", document.name)
        try:
            process_document(service, session, document)
            session.commit()
            print(f"COMMIT SUCCESS: {document.name}", flush=True)
            logger.info("COMMIT SUCCESS: %s", document.name)
        except Exception as error:
            print(f"EXTRACTION FAILED: {error}", flush=True)
            logger.exception("EXTRACTION FAILED: %s", error)
            document.processing_status = "Failed"
            document.processing_error = str(error)
            session.commit()
            print(f"ERROR SAVED: {document.name} -> {document.processing_error}", flush=True)
            logger.info("ERROR SAVED: %s -> %s", document.name, document.processing_error)
            failures += 1
    return failures


def sync_folder(service, session: Session, folder_id: str) -> SyncSummary:
    """Incrementally synchronize supported file metadata for one folder."""
    drive_files = list_supported_files(service, folder_id)
    summary = SyncSummary(total_files=len(drive_files))
    synced_at = datetime.now(timezone.utc).replace(tzinfo=None)

    for file_data in drive_files:
        existing = None
        try:
            modified_time = _parse_modified_time(file_data["modifiedTime"])
            existing = session.query(DriveFile).filter_by(
                drive_file_id=file_data["id"]
            ).one_or_none()

            if existing is None:
                session.add(
                    DriveFile(
                        drive_file_id=file_data["id"],
                        name=file_data["name"],
                        mime_type=file_data["mimeType"],
                        modified_time=modified_time,
                        folder_id=folder_id,
                        last_synced_at=synced_at,
                    )
                )
                session.flush()
                existing = session.query(DriveFile).filter_by(
                    drive_file_id=file_data["id"]
                ).one()
                summary.new_files += 1
                if file_data["mimeType"] == "application/pdf":
                    existing.processing_status = "Pending extraction"
                    existing.processing_error = None
                    print(f"NEW PDF: {existing.name} -> Pending extraction", flush=True)
            elif existing.modified_time == modified_time:
                if existing.processing_status == "Successfully processed":
                    summary.skipped_files += 1
                    print(f"SKIP: {existing.name} (unchanged and successful)", flush=True)
                elif existing.processing_status in {"Pending extraction", "Failed"}:
                    print(f"RETRY QUEUE: {existing.name} remains pending/failed", flush=True)
                    if file_data["mimeType"] == "application/pdf":
                        existing.processing_status = "Pending extraction"
                        existing.processing_error = None
                else:
                    summary.skipped_files += 1
                    print(f"SKIP: {existing.name} (unchanged)", flush=True)
            else:
                existing.name = file_data["name"]
                existing.mime_type = file_data["mimeType"]
                existing.modified_time = modified_time
                existing.folder_id = folder_id
                existing.last_synced_at = synced_at
                summary.updated_files += 1
                if file_data["mimeType"] == "application/pdf":
                    existing.processing_status = "Pending extraction"
                    existing.processing_error = None
                    print(f"UPDATED PDF: {existing.name} -> Pending extraction", flush=True)
        except Exception as error:
            logger.exception("Exception encountered synchronizing %s", file_data.get("name", file_data.get("id")))
            if existing is None:
                existing = session.query(DriveFile).filter_by(
                    drive_file_id=file_data.get("id")
                ).one_or_none()
            if existing is not None:
                existing.processing_status = "Failed"
                existing.processing_error = str(error)
            summary.failed_files += 1

    summary.failed_files += process_pending_documents(service, session, folder_id)

    if summary.failed_files == 0:
        session.merge(
            SyncState(folder_id=folder_id, last_successful_sync=synced_at)
        )
    session.commit()
    return summary