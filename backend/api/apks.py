"""
DroidCortex — API Routes: APK management.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File

from backend.config import settings
from backend.models.database import APK, get_session
from backend.models.schemas import APKOut
from backend.services.adb_service import adb_service

router = APIRouter(prefix="/api/apks", tags=["apks"])


@router.post("/upload", response_model=APKOut)
async def upload_apk(file: UploadFile = File(...)):
    """Upload an APK file and extract its metadata."""
    if not file.filename or not file.filename.endswith(".apk"):
        raise HTTPException(400, "File must be an .apk file")

    # Save to disk
    storage_dir = Path(settings.apk_storage_path)
    storage_dir.mkdir(parents=True, exist_ok=True)
    file_path = storage_dir / file.filename

    # Handle duplicate filenames
    counter = 1
    original_stem = file_path.stem
    while file_path.exists():
        file_path = storage_dir / f"{original_stem}_{counter}.apk"
        counter += 1

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    file_size = len(content)

    # Analyze APK metadata
    apk_info = adb_service.analyze_apk(str(file_path))

    # Save to database
    session = get_session()
    try:
        apk = APK(
            filename=file_path.name,
            file_path=str(file_path),
            package_name=apk_info.package_name if apk_info else None,
            main_activity=apk_info.main_activity if apk_info else None,
            version_name=apk_info.version_name if apk_info else None,
            version_code=apk_info.version_code if apk_info else None,
            min_sdk=apk_info.min_sdk if apk_info else None,
            target_sdk=apk_info.target_sdk if apk_info else None,
            file_size=file_size,
        )
        session.add(apk)
        session.commit()
        session.refresh(apk)

        return APKOut.model_validate(apk)
    except Exception as exc:
        session.rollback()
        raise HTTPException(500, f"Database error: {exc}")
    finally:
        session.close()


@router.get("", response_model=list[APKOut])
async def list_apks():
    """List all uploaded APKs."""
    session = get_session()
    try:
        apks = session.query(APK).order_by(APK.uploaded_at.desc()).all()
        return [APKOut.model_validate(a) for a in apks]
    finally:
        session.close()


@router.get("/{apk_id}", response_model=APKOut)
async def get_apk(apk_id: int):
    """Get APK details."""
    session = get_session()
    try:
        apk = session.get(APK, apk_id)
        if not apk:
            raise HTTPException(404, f"APK {apk_id} not found")
        return APKOut.model_validate(apk)
    finally:
        session.close()


@router.delete("/{apk_id}")
async def delete_apk(apk_id: int):
    """Delete an APK and its file."""
    session = get_session()
    try:
        apk = session.get(APK, apk_id)
        if not apk:
            raise HTTPException(404, f"APK {apk_id} not found")

        # Remove file
        file_path = Path(apk.file_path)
        if file_path.exists():
            file_path.unlink()

        session.delete(apk)
        session.commit()
        return {"deleted": True, "id": apk_id}
    except Exception as exc:
        session.rollback()
        raise HTTPException(500, str(exc))
    finally:
        session.close()
