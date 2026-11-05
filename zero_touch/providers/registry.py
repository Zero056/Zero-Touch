"""Engine registry. Config selects engines by name only; no imports from data. No Frappe imports."""

from zero_touch.providers.engines import NullEngine, TextLayerStubEngine

_ENGINES = {
	NullEngine.name: NullEngine,
	TextLayerStubEngine.name: TextLayerStubEngine,
}


class UnknownEngine(KeyError):
	pass


def engine_names() -> list[str]:
	return sorted(_ENGINES)


def get_engine(name: str, provider_code: str = ""):
	try:
		factory = _ENGINES[name]
	except KeyError as exc:
		raise UnknownEngine(name) from exc
	return factory(provider_code)
