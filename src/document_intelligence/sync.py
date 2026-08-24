"""Incremental synchronization of supported Google Drive files."""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from document_intelligence.models import DriveFile, SyncState


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


def sync_folder(service, session: Session, folder_id: str) -> SyncSummary:
    """Incrementally synchronize supported file metadata for one folder."""
    drive_files = list_supported_files(service, folder_id)
    summary = SyncSummary(total_files=len(drive_files))
    synced_at = datetime.now(timezone.utc).replace(tzinfo=None)

    for file_data in drive_files:
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
                summary.new_files += 1
            elif existing.modified_time == modified_time:
                summary.skipped_files += 1
            else:
                existing.name = file_data["name"]
                existing.mime_type = file_data["mimeType"]
                existing.modified_time = modified_time
                existing.folder_id = folder_id
                existing.last_synced_at = synced_at
                summary.updated_files += 1
        except Exception:
            summary.failed_files += 1

    if summary.failed_files == 0:
        session.merge(
            SyncState(folder_id=folder_id, last_successful_sync=synced_at)
        )
    session.commit()
    return summary