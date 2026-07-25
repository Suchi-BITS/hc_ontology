"""Custom exceptions for SHACL validation."""


class ShaclError(Exception):
    """Base SHACL error."""


class ShaclShapeLoadError(ShaclError):
    """Raised when shape files cannot be loaded or parsed."""


class ShaclDataLoadError(ShaclError):
    """Raised when RDF/OWL data cannot be loaded."""


class ShaclValidationError(ShaclError):
    """Raised when the validation engine fails unexpectedly."""
