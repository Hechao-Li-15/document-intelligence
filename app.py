"""Streamlit user interface for the Document Intelligence application."""

from datetime import datetime
import pandas as pd
import streamlit as st
from sqlalchemy import inspect, text
from document_intelligence.database import SessionLocal, engine, init_db
from document_intelligence.google_drive import (
    GoogleDriveSetupError,
    get_drive_service,
    list_drive_folders,
)
from document_intelligence.models import DriveFile, SyncState
from document_intelligence.sync import sync_folder

init_db()

st.set_page_config(page_title="Document Intelligence", page_icon="DOC", layout="wide")

def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "Never"
    return value.strftime("%Y-%m-%d %H:%M UTC")

def load_financial_records() -> pd.DataFrame:
    """Read extracted records when the extraction table is available."""
    table_names = set(inspect(engine).get_table_names())
    for table_name in ("financial_records", "extracted_records"):
        if table_name in table_names:
            return pd.read_sql(text(f'SELECT * FROM "{table_name}"'), engine)
    return pd.DataFrame()

def answer_question(question: str, records: pd.DataFrame) -> tuple[str, list[str]]:
    """Answer only from records already loaded from SQLite."""
    if records.empty:
        return "No extracted financial records are available yet.", []

    normalized_columns = {
        column.lower().replace(" ", "_"): column for column in records.columns
    }
    return_column = next(
        (
            normalized_columns[name]
            for name in ("return_percentage", "return", "return_pct")
            if name in normalized_columns
        ),
        None,
    )
    fund_column = next(
        (normalized_columns[name] for name in ("fund_name", "fund") if name in normalized_columns),
        None,
    )
    source_column = next(
        (
            normalized_columns[name]
            for name in ("source_filename", "source_file", "filename")
            if name in normalized_columns
        ),
        None,
    )
    date_column = next(
        (
            normalized_columns[name]
            for name in ("reporting_date", "reporting_period", "date")
            if name in normalized_columns
        ),
        None,
    )

    if return_column and any(word in question.lower() for word in ("best", "highest", "top")):
        candidates = records.copy()
        if date_column and "january" in question.lower():
            dates = pd.to_datetime(candidates[date_column], errors="coerce")
            candidates = candidates[dates.dt.month == 1]
        returns = pd.to_numeric(
            candidates[return_column].astype(str).str.rstrip("%"), errors="coerce"
        )
        candidates = candidates.loc[returns.notna()].copy()
        if not candidates.empty:
            winner_index = returns.loc[candidates.index].idxmax()
            winner = candidates.loc[winner_index]
            fund = f" for {winner[fund_column]}" if fund_column else ""
            source = (
                [str(winner[source_column])]
                if source_column and pd.notna(winner[source_column])
                else []
            )
            return f"The best return{fund} was {winner[return_column]}.", source

    return (
        "I can answer questions from the available records, but this question "
        "needs a supported financial query handler.",
        [],
    )

st.title("Document Intelligence")
st.caption("Google Drive documents, processing status, and grounded financial records")

st.header("Google Drive Connection")
token_exists = (st.session_state.get("drive_connected") or False)
if token_exists:
    st.success("Google Drive connected")
else:
    st.info("Google Drive is not connected. Connect it to load your Drive folders.")
if st.button("Connect Google Drive", type="primary", key="connect_google_drive_dashboard"):
    try:
        with st.spinner("Waiting for Google authentication..."):
            drive_service = get_drive_service()
            st.session_state.drive_folders = list_drive_folders(drive_service)
            st.session_state.drive_connected = True
        st.success("Google Drive connected.")
    except GoogleDriveSetupError as error:
        st.error(str(error))
    except Exception as error:
        st.error(f"Google Drive connection failed: {error}")

folders = st.session_state.get("drive_folders", [])
if folders:
    folder_options = {folder["name"]: folder["id"] for folder in folders}
    selected_folder = st.selectbox(
        "Monitored folder",
        options=list(folder_options),
        index=(
            list(folder_options.values()).index(st.session_state["selected_folder_id"])
            if st.session_state.get("selected_folder_id") in folder_options.values()
            else 0
        ),
    )
    st.session_state.selected_folder_id = folder_options[selected_folder]
else:
    st.warning("No folder is selected. Connect Google Drive and choose a folder.")
if st.session_state.get("selected_folder_id"):
    folder_id = st.session_state.selected_folder_id
    with SessionLocal() as session:
        sync_state = session.get(SyncState, folder_id)
    st.caption(f"Last successful sync: {format_datetime(sync_state.last_successful_sync if sync_state else None)}")

    if st.button("Sync Google Drive", key="sync_google_drive_dashboard"):
        try:
            with st.spinner("Synchronizing supported files..."):
                drive_service = get_drive_service()
                with SessionLocal() as session:
                    st.session_state.sync_summary = sync_folder(
                        drive_service, session, folder_id
                    )
            st.success("Google Drive synchronization completed.")
            st.rerun()
        except GoogleDriveSetupError as error:
            st.error(str(error))
        except Exception as error:
            st.error(f"Google Drive synchronization failed: {error}")

summary = st.session_state.get("sync_summary")
if summary:
    st.subheader("Latest Sync Results")
    columns = st.columns(5)
    for column, label, value in zip(
        columns,
    ("Total files", "New", "Updated", "Skipped", "Failed"),
    (summary.total_files, summary.new_files, summary.updated_files,
     summary.skipped_files, summary.failed_files),
    ):
        column.metric(label, value)

st.header("Document Status")
with SessionLocal() as session:
    document_rows = session.query(DriveFile).order_by(DriveFile.name).all()

if not document_rows:
    st.info("No documents have been synchronized yet.")
else:
    st.metric("Total documents", len(document_rows))
    st.metric("Successfully processed", 0, help="Extraction is not available yet.")
    st.metric("Failed", summary.failed_files if summary else 0)
    documents = pd.DataFrame(
        [
            {
                "Filename": document.name,
                "File type": document.mime_type,
                "Processing status": "Pending extraction",
                "Modified date": format_datetime(document.modified_time),
            }
            for document in document_rows
        ]
    )
    st.dataframe(documents, use_container_width=True, hide_index=True)

st.header("Extracted Performance Data")
records = load_financial_records()
if records.empty:
    st.info("No extracted financial records are available yet.")
else:
    fund_column = next((column for column in records.columns if column.lower() in {"fund_name", "fund name"}), None)
    date_column = next((column for column in records.columns if column.lower() in {"reporting_date", "reporting date", "reporting_period"}), None)
    filter_columns = st.columns(2)
    with filter_columns[0]:
        selected_funds = st.multiselect("Fund name", sorted(records[fund_column].dropna().unique())) if fund_column else []
    with filter_columns[1]:
        selected_dates = st.multiselect("Reporting date", sorted(records[date_column].dropna().unique())) if date_column else []
    filtered_records = records
    if selected_funds:
        filtered_records = filtered_records[filtered_records[fund_column].isin(selected_funds)]
    if selected_dates:
        filtered_records = filtered_records[filtered_records[date_column].isin(selected_dates)]
    st.dataframe(filtered_records, use_container_width=True, hide_index=True)

st.header("Ask Your Documents")
question = st.text_input("Ask a question about the extracted financial data")
if question:
    answer, sources = answer_question(question, records)
    st.write(answer)
    if sources:
        st.caption("Sources: " + ", ".join(sources))
    elif not records.empty:
        st.caption("No source records were selected for this answer.")
