"""Image conversion, compression, resizing and rotation (Pillow)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from ..config import settings
from .paths import target_path

try:  # optional: adds HEIC/HEIF reading and writing
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_OK = True
except Exception:  # pragma: no cover - optional dependency
    HEIF_OK = False

# Pillow's own name for each container we offer.
PIL_FORMAT = {
    ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP",
    ".bmp": "BMP", ".tif": "TIFF", ".tiff": "TIFF", ".gif": "GIF",
    ".ico": "ICO", ".pdf": "PDF", ".avif": "AVIF", ".heic": "HEIF", ".heif": "HEIF",
}
# Formats with no alpha channel: flatten onto white first.
NO_ALPHA = {"JPEG", "PDF", "BMP"}
LOSSY = {"JPEG", "WEBP", "AVIF", "HEIF"}
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

MAX_PIXELS = 400_000_000  # guard against decompression bombs
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def _load(path) -> Image.Image:
    image = Image.open(path)
    image.load()
    # Honour the EXIF orientation flag so output matches what the user saw.
    try:
        image = ImageOps.exif_transpose(image) or image
    except Exception:
        pass
    return image


def _prepare(image: Image.Image, pil_format: str) -> Image.Image:
    if pil_format in NO_ALPHA:
        if image.mode in ("RGBA", "LA", "PA"):
            background = Image.new("RGB", image.size, (255, 255, 255))
            alpha = image.convert("RGBA").getchannel("A")
            background.paste(image.convert("RGB"), mask=alpha)
            return background
        if image.mode == "P":
            converted = image.convert("RGBA")
            return _prepare(converted, pil_format)
        if image.mode != "RGB":
            return image.convert("RGB")
        return image
    if pil_format == "PNG" and image.mode not in ("RGB", "RGBA", "L", "LA", "P", "I", "1"):
        return image.convert("RGBA")
    if pil_format in ("WEBP", "AVIF", "HEIF") and image.mode not in ("RGB", "RGBA"):
        return image.convert("RGBA" if "A" in image.getbands() else "RGB")
    if pil_format == "ICO":
        image = image.convert("RGBA") if image.mode != "RGBA" else image
        side = max(image.size)
        if image.size[0] != image.size[1]:
            square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            square.paste(image, ((side - image.size[0]) // 2, (side - image.size[1]) // 2))
            image = square
        return image
    if pil_format == "GIF" and image.mode not in ("P", "L"):
        return image.convert("P", palette=Image.ADAPTIVE)
    return image


def _save(image: Image.Image, destination: Path, pil_format: str, quality: int | None = None) -> None:
    options: dict = {}
    if pil_format == "JPEG":
        options.update(quality=quality or settings.get("jpeg_quality"), optimize=True,
                       progressive=True, subsampling="4:2:0")
    elif pil_format == "WEBP":
        options.update(quality=quality or settings.get("jpeg_quality"), method=5)
    elif pil_format in ("AVIF", "HEIF"):
        options.update(quality=quality or settings.get("jpeg_quality"))
    elif pil_format == "PNG":
        options.update(optimize=True, compress_level=9)
    elif pil_format == "TIFF":
        options.update(compression="tiff_lzw")
    elif pil_format == "PDF":
        options.update(resolution=96.0)
    elif pil_format == "ICO":
        sizes = [s for s in ICO_SIZES if s[0] <= max(image.size)] or [(32, 32)]
        options.update(sizes=sizes)
    image.save(destination, pil_format, **options)


def convert(source, extension: str, quality: int | None = None) -> Path:
    """Convert a single image to `extension` (with dot)."""
    source = Path(source)
    extension = extension.lower()
    pil_format = PIL_FORMAT.get(extension)
    if not pil_format:
        raise ValueError(f"Unsupported image format: {extension}")
    if pil_format == "HEIF" and not HEIF_OK:
        raise ValueError("HEIC needs the pillow-heif package (pip install pillow-heif).")
    with _load(source) as image:
        prepared = _prepare(image, pil_format)
        destination = target_path(source, extension)
        _save(prepared, destination, pil_format, quality)
    return destination


def compress(source, quality: int | None = None) -> Path:
    """Re-encode smaller, keeping a sensible container."""
    source = Path(source)
    quality = quality or settings.get("compress_quality")
    extension = source.suffix.lower()
    pil_format = PIL_FORMAT.get(extension, "JPEG")
    if pil_format not in LOSSY:
        # PNG/BMP/TIFF do not compress much further: JPEG unless we need alpha.
        with _load(source) as probe_image:
            has_alpha = probe_image.mode in ("RGBA", "LA", "PA") or (
                probe_image.mode == "P" and "transparency" in probe_image.info
            )
        extension, pil_format = (".webp", "WEBP") if has_alpha else (".jpg", "JPEG")
    with _load(source) as image:
        prepared = _prepare(image, pil_format)
        destination = target_path(source, extension, stem=f"{source.stem}-compressed")
        _save(prepared, destination, pil_format, quality)
    return destination


def resize(source, *, scale: float | None = None, width: int | None = None,
           height: int | None = None) -> Path:
    """Resize by a factor or to a longest/target edge, preserving aspect ratio."""
    source = Path(source)
    with _load(source) as image:
        original_width, original_height = image.size
        if scale:
            new_width = max(1, round(original_width * scale))
            new_height = max(1, round(original_height * scale))
        elif width and height:
            new_width, new_height = max(1, width), max(1, height)
        elif width:
            new_width = max(1, width)
            new_height = max(1, round(original_height * (new_width / original_width)))
        elif height:
            new_height = max(1, height)
            new_width = max(1, round(original_width * (new_height / original_height)))
        else:
            raise ValueError("resize needs a scale, width or height")

        resized = image.resize((new_width, new_height), Image.LANCZOS)
        extension = source.suffix.lower()
        pil_format = PIL_FORMAT.get(extension, "PNG")
        if extension not in PIL_FORMAT:
            extension, pil_format = ".png", "PNG"
        prepared = _prepare(resized, pil_format)
        destination = target_path(source, extension, stem=f"{source.stem}-{new_width}x{new_height}")
        _save(prepared, destination, pil_format)
    return destination


def rotate(source, degrees: int) -> Path:
    """Rotate clockwise by 90/180/270 degrees."""
    source = Path(source)
    mapping = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}
    if degrees not in mapping:
        raise ValueError("rotate supports 90, 180 or 270 degrees")
    with _load(source) as image:
        rotated = image.transpose(mapping[degrees])
        extension = source.suffix.lower()
        pil_format = PIL_FORMAT.get(extension, "PNG")
        if extension not in PIL_FORMAT:
            extension, pil_format = ".png", "PNG"
        prepared = _prepare(rotated, pil_format)
        destination = target_path(source, extension, stem=f"{source.stem}-rotated")
        _save(prepared, destination, pil_format)
    return destination


def flip(source, horizontal: bool = True) -> Path:
    source = Path(source)
    with _load(source) as image:
        flipped = image.transpose(
            Image.FLIP_LEFT_RIGHT if horizontal else Image.FLIP_TOP_BOTTOM
        )
        extension = source.suffix.lower()
        pil_format = PIL_FORMAT.get(extension, "PNG")
        if extension not in PIL_FORMAT:
            extension, pil_format = ".png", "PNG"
        prepared = _prepare(flipped, pil_format)
        destination = target_path(source, extension, stem=f"{source.stem}-flipped")
        _save(prepared, destination, pil_format)
    return destination


def _same_format(source: Path) -> tuple[str, str]:
    """Keep the source's format when we can write it, otherwise PNG."""
    extension = source.suffix.lower()
    if extension in PIL_FORMAT and extension != ".pdf":
        return extension, PIL_FORMAT[extension]
    return ".png", "PNG"


def strip_metadata(source) -> Path:
    """A copy without hidden details: location, camera, date, comments, thumbnails."""
    source = Path(source)
    extension, pil_format = _same_format(source)
    destination = target_path(source, extension, stem=f"{source.stem}-clean")
    with Image.open(source) as original:
        upright = (original.getexif().get(0x0112, 1) or 1) == 1   # no EXIF rotation to bake in
        if pil_format == "JPEG" and upright and original.format == "JPEG":
            # Same compressed data, metadata left behind: no quality loss.
            original.save(destination, "JPEG", quality="keep", optimize=True)
            return destination
    with _load(source) as image:          # applies the EXIF rotation, so dropping EXIF is safe
        clean = Image.new(image.mode, image.size)
        clean.putdata(image.getdata())
        if image.mode == "P":
            clean.putpalette(image.getpalette())
            if "transparency" in image.info:
                clean.info["transparency"] = image.info["transparency"]
        _save(_prepare(clean, pil_format), destination, pil_format, quality=95 if pil_format in LOSSY else None)
    return destination


def grayscale(source) -> Path:
    source = Path(source)
    extension, pil_format = _same_format(source)
    with _load(source) as image:
        has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
        grey = image.convert("LA" if has_alpha else "L")
        if pil_format in ("WEBP", "AVIF", "HEIF", "ICO"):
            grey = grey.convert("RGBA" if has_alpha else "RGB")
        destination = target_path(source, extension, stem=f"{source.stem}-bw")
        _save(_prepare(grey, pil_format), destination, pil_format)
    return destination


def pad_square(source) -> Path:
    """Fit the whole picture on a square canvas (for profile pictures, posts): nothing is cropped.
    The border is transparent where the format allows it, white otherwise."""
    source = Path(source)
    extension, pil_format = _same_format(source)
    with _load(source) as image:
        width, height = image.size
        side = max(width, height)
        transparent = pil_format not in NO_ALPHA
        canvas = Image.new("RGBA", (side, side), (255, 255, 255, 0 if transparent else 255))
        canvas.paste(image.convert("RGBA"), ((side - width) // 2, (side - height) // 2))
        destination = target_path(source, extension, stem=f"{source.stem}-square")
        _save(_prepare(canvas, pil_format), destination, pil_format)
    return destination


def to_pdf(sources, destination_hint=None) -> Path:
    """Combine one or more images into a single PDF, in the order given."""
    sources = [Path(p) for p in sources]
    if not sources:
        raise ValueError("No images given")
    pages = []
    try:
        for path in sources:
            image = _load(path)
            pages.append(_prepare(image, "PDF"))
        first, rest = pages[0], pages[1:]
        base = Path(destination_hint) if destination_hint else sources[0]
        stem = base.stem if len(sources) == 1 else f"{base.stem}-and-{len(sources) - 1}-more"
        destination = target_path(base, ".pdf", stem=stem)
        first.save(destination, "PDF", resolution=96.0, save_all=bool(rest), append_images=rest)
    finally:
        for page in pages:
            try:
                page.close()
            except Exception:
                pass
    return destination


def info(source) -> dict:
    with _load(source) as image:
        return {"width": image.size[0], "height": image.size[1], "mode": image.mode,
                "format": image.format}
