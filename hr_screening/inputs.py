"""Input discovery and validation.

Discovery is based on folder contents, not hard-coded candidate names. All
paths are resolved from the project's ``HR_dummy_data`` folder rather than the
process working directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import DATA_ROOT
from .errors import InputValidationError

_LISTING_ROOT = "listing"
_BATCH_ROOT = "candidates"
_TEMPLATE_NAME = "scoring template.txt"


@dataclass(frozen=True)
class ListingInput:
    key: str
    directory: Path
    listing_text_path: Path
    scoring_template_path: Path
    listing_text: str
    scoring_template: str


@dataclass(frozen=True)
class BatchInput:
    key: str
    directory: Path
    pdf_paths: tuple[Path, ...]

    @property
    def count(self) -> int:
        return len(self.pdf_paths)


@dataclass(frozen=True)
class Selection:
    listing: ListingInput
    batch: BatchInput
    top_n: int


def _safe_child(root: Path, key: str, kind: str) -> Path:
    if not key or key in {".", ".."} or Path(key).name != key:
        raise InputValidationError(
            f"Invalid {kind} selection '{key}'. Select a folder name from the list."
        )
    path = root / key
    if not path.is_dir():
        raise InputValidationError(
            f"The selected {kind} folder does not exist: {path}"
        )
    try:
        if path.resolve().parent != root.resolve():
            raise InputValidationError(
                f"The selected {kind} folder is outside the expected data folder: {path}"
            )
    except OSError as exc:
        raise InputValidationError(
            f"The selected {kind} folder could not be resolved: {path}"
        ) from exc
    return path


def list_listing_keys(data_root: Path = DATA_ROOT) -> list[str]:
    root = Path(data_root) / _LISTING_ROOT
    if not root.is_dir():
        return []
    return sorted(
        (p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")),
        key=str.lower,
    )


def list_batch_keys(data_root: Path = DATA_ROOT) -> list[str]:
    root = Path(data_root) / _BATCH_ROOT
    if not root.is_dir():
        return []
    return sorted(
        (p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")),
        key=str.lower,
    )


def load_listing(listing_key: str, data_root: Path = DATA_ROOT) -> ListingInput:
    listing_root = Path(data_root) / _LISTING_ROOT
    if not listing_root.is_dir():
        raise InputValidationError(
            f"The listing folder is missing: {listing_root}"
        )

    directory = _safe_child(listing_root, listing_key, "listing")
    template_path = directory / _TEMPLATE_NAME
    if not template_path.is_file():
        raise InputValidationError(
            f"The scoring template is missing: {template_path}"
        )

    text_files = sorted(
        (
            p
            for p in directory.iterdir()
            if p.is_file()
            and p.suffix.lower() == ".txt"
            and p.name.lower() != _TEMPLATE_NAME.lower()
        ),
        key=lambda p: p.name.lower(),
    )
    if not text_files:
        raise InputValidationError(
            f"No job-listing text file was found in {directory}. "
            f"Expected one .txt file other than '{_TEMPLATE_NAME}'."
        )
    if len(text_files) > 1:
        names = ", ".join(p.name for p in text_files)
        raise InputValidationError(
            f"Multiple job-listing text files were found in {directory}: {names}. "
            "Keep exactly one listing text file."
        )

    listing_path = text_files[0]
    try:
        listing_text = listing_path.read_text(encoding="utf-8").strip()
        scoring_template = template_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise InputValidationError(
            f"An input file could not be read as UTF-8 text: {listing_path} or {template_path}"
        ) from exc

    if not listing_text:
        raise InputValidationError(f"The job listing is empty: {listing_path}")
    if not scoring_template:
        raise InputValidationError(f"The scoring template is empty: {template_path}")

    return ListingInput(
        key=listing_key,
        directory=directory,
        listing_text_path=listing_path,
        scoring_template_path=template_path,
        listing_text=listing_text,
        scoring_template=scoring_template,
    )


def discover_batch(batch_key: str, data_root: Path = DATA_ROOT) -> BatchInput:
    batch_root = Path(data_root) / _BATCH_ROOT
    if not batch_root.is_dir():
        raise InputValidationError(
            f"The candidate batch folder is missing: {batch_root}"
        )

    directory = _safe_child(batch_root, batch_key, "candidate batch")
    pdf_paths = tuple(
        sorted(
            (
                p
                for p in directory.iterdir()
                if p.is_file() and p.suffix.lower() == ".pdf"
            ),
            key=lambda p: p.name.lower(),
        )
    )
    if not pdf_paths:
        raise InputValidationError(
            f"No PDF files were found in candidate batch '{batch_key}' ({directory}). "
            "The run was not started."
        )

    return BatchInput(key=batch_key, directory=directory, pdf_paths=pdf_paths)


def validate_top_n(top_n: object, discovered: int) -> int:
    if isinstance(top_n, bool) or not isinstance(top_n, int):
        raise InputValidationError(
            f"Top N must be a whole number from 1 to {discovered}."
        )
    if top_n < 1 or top_n > discovered:
        raise InputValidationError(
            f"Top N must be a whole number from 1 to {discovered}; received {top_n}."
        )
    return top_n


def validate_selection(
    listing_key: str,
    batch_key: str,
    top_n: object,
    data_root: Path = DATA_ROOT,
) -> Selection:
    listing = load_listing(listing_key, data_root=data_root)
    batch = discover_batch(batch_key, data_root=data_root)
    validated_top_n = validate_top_n(top_n, batch.count)
    return Selection(listing=listing, batch=batch, top_n=validated_top_n)
