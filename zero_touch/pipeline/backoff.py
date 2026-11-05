"""Retry delay with exponential growth and full jitter. No Frappe imports."""

import random
from collections.abc import Callable


def backoff_seconds(
	attempt: int,
	base: int = 60,
	cap: int = 3600,
	jitter: Callable[[], float] = random.random,
) -> int:
	if attempt < 1:
		raise ValueError("attempt must be >= 1")
	if base < 1 or cap < 1:
		raise ValueError("base and cap must be >= 1")
	ceiling = min(cap, base * (2 ** (attempt - 1)))
	fraction = min(max(jitter(), 0.0), 1.0)
	return int(ceiling * fraction)
