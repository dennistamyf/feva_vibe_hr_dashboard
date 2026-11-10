"""Named application errors with safe, reviewer-readable messages."""


class HRScreeningError(Exception):
    """Base class for expected application failures."""


class InputValidationError(HRScreeningError):
    """The selected listing, template, batch, or top-N is invalid."""


class PdfExtractionError(HRScreeningError):
    """A PDF could not be read or produced no extractable text."""


class MissingProviderConfig(HRScreeningError):
    """The OpenRouter key or model handle is not configured."""


class ProviderRequestError(HRScreeningError):
    """The provider request failed after the allowed retry policy."""


class ResponseParseError(HRScreeningError):
    """The model response was not a single JSON object."""


class EvaluationValidationError(HRScreeningError):
    """The model response did not satisfy the evaluation schema."""


class DuplicateIdentityError(HRScreeningError):
    """Two candidates share an identity and need reviewer disambiguation."""


class RunInProgressError(HRScreeningError):
    """A second screening run was started while one was active."""


class OutputWriteError(HRScreeningError):
    """The output bundle could not be written safely."""
