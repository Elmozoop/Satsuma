"""Video and audio operations via ffmpeg."""
from __future__ import annotations

from pathlib import Path

from . import ffmpeg_tool as ff
from .paths import target_path

# Per-container encoder choices that are known-good in stock ffmpeg builds.
VIDEO_PROFILES = {
    ".mp4":  ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"],
    ".mov":  ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "160k"],
    ".mkv":  ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "160k"],
    ".webm": ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1",
              "-c:a", "libopus", "-b:a", "128k"],
    ".avi":  ["-c:v", "mpeg4", "-q:v", "4", "-c:a", "libmp3lame", "-q:a", "3"],
}
AUDIO_PROFILES = {
    ".mp3":  ["-c:a", "libmp3lame", "-q:a", "2"],
    ".m4a":  ["-c:a", "aac", "-b:a", "192k"],
    ".aac":  ["-c:a", "aac", "-b:a", "192k"],
    ".wav":  ["-c:a", "pcm_s16le"],
    ".aiff": ["-c:a", "pcm_s16be"],
    ".flac": ["-c:a", "flac"],
    ".ogg":  ["-c:a", "libvorbis", "-q:a", "5"],
    ".opus": ["-c:a", "libopus", "-b:a", "128k"],
}


EVEN_PAD = "pad=ceil(iw/2)*2:ceil(ih/2)*2"
X264_EXT = (".mp4", ".mov", ".mkv")


def _even_scale(max_height: int) -> str:
    # Never upscale, keep aspect ratio, keep dimensions even (required by yuv420p).
    return f"scale=-2:'min({max_height},ih)':flags=lanczos"


def convert_video(source, extension: str) -> Path:
    source = Path(source)
    extension = extension.lower()
    if extension not in VIDEO_PROFILES:
        raise ValueError(f"Unsupported video format: {extension}")
    destination = target_path(source, extension)
    args = ["-i", str(source), "-map", "0:v:0", "-map", "0:a?", *VIDEO_PROFILES[extension]]
    if extension in X264_EXT:
        # yuv420p needs even dimensions; pad by one pixel if the source is odd.
        args += ["-vf", EVEN_PAD]
    ff.run([*args, str(destination)])
    return destination


def compress_video(source, max_height: int = 1080, crf: int = 28) -> Path:
    source = Path(source)
    destination = target_path(source, ".mp4", stem=f"{source.stem}-compressed")
    ff.run([
        "-i", str(source), "-map", "0:v:0", "-map", "0:a?",
        "-vf", _even_scale(max_height),
        "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        str(destination),
    ])
    return destination


def trim(source, start: float, end: float) -> Path:
    """Cut [start, end] seconds. Re-encodes for frame-accurate cuts."""
    source = Path(source)
    if end <= start:
        raise ValueError("The end time must be after the start time.")
    extension = source.suffix.lower()
    is_audio = extension in AUDIO_PROFILES
    profile = (AUDIO_PROFILES if is_audio else VIDEO_PROFILES).get(extension)
    if profile is None:
        extension = ".m4a" if is_audio else ".mp4"
        profile = (AUDIO_PROFILES if is_audio else VIDEO_PROFILES)[extension]
    destination = target_path(source, extension, stem=f"{source.stem}-trim")
    maps = ["-map", "0:a:0"] if is_audio else ["-map", "0:v:0", "-map", "0:a?"]
    filters = ["-vf", EVEN_PAD] if (not is_audio and extension in X264_EXT) else []
    ff.run([
        "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{end - start:.3f}",
        *maps, *filters, *profile, str(destination),
    ])
    return destination


def extract_audio(source, extension: str = ".mp3") -> Path:
    source = Path(source)
    extension = extension.lower()
    if extension not in AUDIO_PROFILES:
        raise ValueError(f"Unsupported audio format: {extension}")
    if not ff.has_audio(source):
        raise ff.ConversionError("This video has no audio track.")
    destination = target_path(source, extension)
    ff.run(["-i", str(source), "-vn", "-map", "0:a:0", *AUDIO_PROFILES[extension], str(destination)])
    return destination


def convert_audio(source, extension: str) -> Path:
    source = Path(source)
    extension = extension.lower()
    if extension not in AUDIO_PROFILES:
        raise ValueError(f"Unsupported audio format: {extension}")
    destination = target_path(source, extension)
    ff.run(["-i", str(source), "-vn", "-map", "0:a:0", *AUDIO_PROFILES[extension], str(destination)])
    return destination


def to_gif(source, width: int = 480, fps: int = 12, max_seconds: float = 15.0) -> Path:
    """Two-pass palette GIF: far better colours than a naive conversion."""
    source = Path(source)
    destination = target_path(source, ".gif")
    filters = (
        f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];"
        f"[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5"
    )
    ff.run(["-t", f"{max_seconds:.2f}", "-i", str(source), "-filter_complex", filters,
            "-loop", "0", str(destination)])
    return destination


def _video_target(source: Path, label: str) -> tuple[Path, list[str]]:
    """Same container as the source when we know how to write it, otherwise MP4."""
    extension = source.suffix.lower() if source.suffix.lower() in VIDEO_PROFILES else ".mp4"
    return target_path(source, extension, stem=f"{source.stem}-{label}"), VIDEO_PROFILES[extension]


