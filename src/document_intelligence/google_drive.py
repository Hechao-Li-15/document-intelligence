"""Google Drive OAuth authentication and folder listing."""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
TOKEN_FILE = PROJECT_ROOT / "token.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


class GoogleDriveSetupError(RuntimeError):
    """Raised when local Google OAuth setup is incomplete."""


def get_drive_service() -> Resource:
    """Load a saved token or run the local Google OAuth flow."""
    credentials = None
    if TOKEN_FILE.exists():
        credentials = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    elif not credentials or not credentials.valid:
        if not CREDENTIALS_FILE.exists():
            raise GoogleDriveSetupError(
                "credentials.json was not found in the project root. "
                "Download an OAuth desktop-app client from Google Cloud Console."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
        credentials = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
    return build("drive", "v3", credentials=credentials)


def list_drive_folders(service: Resource) -> list[dict[str, str]]:
    """Return non-trashed folders visible to the authenticated user."""
    response = (
        service.files()
        .list(
            q="mimeType = 'application/vnd.google-apps.folder' and trashed = false",
            spaces="drive",
            fields="files(id, name, webViewLink)",
            orderBy="name",
            pageSize=1000,
        )
        .execute()
    )
    return response.get("files", [])
