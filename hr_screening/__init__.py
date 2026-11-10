"""Local, file-based HR screening workflow.

The package is intentionally small: Streamlit is the only UI, PDFs are read
locally, and one OpenRouter request is made per candidate (plus one per selected
candidate for interview questions).
"""

__all__ = ["__version__"]
__version__ = "1.0.0"
