from __future__ import annotations

from pathlib import Path
from typing import Iterator, List

import pytest
import shutil
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig
from app.db.models import Base
from scripts import create_dataset


@pytest.fixture()
def temp_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    cache_dir = data_dir / "cache"
    input_dir = data_dir / "input"
    output_dir = data_dir / "output"
    scripts_dir = data_dir / "scripts"
    log_dir = data_dir / "logs"
    for directory in (cache_dir, input_dir, output_dir, scripts_dir, log_dir):
        directory.mkdir(parents=True, exist_ok=True)

    db_path = tmp_path / "email_handler.db"
    return AppConfig(
        database_url=f"sqlite:///{db_path}",
        pickle_cache_dir=cache_dir,
        input_dir=input_dir,
        output_dir=output_dir,
        scripts_dir=scripts_dir,
        log_dir=log_dir,
        env_name="test",
    )


@pytest.fixture()
def db_session(temp_config: AppConfig) -> Iterator[Session]:
    engine = create_engine(temp_config.database_url, future=True)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(scope="session")
def generated_dataset(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("dataset")
    create_dataset(root, email_count=80, seed=314152)
    return root


@pytest.fixture()
def populated_input(temp_config: AppConfig, generated_dataset: Path) -> List[Path]:
    source_dir = generated_dataset / "emails"
    destination = temp_config.input_dir
    paths: List[Path] = []
    for email_file in source_dir.glob("*.eml"):
        target = destination / email_file.name
        shutil.copy2(email_file, target)
        paths.append(target)
    return paths

