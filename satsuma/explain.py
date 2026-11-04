"""Plain-language descriptions of what each action does, for the bubble beside a hovered wedge."""
from __future__ import annotations

from pathlib import Path

from .actions import Action
from .config import settings

DESCRIPTIONS = {
    # ---- images: convert
    "img-png": "A PNG copy. Lossless: sharp edges and transparency stay perfect, but files are bigger.",
    "img-jpg": "A JPG copy, the photo format everything opens. Smaller; transparent areas become white.",
    "img-webp": "A WEBP copy, about a third the size of a JPG at the same quality. Transparency is kept.",
    "img-gif": "A GIF copy with up to 256 colours. For simple graphics and older apps.",
    "img-tiff": "A TIFF copy for printing and editing. Lossless, but large.",
    "img-ico": "A Windows icon, with every size from 16 to 256 pixels inside.",
    "img-avif": "An AVIF copy, the smallest modern format. New browsers and apps open it.",
    "img-heic": "A HEIC copy, the format iPhones save photos in. Small and high quality.",
    "img-bmp": "An uncompressed bitmap. Very large; only for old software that needs it.",
    "img-pdf": "All the pictures in one PDF, one per page, in file-name order.",
    # ---- images: tools
    "img-compress": "Re-saves it smaller. PNGs become JPG, or WEBP if they have transparency.",
    "img-resize": "Scale it, or set a width or height. You'll choose the size first.",
    "img-rotate": "Turns it a quarter turn clockwise.",
    "img-flip": "Mirrors it left to right.",
    "img-clean": "Removes hidden details before you share: location, camera, date and comments.",
    "img-bw": "A black and white copy. Transparency is kept.",
    "img-square": "Fits the whole picture on a square canvas. Nothing is cropped.",
    # ---- video
    "vid-mp4": "An MP4 that plays everywhere: phones, TVs, browsers, WhatsApp.",
    "vid-mov": "A QuickTime MOV, for Apple apps and video editors.",
    "vid-mkv": "An MKV, which keeps every track. Good for archiving.",
    "vid-webm": "A WEBM for the web: small files that play in any browser.",
    "vid-avi": "An AVI for older players and TVs.",
    "vid-gif": "The first 15 seconds as a looping GIF.",
    "vid-mp3": "Just the sound, as an MP3.",
    "vid-compress": "A smaller MP4, at most 1080p.",
    "vid-trim": "Keeps only the part you choose. You'll set the start and end first.",
    "vid-mute": "Removes the sound. The picture isn't re-encoded, so it's quick.",
    "vid-frame": "Saves one still frame from the middle as a PNG.",
    "vid-speed": "Plays faster or slower; you'll choose how much. Voices still sound natural.",
    "vid-rotate": "Turns the video a quarter turn clockwise.",
    "vid-boomerang": "The first 3 seconds, forwards then backwards, as a looping GIF.",
    "vid-join": "Plays the clips one after another as one video, in file-name order.",
    # ---- audio
    "aud-mp3": "An MP3 that plays everywhere.",
    "aud-m4a": "An M4A (AAC): smaller than MP3 at the same quality. Apple's default.",
    "aud-wav": "An uncompressed WAV, for editing.",
    "aud-flac": "A FLAC: lossless, and smaller than WAV.",
    "aud-ogg": "An OGG Vorbis file: an open format with good quality.",
    "aud-opus": "An OPUS file: tiny, and great for voice.",
    "aud-aiff": "An uncompressed AIFF, for Mac apps.",
    "aud-trim": "Keeps only the part you choose. You'll set the start and end first.",
    "aud-join": "Plays the files one after another as one track, in file-name order.",
    # ---- pdf
    "pdf-merge": "All the PDFs joined into one, in file-name order.",
    "pdf-png": "Every page as a PNG image, in a new folder.",
    "pdf-jpg": "Every page as a JPG image, in a new folder.",
    "pdf-txt": "All the text, as a plain .txt file.",
    "pdf-compress": "Shrinks the pictures inside. Text stays sharp.",
    "pdf-split": "One PDF per page, in a new folder.",
    "pdf-pages": "Copies the pages you choose into a new PDF.",
    "pdf-rotate": "Turns every page a quarter turn clockwise.",
    "pdf-numbers": "Adds “3 / 12” at the bottom of every page.",
    "pdf-lock": "A copy that asks for a password to open (AES-256). You'll type it twice.",
    "pdf-unlock": "A copy without the password. You'll be asked for the current one.",
    "mix-pdf": "The pictures and PDFs together in one PDF, in file-name order.",
    # ---- anything
    "any-zip": "Everything in one compressed .zip.",
    "zip-extract": "Unpacks it into a new folder beside the archive.",
}

DOCUMENTS = {
    ".pdf": "A PDF that looks the same everywhere.",
    ".docx": "A Word document (.docx).",
    ".doc": "An older Word document (.doc), for Word 97–2003.",
    ".odt": "An OpenDocument text file, for LibreOffice.",
    ".rtf": "A rich-text file that almost any editor opens.",
    ".txt": "Just the text, without formatting.",
    ".html": "A web page (.html) that any browser opens.",
    ".md": "Markdown: plain text with simple formatting marks.",
    ".pptx": "A PowerPoint presentation (.pptx).",
    ".ppt": "An older PowerPoint presentation (.ppt).",
    ".odp": "An OpenDocument presentation, for LibreOffice.",
    ".xlsx": "An Excel workbook (.xlsx).",
    ".xls": "An older Excel workbook (.xls).",
    ".ods": "An OpenDocument spreadsheet, for LibreOffice.",
    ".csv": "A CSV: the values, separated by commas. Only the first sheet.",
    ".json": "JSON data: one entry per row, named by the column headers.",
}


def description(action: Action) -> str:
    if action.id in DESCRIPTIONS:
        return DESCRIPTIONS[action.id]
    if action.id.startswith("doc-"):
        return DOCUMENTS.get(f".{action.id[4:]}", f"A {action.label} copy.")
    return action.caption[:1].upper() + action.caption[1:] + "." if action.caption else ""


def destination() -> str:
    """Where new files go, from the Saving settings."""
    mode = settings.get("output_mode")
    if mode == "subfolder":
        return f"New file in the “{settings.get('output_subfolder') or 'Converted'}” folder beside the original."
    if mode == "custom" and str(settings.get("output_custom") or "").strip():
        return f"New file in “{Path(str(settings.get('output_custom'))).name}”."
    return "New file next to the original."


def explain(action: Action) -> tuple[str, str, str]:
    """(title, what it does, where the result goes) for the bubble."""
    title = action.label if not action.caption else f"{action.label} · {action.caption}"
    return title, description(action), f"{destination()} Your original isn't changed."
