"""Parsing pipeline orchestration for resilient email ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Callable, Iterable, List, Literal, Optional

from loguru import logger

from app.parsers import parse_eml_bytes, parse_msg_file
from app.parsers.models import ParsedEmail

try:
    import mailparser  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    mailparser = None  # type: ignore[assignment]

EXTRACT_MSG_AVAILABLE = find_spec("extract_msg") is not None

DetectedType = Literal["eml", "msg", "unknown"]

OLE_HEADER = b"\xd0\xcf\x11\xe0"
ZIP_HEADER = b"PK\x03\x04"


@dataclass(slots=True)
class EmailCandidate:
    """Represents a file slated for parsing with detection metadata."""

    path: Path
    data: bytes
    detected_type: DetectedType
    size: int


@dataclass(slots=True)
class ParserAttempt:
    """Captures the outcome of a parser strategy."""

    name: str
    version: str
    status: Literal["success", "failed"]
    error_message: Optional[str] = None


@dataclass(slots=True)
class ParsingOutcome:
    parsed_email: Optional[ParsedEmail]
    attempts: List[ParserAttempt]


def detect_candidate(path: Path, data: bytes) -> EmailCandidate:
    detected_type: DetectedType = "unknown"
    lower_suffix = path.suffix.lower()
    header = data[:4]

    if header.startswith(OLE_HEADER) or lower_suffix == ".msg":
        detected_type = "msg"
    elif lower_suffix == ".eml":
        detected_type = "eml"
    elif header.startswith(ZIP_HEADER):
        detected_type = "eml"  # zipped MSG/EML not yet supported; default to MIME
    else:
        sample = data[:4096].lower()
        if b"content-type" in sample or b"mime-version" in sample or b"return-path" in sample:
            detected_type = "eml"

    return EmailCandidate(path=path, data=data, detected_type=detected_type, size=len(data))


def run_parsing_pipeline(candidate: EmailCandidate) -> ParsingOutcome:
    attempts: List[ParserAttempt] = []

    if candidate.detected_type != "msg" and not _looks_like_email(candidate.data):
        attempts.append(
            ParserAttempt(
                name="content_sniffer",
                version="1.0.0",
                status="failed",
                error_message="Payload does not resemble an email message.",
            )
        )
        return ParsingOutcome(parsed_email=None, attempts=attempts)

    for strategy in _strategies_for(candidate):
        name = strategy.name
        try:
            parsed = strategy.func(candidate)
        except Exception as exc:  # noqa: BLE001 - capture all parsing errors
            logger.debug("Parser %s failed for %s: %s", name, candidate.path.name, exc)
            attempts.append(
                ParserAttempt(
                    name=name,
                    version=strategy.version,
                    status="failed",
                    error_message=str(exc),
                )
            )
            continue

        attempts.append(ParserAttempt(name=name, version=strategy.version, status="success"))
        return ParsingOutcome(parsed_email=parsed, attempts=attempts)

    return ParsingOutcome(parsed_email=None, attempts=attempts)


class ParserStrategy:
    __slots__ = ("name", "target_types", "func", "version")

    def __init__(
        self,
        name: str,
        target_types: Iterable[DetectedType],
        func: Callable[[EmailCandidate], ParsedEmail],
        version: str = "1.0.0",
    ) -> None:
        self.name = name
        self.target_types = tuple(target_types)
        self.func = func
        self.version = version

    def supports(self, detected_type: DetectedType) -> bool:
        return not self.target_types or detected_type in self.target_types or "unknown" in self.target_types


def _strategies_for(candidate: EmailCandidate) -> List[ParserStrategy]:
    strategies: List[ParserStrategy] = []

    if candidate.detected_type in ("eml", "unknown"):
        strategies.append(
            ParserStrategy(
                name="eml_bytes_parser",
                target_types=("eml", "unknown"),
                func=lambda c: parse_eml_bytes(c.data),
            )
        )
        if mailparser is not None:
            strategies.append(
                ParserStrategy(
                    name="mailparser_fallback",
                    target_types=("eml", "unknown"),
                    func=_parse_with_mailparser,
                    version=getattr(mailparser, "__version__", "unknown"),
                )
            )

    if candidate.detected_type in ("msg", "unknown") and EXTRACT_MSG_AVAILABLE:
        strategies.append(
            ParserStrategy(
                name="msg_extract_msg",
                target_types=("msg", "unknown"),
                func=lambda c: parse_msg_file(c.path),
            )
        )

    return strategies


def _parse_with_mailparser(candidate: EmailCandidate) -> ParsedEmail:
    if mailparser is None:  # pragma: no cover - guarded earlier
        raise RuntimeError("mailparser is not installed")

    parsed = mailparser.parse_from_bytes(candidate.data)

    # Convert mailparser object into ParsedEmail by reusing existing helpers.
    return parse_eml_bytes(parsed.mail.as_bytes())


def parser_capabilities() -> dict:
    """Return diagnostic information about optional parsing dependencies."""
    return {
        "extract_msg": {
            "available": EXTRACT_MSG_AVAILABLE,
            "description": "Required for MSG parsing",
        },
        "mailparser": {
            "available": mailparser is not None,
            "description": "Improved EML fallback parser",
        },
    }


def _looks_like_email(data: bytes) -> bool:
    if not data:
        return False
    sample = data[:2048]
    if not sample.strip():
        return False
    ascii_ratio = sum(1 for b in sample if 9 <= b <= 126 or b in (10, 13)) / len(sample)
    if ascii_ratio < 0.6:
        return False
    lowered = sample.lower()
    return any(token in lowered for token in (b"subject:", b"from:", b"content-type", b"mime-version"))


