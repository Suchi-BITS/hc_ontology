"""Configure TLS trust for OpenAI, LangSmith, and PyPI on Windows/corporate networks."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("healthcare_ontology.ssl")

_configured = False


def configure_ssl() -> None:
    """Use OS trust store (Windows) or certifi bundle before any HTTPS clients start."""
    global _configured
    if _configured:
        return

    try:
        import truststore

        truststore.inject_into_ssl()
        logger.debug("TLS: truststore injected (OS certificate store)")
        _configured = True
        return
    except ImportError:
        pass

    try:
        import certifi

        bundle = certifi.where()
        os.environ.setdefault("SSL_CERT_FILE", bundle)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)
        logger.debug("TLS: using certifi bundle at %s", bundle)
    except ImportError:
        logger.warning("TLS: neither truststore nor certifi installed — HTTPS may fail")

    _configured = True
