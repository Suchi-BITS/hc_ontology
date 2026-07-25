import logging
import sys

from core.config import get_settings


def setup_logging():
    settings = get_settings()
    level = getattr(logging, settings["log_level"].upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    return logging.getLogger("healthcare_ontology")
