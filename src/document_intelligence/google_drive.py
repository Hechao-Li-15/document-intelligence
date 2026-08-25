"""Google Drive OAuth authentication and folder listing."""

from io import BytesIO
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build
from googleapiclient.http import MediaIoBaseDownload


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
TOKEN_FILE = PROJECT_ROOT / "token.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


class GoogleDriveSetupError(RuntimeError):
    """Raised when local Google OAuth setup is incomplete."""


def _credentials_have_required_scope(credentials: Credentials) -> bool:
    """Return whether saved credentials include exactly the required scope."""
    return set(credentials.scopes or ()) == set(SCOPES)


def get_drive_service() -> Resource:
    """Load a saved token or run the local Google OAuth flow."""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if not _credentials_have_required_scope(creds):
            TOKEN_FILE.unlink()
            creds = None

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        if not CREDENTIALS_FILE.exists():
            raise GoogleDriveSetupError(
                "credentials.json was not found in the project root. "
                "Download an OAuth desktop-app client from Google Cloud Console."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
        creds = flow.run_local_server(port=0)

    if not _credentials_have_required_scope(creds):
        raise GoogleDriveSetupError(
            "Google OAuth did not grant the required read-only Drive scope."
        )

    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return build("drive", "v3", credentials=creds)


def list_drive_folders(service: Resource) -> list[dict[str, str]]:
    """Return non-trashed folders visible to the authenticated user."""
    folders = []
    page_token = None
    while True:
        response = (
            service.files()
            .list(
                q="mimeType = 'application/vnd.google-apps.folder' and trashed = false",
                spaces="drive",
                fields="nextPageToken, files(id,name)",
                orderBy="name",
                pageSize=1000,
                pageToken=page_token,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            )
            .execute()
        )
        folders.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            return folders


def download_file(service: Resource, file_id: str) -> bytes:
    """Download a Drive file into memory."""
    request = service.files().get_media(fileId=file_id)
    buffer = BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()
