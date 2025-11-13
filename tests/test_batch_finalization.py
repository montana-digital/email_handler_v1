from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.db.models import PickleBatch
from app.services.batch_finalization import ARCHIVE_SUBDIR, finalize_batch


def _create_batch(db_session, temp_config) -> PickleBatch:
    pickle_path = temp_config.pickle_cache_dir / "batch_test.pkl"
    pickle_path.write_bytes(b"payload")

    batch = PickleBatch(
        batch_name="batch_test",
        file_path=str(pickle_path),
        record_count=2,
        status="draft",
    )
    db_session.add(batch)
    db_session.commit()
    return batch


def test_finalize_batch_moves_pickle_and_updates_status(db_session, temp_config):
    batch = _create_batch(db_session, temp_config)

    result = finalize_batch(db_session, batch.id, config=temp_config)

    assert result is not None
    assert result.status == "finalized"
    assert result.archived_path is not None
    assert result.archived_path.parent == temp_config.output_dir / ARCHIVE_SUBDIR
    assert result.archived_path.exists()

    refreshed = db_session.get(PickleBatch, batch.id)
    assert refreshed.status == "finalized"
    assert refreshed.uploaded_at is not None
    assert refreshed.file_path == str(result.archived_path)


def test_finalize_batch_handles_missing_file(db_session, temp_config):
    batch = PickleBatch(
        batch_name="missing_pickles",
        file_path=str(temp_config.pickle_cache_dir / "missing.pkl"),
        record_count=1,
        status="draft",
    )
    db_session.add(batch)
    db_session.commit()

    result = finalize_batch(db_session, batch.id, config=temp_config)

    assert result is not None
    assert result.archived_path is None

    refreshed = db_session.get(PickleBatch, batch.id)
    assert refreshed.status == "finalized"
    assert refreshed.uploaded_at is not None

