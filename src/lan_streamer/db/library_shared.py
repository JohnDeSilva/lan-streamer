"""
Shared internal helpers used by both library_tv.py and library_movie.py.
"""

import json
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from lan_streamer.db.models import MediaFile


def get_session() -> Any:
    import lan_streamer.db.connection

    return lan_streamer.db.connection.get_session()


def _update_field_safely(existing_val: Any, incoming_val: Any) -> Any:
    """
    Prevents overwriting valid database values with null, empty, or placeholder "Unknown" values.
    """
    if incoming_val is None:
        return existing_val
    if isinstance(incoming_val, str) and incoming_val in ("", "Unknown"):
        return existing_val
    if isinstance(incoming_val, (list, dict)) and not incoming_val:
        return existing_val
    return incoming_val


def _sync_media_files(
    session: Session, owner: Any, versions_data: List[Dict[str, Any]] | None
) -> None:
    if versions_data is None:
        return

    incoming_paths = {v["path"] for v in versions_data if v.get("path")}

    # First, resolve/deduplicate any transient MediaFile objects created by setters
    # against existing database records to avoid UNIQUE constraint violations on flush.
    for path in incoming_paths:
        db_mf = session.scalars(select(MediaFile).where(MediaFile.path == path)).first()
        if not db_mf:
            for obj in session.new:
                if isinstance(obj, MediaFile) and obj.path == path:
                    db_mf = obj
                    break
        if db_mf:
            incorrect_mfs = [
                mf_obj
                for mf_obj in list(owner.media_files)
                if mf_obj.path == path and mf_obj != db_mf
            ]
            for mf_obj in incorrect_mfs:
                owner.media_files.remove(mf_obj)
                if mf_obj in session:
                    session.expunge(mf_obj)
            if db_mf not in owner.media_files:
                owner.media_files.append(db_mf)

    # Remove existing files not in incoming
    existing_files = {mf.path: mf for mf in owner.media_files}
    deleted_any = False
    for path, mf in list(existing_files.items()):
        if path not in incoming_paths:
            owner.media_files.remove(mf)
            # Only delete the media file from database if it's no longer referenced
            has_other_refs = any(ep != owner for ep in mf.episodes) or any(
                mv != owner for mv in mf.movies
            )
            if not has_other_refs:
                session.delete(mf)
                deleted_any = True

    # Flush deletes immediately so the database unique constraint is freed
    if deleted_any:
        session.flush()

    # Add or update files
    for v in versions_data:
        path = v.get("path")
        if not path:
            continue

        mf = None
        for existing_mf in owner.media_files:
            if existing_mf.path == path:
                mf = existing_mf
                break

        if not mf:
            # Look for the correct MediaFile in the database or session.new
            db_mf = session.scalars(
                select(MediaFile).where(MediaFile.path == path)
            ).first()
            if not db_mf:
                for obj in session.new:
                    if (
                        isinstance(obj, MediaFile)
                        and obj.path == path
                        and obj not in owner.media_files
                    ):
                        db_mf = obj
                        break

            if db_mf:
                if db_mf not in owner.media_files:
                    owner.media_files.append(db_mf)
                mf = db_mf
            else:
                mf = MediaFile(path=path)
                owner.media_files.append(mf)
                session.add(mf)

        mf.size_bytes = _update_field_safely(mf.size_bytes, v.get("size_bytes"))
        mf.video_type = _update_field_safely(mf.video_type, v.get("video_type"))
        mf.video_codec = _update_field_safely(mf.video_codec, v.get("video_codec"))
        mf.resolution = _update_field_safely(mf.resolution, v.get("resolution"))
        mf.bit_rate = _update_field_safely(mf.bit_rate, v.get("bit_rate"))

        incoming_audio = v.get("audio_tracks")
        if incoming_audio is not None and len(incoming_audio) > 0:
            mf.audio_tracks = json.dumps(incoming_audio)
        incoming_subs = v.get("subtitle_tracks")
        if incoming_subs is not None and len(incoming_subs) > 0:
            mf.subtitle_tracks = json.dumps(incoming_subs)
