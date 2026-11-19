"""TLS settings shared by every outbound HTTP client (upstream sources and model APIs).

By default the Mozilla CA bundle shipped with ``certifi`` is used, so a machine-wide
``SSL_CERT_FILE`` that lacks an upstream's root does not break verification. Set
``CIELO_CA_BUNDLE`` to a PEM file to use another bundle (for example a corporate one).
Verification is never disabled.
"""

from __future__ import annotations

import ssl
from collections.abc import Mapping

import certifi


def ssl_context(settings: Mapping[str, str] | None = None) -> ssl.SSLContext:
    bundle = (settings or {}).get("CIELO_CA_BUNDLE") or certifi.where()
    return ssl.create_default_context(cafile=bundle)
