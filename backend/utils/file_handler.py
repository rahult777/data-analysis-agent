"""Handles the full lifecycle of uploaded files: validation, temporary local storage,
Supabase Storage upload/download, and cleanup of temporary artifacts."""

import asyncio
import io
import logging
import uuid
from pathlib import Path

import pandas as pd

from backend.utils.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

TEMP_DIR = Path("backend/uploads")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

_ALLOWED_EXTENSIONS = {".csv", ".xls", ".xlsx"}
_STORAGE_BUCKET = "cleaned-datasets"


def validate_file(filename: str, content: bytes) -> None:
    extension = Path(filename).suffix.lower()
    if extension not in _ALLOWED_EXTENSIONS:
        raise ValueError(
            "USER_ERROR: Unsupported file type. Please upload a CSV or Excel file."
        )
    if len(content) > MAX_FILE_SIZE:
        raise ValueError(
            "USER_ERROR: File too large. Maximum supported file size is 100MB."
        )
    if len(content) == 0:
        raise ValueError(
            "USER_ERROR: This file is empty. Please upload a file with data."
        )
    if _has_no_data_rows(filename, content, extension):
        raise ValueError(
            "USER_ERROR: This file has no data rows. "
            "Please upload a file with at least one row of data."
        )


def _has_no_data_rows(filename: str, content: bytes, extension: str) -> bool:
    # Same pandas defaults as profiler.load_dataframe, limited to the first data row.
    # Any failure other than "no columns" is left for the pipeline to report (fail-open);
    # corrupted-file handling is out of scope here.
    buffer = io.BytesIO(content)
    try:
        if extension == ".csv":
            peek = pd.read_csv(buffer, nrows=1)
        else:
            peek = pd.read_excel(buffer, nrows=1)
            if peek.empty:
                # nrows=1 reads only the first two sheet rows and pandas drops trailing
                # blank ones, so a blank second row hides the data below it. Confirm
                # with the Profiler's full read before rejecting.
                peek = pd.read_excel(io.BytesIO(content))
    except pd.errors.EmptyDataError:
        return True
    except Exception as exc:
        logger.warning("Empty-data peek skipped for %s: %s", filename, exc)
        return False
    return peek.empty


async def save_temp_file(content: bytes, original_filename: str) -> str:
    suffix = Path(original_filename).suffix
    stored_filename = f"{uuid.uuid4()}{suffix}"
    dest = TEMP_DIR / stored_filename
    await asyncio.to_thread(dest.write_bytes, content)
    return stored_filename


async def upload_to_storage(analysis_id: str, local_parquet_path: str) -> None:
    file_bytes = await asyncio.to_thread(Path(local_parquet_path).read_bytes)
    storage_key = f"{analysis_id}.parquet"
    client = get_supabase_client()
    await asyncio.to_thread(
        client.storage.from_(_STORAGE_BUCKET).upload,
        storage_key,
        file_bytes,
    )
    exists = await asyncio.to_thread(
        client.storage.from_(_STORAGE_BUCKET).exists,
        storage_key,
    )
    if not exists:
        raise RuntimeError(
            f"Upload verification failed: {storage_key} not found in "
            f"'{_STORAGE_BUCKET}' bucket after upload."
        )


async def download_from_storage(analysis_id: str) -> str:
    storage_key = f"{analysis_id}.parquet"
    client = get_supabase_client()
    data: bytes = await asyncio.to_thread(
        client.storage.from_(_STORAGE_BUCKET).download,
        storage_key,
    )
    local_path = TEMP_DIR / f"{analysis_id}.parquet"
    await asyncio.to_thread(local_path.write_bytes, data)
    return str(local_path)


async def cleanup_temp_file(stored_filename: str) -> None:
    target = TEMP_DIR / stored_filename
    try:
        await asyncio.to_thread(lambda: target.unlink(missing_ok=True))
    except Exception as e:
        logger.warning("Failed to delete temp file %s: %s", stored_filename, e)
