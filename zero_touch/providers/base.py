"""Provider contract (docs/architecture/05-provider-abstraction.md). No Frappe imports."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class ErrorCode(str, Enum):
	TIMEOUT = "TIMEOUT"
	RATE_LIMITED = "RATE_LIMITED"
	UNAVAILABLE = "UNAVAILABLE"
	AUTH = "AUTH"
	BAD_INPUT = "BAD_INPUT"
	UNSUPPORTED = "UNSUPPORTED"
	INVALID_OUTPUT = "INVALID_OUTPUT"
	POLICY_BLOCKED = "POLICY_BLOCKED"


TRANSIENT_ERRORS = frozenset({ErrorCode.TIMEOUT, ErrorCode.RATE_LIMITED, ErrorCode.UNAVAILABLE})

PROVIDER_KINDS = ("text_layer", "ocr", "classifier", "llm")


@dataclass(frozen=True)
class Capabilities:
	kinds: frozenset[str]
	languages: frozenset[str] = frozenset()
	data_residency: str = "local"
	max_pages: int = 50
	max_file_bytes: int = 20 * 1024 * 1024


@dataclass(frozen=True)
class DocumentInput:
	content: bytes
	extension: str
	languages: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderError:
	code: ErrorCode
	message: str

	@property
	def transient(self) -> bool:
		return self.code in TRANSIENT_ERRORS


@dataclass(frozen=True)
class ExtractionResult:
	ok: bool
	provider_code: str
	payload: dict | None = None
	errors: tuple[ProviderError, ...] = field(default_factory=tuple)


class Engine(Protocol):
	name: str
	capabilities: Capabilities

	def extract(self, document: DocumentInput) -> ExtractionResult: ...
