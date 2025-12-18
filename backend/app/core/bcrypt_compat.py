"""
Compatibility helpers for pyca/bcrypt v4.2+ where __about__.__version__ was removed.

Passlib's bcrypt handler still inspects ``bcrypt.__about__.__version__`` to detect
backend capabilities. When that attribute is missing, Passlib emits warnings on every
hash/verify attempt. This shim recreates the attribute using the best available
version information so Passlib keeps working without noise.
"""

from __future__ import annotations

import logging
from importlib import metadata

logger = logging.getLogger(__name__)

try:
    import bcrypt as _bcrypt  # type: ignore
except Exception as exc:  # pragma: no cover - bcrypt might be optional in tests
    _bcrypt = None
    logger.debug("bcrypt package not available: %s", exc)


if _bcrypt and not hasattr(_bcrypt, "__about__"):
    class _About:
        __version__ = getattr(_bcrypt, "__version__", None)

    if not getattr(_About, "__version__", None):
        try:
            _About.__version__ = metadata.version("bcrypt")
        except metadata.PackageNotFoundError as exc:  # pragma: no cover
            logger.debug("Could not read bcrypt version from metadata: %s", exc)
            _About.__version__ = "unknown"

    _bcrypt.__about__ = _About()  # type: ignore[attr-defined]
    logger.info(
        "Patched bcrypt module to expose __about__.__version__=%s for passlib compatibility",
        _About.__version__,
    )