def atempo_chain(factor: float) -> str:
    """atempo keeps pitch natural; each stage handles 0.5x–2x, so chain them for bigger changes."""
    stages = []
    while factor < 0.5:
        stages.append(0.5)
        factor /= 0.5
    while factor > 2.0:
        stages.append(2.0)
        factor /= 2.0
    stages.append(factor)
    return ",".join(f"atempo={s:g}" for s in stages)


def change_speed(source, factor: float) -> Path:
    """Play faster (factor > 1) or slower (< 1); audio follows without chipmunk pitch."""
    source = Path(source)
    if not 0.1 <= factor <= 10:
        raise ValueError("Speed must be between 0.1× and 10×.")
    label = f"{factor:g}x".replace(".", "_")
    destination, profile = _video_target(source, label)
    video = f"[0:v:0]setpts=PTS/{factor:g},{EVEN_PAD}[v]"
    graph, maps = video, ["-map", "[v]"]
    if ff.has_audio(source):
        graph += f";[0:a:0]{atempo_chain(factor)}[a]"
        maps += ["-map", "[a]"]
    ff.run(["-i", str(source), "-filter_complex", graph, *maps, *profile, str(destination)])
    return destination


def rotate_video(source, clockwise: bool = True) -> Path:
    source = Path(source)
    destination, profile = _video_target(source, "rotated")
    turn = "transpose=1" if clockwise else "transpose=2"
    ff.run(["-i", str(source), "-map", "0:v:0", "-map", "0:a?", "-vf", f"{turn},{EVEN_PAD}",
            "-metadata:s:v:0", "rotate=0", *profile, str(destination)])
    return destination


def boomerang(source, seconds: float = 3.0, width: int = 480, fps: int = 15) -> Path:
    """The first few seconds played forwards then backwards, as an endlessly looping GIF."""
    source = Path(source)
    destination = target_path(source, ".gif", stem=f"{source.stem}-boomerang")
    filters = (
        f"fps={fps},scale={width}:-1:flags=lanczos,split[f][r];[r]reverse[rv];"
        f"[f][rv]concat=n=2:v=1:a=0,split[a][b];"
        f"[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5"
    )
    ff.run(["-t", f"{seconds:.2f}", "-i", str(source), "-filter_complex", filters,
            "-loop", "0", str(destination)])
    return destination


def mute(source) -> Path:
    source = Path(source)
    extension = source.suffix.lower() if source.suffix.lower() in VIDEO_PROFILES else ".mp4"
    destination = target_path(source, extension, stem=f"{source.stem}-muted")
    ff.run(["-i", str(source), "-map", "0:v:0", "-c:v", "copy", "-an", str(destination)])
    return destination


def snapshot(source, at: float | None = None) -> Path:
    """Grab a single frame (middle of the clip by default) as PNG."""
    source = Path(source)
    if at is None:
        duration = ff.duration_of(source)
        at = duration / 2 if duration else 0.0
    destination = target_path(source, ".png", stem=f"{source.stem}-frame")
    ff.run(["-ss", f"{at:.3f}", "-i", str(source), "-frames:v", "1", str(destination)])
    return destination


def concat(sources, extension: str | None = None) -> Path:
    """Join clips end to end, re-encoding so mismatched inputs still work."""
    sources = [Path(p) for p in sources]
    if len(sources) < 2:
        raise ValueError("Joining needs at least two files.")
    is_audio = all(p.suffix.lower() in AUDIO_PROFILES for p in sources)
    extension = extension or (".m4a" if is_audio else ".mp4")
    destination = target_path(sources[0], extension, stem=f"{sources[0].stem}-joined")

    inputs: list[str] = []
    for path in sources:
        inputs += ["-i", str(path)]

    if is_audio:
        chain = "".join(f"[{i}:a:0]" for i in range(len(sources)))
        graph = f"{chain}concat=n={len(sources)}:v=0:a=1[a]"
        ff.run([*inputs, "-filter_complex", graph, "-map", "[a]",
                *AUDIO_PROFILES[extension], str(destination)])
        return destination

    # Normalise every clip to the first clip's size/fps so concat accepts them.
    first = ff.probe(sources[0])
    video = next((s for s in first.get("streams", []) if s.get("codec_type") == "video"), {})
    width = int(video.get("width") or 1280) // 2 * 2
    height = int(video.get("height") or 720) // 2 * 2
    all_audio = all(ff.has_audio(p) for p in sources)

    parts = []
    for i in range(len(sources)):
        parts.append(
            f"[{i}:v:0]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[v{i}]"
        )
        if all_audio:
            parts.append(f"[{i}:a:0]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
    chain = "".join(f"[v{i}]" + (f"[a{i}]" if all_audio else "") for i in range(len(sources)))
    parts.append(f"{chain}concat=n={len(sources)}:v=1:a={1 if all_audio else 0}[v]" +
                 ("[a]" if all_audio else ""))
    maps = ["-map", "[v]"] + (["-map", "[a]"] if all_audio else [])
    ff.run([*inputs, "-filter_complex", ";".join(parts), *maps,
            *VIDEO_PROFILES.get(extension, VIDEO_PROFILES[".mp4"]), str(destination)])
    return destination
