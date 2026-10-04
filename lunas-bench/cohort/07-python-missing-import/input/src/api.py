"""Clock module: a small async helper exposing the current time.

``get_time`` is intentionally written to sleep briefly before returning
so that real callers can measure latency. The sleep is implemented via
``asyncio.sleep`` so it doesn't block the event loop.
"""

from datetime import datetime, timezone


async def get_time() -> dict[str, str]:
    """Return the current UTC time as ISO-8601 after a 1s pause."""
    # Simulate latency.
    await asyncio.sleep(1)
    return {"now": datetime.now(timezone.utc).isoformat()}
