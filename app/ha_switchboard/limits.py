"""Single source of truth for App and wire-contract bounds."""

MAX_REQUEST_BYTES = 64_000
MAX_RESPONSE_BYTES = 64_000
MAX_UTTERANCE = 2_000
MAX_TEXT = 4_000
MAX_CONTEXT_ITEMS = 16
MAX_CANDIDATES = 64
MAX_PROFILE_CAPABILITIES = 2_000
MAX_DIAGNOSTIC_EVENTS = 256
MAX_DIAGNOSTIC_FIELDS = 32
MAX_ROUTES = 32
MAX_RETRY_ATTEMPTS = 2
REQUEST_READ_TIMEOUT = 10.0
MAX_REQUEST_WORKERS = 32
RATE_LIMIT_WINDOW_SECONDS = 60.0
RATE_LIMIT_REQUESTS = 120


def bounded_int(value: object, *, name: str, minimum: int, maximum: int) -> int:
    """Parse an integer option without accepting booleans or unbounded values."""

    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed
