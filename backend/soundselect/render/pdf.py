"""HTML pages to PDF with WeasyPrint, so a page and its PDF always match.

WeasyPrint needs the Pango text library from the system (on a Mac: ``brew install pango``).
Everything else in SoundSelect works without it.
"""

from __future__ import annotations


class PdfUnavailable(RuntimeError):
    """PDF output needs WeasyPrint and the Pango library."""


def html_to_pdf(html: str) -> bytes:
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:  # OSError: Pango is missing
        raise PdfUnavailable(
            "Making PDFs needs the Pango library. On a Mac run 'brew install pango'; on "
            "Ubuntu or Debian run 'sudo apt install libpango-1.0-0 libpangoft2-1.0-0'. "
            f"({exc})"
        ) from exc
    return HTML(string=html).write_pdf()


def pdf_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True
