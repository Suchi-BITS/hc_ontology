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
        force=True,
    )

    memory_log = logging.getLogger("healthcare_ontology.agent.memory")
    memory_log.setLevel(level)

    return logging.getLogger("healthcare_ontology")
