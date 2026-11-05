"""Built-in engines. Phase 1 ships placeholders only: they never produce data. No Frappe imports."""

from zero_touch.providers.base import (
	Capabilities,
	DocumentInput,
	ErrorCode,
	ExtractionResult,
	ProviderError,
)


class NullEngine:
	name = "null"
	capabilities = Capabilities(kinds=frozenset(), data_residency="local")

	def __init__(self, provider_code: str = ""):
		self.provider_code = provider_code or self.name

	def extract(self, document: DocumentInput) -> ExtractionResult:
		return ExtractionResult(
			ok=False,
			provider_code=self.provider_code,
			errors=(ProviderError(ErrorCode.UNSUPPORTED, "No extraction engine is configured"),),
		)


class TextLayerStubEngine:
	name = "text_layer_stub"
	capabilities = Capabilities(kinds=frozenset({"text_layer"}), data_residency="local")

	def __init__(self, provider_code: str = ""):
		self.provider_code = provider_code or self.name

	def extract(self, document: DocumentInput) -> ExtractionResult:
		return ExtractionResult(
			ok=False,
			provider_code=self.provider_code,
			errors=(ProviderError(ErrorCode.UNSUPPORTED, "Text extraction is not available in this release"),),
		)
