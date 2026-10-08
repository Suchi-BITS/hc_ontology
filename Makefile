# Convenience wrapper. Everything is implemented in scripts/dev.py (works on Windows too:
#   python scripts/dev.py <command>).
PYTHON ?= python3

.PHONY: help quickstart setup doctor validate test demo up load down serve lock

help:
	@$(PYTHON) scripts/dev.py --help

quickstart setup doctor validate test demo up load down serve lock:
	@$(PYTHON) scripts/dev.py $@
