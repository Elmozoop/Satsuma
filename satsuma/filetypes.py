"""Map a path to a coarse category used to pick the menu."""
from __future__ import annotations

from pathlib import Path

IMAGE_EXT = {
    ".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".webp", ".bmp", ".gif",
    ".tif", ".tiff", ".ico", ".ppm", ".pgm", ".tga", ".heic", ".heif", ".avif",
}
VIDEO_EXT = {
    ".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm", ".wmv", ".flv",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".3gp", ".ogv",
}
AUDIO_EXT = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus",
    ".wma", ".aiff", ".aif", ".alac", ".amr",
}
PDF_EXT = {".pdf"}
DOC_EXT = {
    ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".markdown", ".html", ".htm",
    ".ppt", ".pptx", ".odp", ".xls", ".xlsx", ".ods", ".csv", ".epub", ".json",
}
ARCHIVE_EXT = {".zip", ".7z", ".rar", ".tar", ".tgz", ".gz", ".bz2", ".xz"}

IMAGE = "image"
VIDEO = "video"
AUDIO = "audio"
PDF = "pdf"
DOCUMENT = "document"
ARCHIVE = "archive"
OTHER = "other"
MIXED = "mixed"

_LOOKUP = [
    (IMAGE_EXT, IMAGE),
    (VIDEO_EXT, VIDEO),
    (AUDIO_EXT, AUDIO),
    (PDF_EXT, PDF),
    (DOC_EXT, DOCUMENT),
    (ARCHIVE_EXT, ARCHIVE),
]

LABELS = {
    IMAGE: "Image",
    VIDEO: "Video",
    AUDIO: "Audio",
    PDF: "PDF",
    DOCUMENT: "Document",
    ARCHIVE: "Archive",
    OTHER: "File",
    MIXED: "Files",
}


def category_of(path) -> str:
    ext = Path(path).suffix.lower()
    for extensions, name in _LOOKUP:
        if ext in extensions:
            return name
    return OTHER


def category_for(paths) -> str:
    """One category for a whole drop; MIXED when they disagree."""
    cats = {category_of(p) for p in paths}
    if not cats:
        return OTHER
    if len(cats) == 1:
        return cats.pop()
    # Images + PDFs together still merge sensibly into a PDF.
    if cats <= {IMAGE, PDF}:
        return MIXED
    return MIXED


def describe(paths) -> str:
    """Short human label for the menu header."""
    paths = list(paths)
    if len(paths) == 1:
        return Path(paths[0]).name
    cat = category_for(paths)
    return f"{len(paths)} {LABELS.get(cat, 'files').lower()}s" if cat != MIXED else f"{len(paths)} files"
