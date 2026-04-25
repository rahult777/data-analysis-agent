"""Handles the full lifecycle of uploaded files: validation, temporary local storage,
Supabase Storage upload/download, and cleanup of temporary artifacts."""

import asyncio
import logging
import uuid
from pathlib import Path

from backend.utils.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

TEMP_DIR = Path("backend/uploads")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

_ALLOWED_EXTENSIONS = {".csv", ".xls", ".xlsx"}
_STORAGE_BUCKET = "cleaned-datasets"


def validate_file(filename: str, file_size: int) -> None:
    extension = Path(filename).suffix.lower()
    if extension not in _ALLOWED_EXTENSIONS:
        raise ValueError(
            "USER_ERROR: Unsupported file type. Please upload a CSV or Excel file."
        )
    if file_size > MAX_FILE_SIZE:
        raise ValueError(
            "USER_ERROR: File too large. Maximum supported file size is 100MB."
        )


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
