# Satsuma 🍊

**Hold Shift while dragging a file. A ring of actions springs open under your cursor. Drop the file on what you want.**

A Windows take on the drag-to-convert idea: convert, compress, trim, merge, and edit files
without opening a single app. Everything runs **locally on your PC** — files are never uploaded.

![demo](docs/demo.gif)

---

## Start it

1. Install **Python 3.10 or newer** from [python.org](https://www.python.org/downloads/)
   (tick **“Add python.exe to PATH”**).
2. Double-click **`run.bat`**.
   The first run sets things up (a minute or two); after that it starts instantly.
3. Satsuma lives in the system tray (the 🍊 by the clock).

Prefer a standalone `.exe`? See [Build an .exe](#build-an-exe).

## Use it

| Do this | What happens |
|---|---|
| Drag any file, and hold **Shift** while dragging | The ring springs open under your cursor |
| Move over a wedge | It lights up; the centre names the action |
| Rest on the **centre** for a moment | The ring swaps between **Convert** and **Tools** (dots show which) |
| Drop the file on a wedge | It runs in the background; a card in the corner shows progress |
| Click **Open** / **Show in folder** on the card | Jump to the result |
| Let go anywhere else, or press **Esc** | Nothing happens |
| Right-click files → **Send to → Satsuma** | Same menu, click instead of drop *(enable in Settings)* |
| Click the tray icon | A drop ring you can drag files onto without Shift (drag its centre to move it) |

Your original file is **never changed, moved or deleted**. Results are saved next to it
(e.g. `photo.png` → `photo.webp`), and if that name is taken you get `photo (1).webp`.

> Shift normally means *move* when you drag in Explorer. Satsuma always takes the drop as a
> **copy**, so Explorer never removes the original.

## What it can do

| Files | Convert to | Tools |
|---|---|---|
| **Images** — PNG, JPG, WEBP, GIF, BMP, TIFF, ICO, HEIC, AVIF… | PNG · JPG · WEBP · GIF · TIFF · ICO · PDF | Compress · Resize · Rotate · Flip |
| **Videos** — MP4, MOV, MKV, WEBM, AVI… | MP4 · MOV · MKV · WEBM · GIF · MP3 | Compress · Trim · Mute · Frame grab · Join |
| **Audio** — MP3, WAV, M4A, FLAC, OGG, OPUS… | MP3 · M4A · WAV · FLAC · OGG · OPUS | Trim · Join |
| **PDF** | PNG · JPG (per page) · TXT | Merge · Compress · Split · Extract pages · Rotate |
| **Text** — TXT, Markdown, HTML | PDF | |
| **Office** — DOCX, PPTX, XLSX, ODT… | PDF, and DOCX/ODT/XLSX/CSV… with LibreOffice | |
| **Anything** | | ZIP · Extract (.zip) |

Drop **several files** at once to batch them, or to **merge** (PDFs, images → one PDF) and
**join** (videos, audio) them. Merging and joining go in file-name order — `part1`, `part2`,
`part10` — so name them to set the order.

### What it needs

- **Images, PDFs, text, ZIP** — nothing extra.
- **Video & audio** — FFmpeg. Satsuma downloads it automatically the first time you use a
  video/audio action (a one-time 100–200 MB download, saved in `%LOCALAPPDATA%\Satsuma\bin`;
  if FFmpeg is already on your PATH it uses that instead). You can also press
  *Download FFmpeg* in Settings. That download is the only time Satsuma uses the internet.
- **Word / PowerPoint / Excel** — [LibreOffice](https://www.libreoffice.org/) (free) for all
  conversions, or Microsoft Office for conversion to PDF.

## Customise

Right-click the tray icon → **Settings…**

![settings](docs/settings.png)

**Look & feel** — with a live preview you can hover and click:

- **Theme** — follow Windows, or force dark / light.
- **Accent colour** — eight presets or any colour you pick; text on it switches between white
  and dark automatically so it stays readable.
- **Glass** — how see-through the ring is.
- **Size** — 70 % to 150 %.
- **Wedges per ring** — 3 to 10; extra actions spill onto another ring.
- **First ring** — open on Convert or on Tools.
- **Animation** — Fast, Normal, Relaxed or Off, with or without the springy bounce.
- **Hold centre to swap** — how long to rest on the centre before the ring swaps.
- **Centre shows** — file size, file name or file type, and optionally a description of the
  action under the cursor.
- **Show icons** on tool wedges.

**Actions** — for each kind of file (images, videos, audio, PDFs, documents, archives…), tick
what appears in the ring and drag to change the order.

**Trigger & saving** — modifier key (Shift / Ctrl / Alt), *only for real file drags*, where
results go (next to the original, a subfolder, or one folder), overwrite or add `(1)`, show in
Explorer when done, start with Windows, *Send to* menu.

**Converters** — JPG/WEBP quality, compression strength, FFmpeg and LibreOffice status.

## Build an .exe

**On your PC:** double-click **`build.bat`** → `dist\Satsuma\Satsuma.exe`
(keep the whole `Satsuma` folder together).

**On GitHub (no setup):** push this folder to a GitHub repo. The included workflow runs the tests
on Windows, builds the exe, starts it to check it works, and attaches **Satsuma-windows.zip** to
the run (Actions tab → latest run → Artifacts).

## Troubleshooting

- **Menu doesn't appear when dragging from an app running as Administrator.** Windows blocks
  drops from elevated apps into normal ones. Drag from regular Explorer windows, or run Satsuma
  as Administrator too.
- **Menu doesn't appear for files inside a .zip or from Outlook.** Those aren't real files on disk
  yet. Extract/save them first.
- **Shift-drag conflicts with another app.** Change the modifier to Ctrl or Alt in Settings, or
  untick *Enabled* in the tray menu.
- **Windows SmartScreen warns about Satsuma.exe.** It's unsigned because it's your own build.
  Click *More info → Run anyway*.
- **Something failed?** The card says why. Full details: tray → **Open log**
  (`%LOCALAPPDATA%\Satsuma\satsuma.log`).

## Uninstall

Untick *Start with Windows* and *Send to* in Settings, quit from the tray, then delete this folder
and `%LOCALAPPDATA%\Satsuma`.

## Project layout

```
main.py                 entry point
satsuma/app.py          tray, single instance, wiring
satsuma/detector.py     notices Shift-drags (polls GetAsyncKeyState, no hooks)
satsuma/ui/radial.py    the ring: geometry, hit-testing, drawing
satsuma/ui/anim.py      spring physics + frame clock at the display's refresh rate
satsuma/ui/menu.py      the overlay window (drag/drop, click and pinned modes)
satsuma/actions.py      which actions show for which files
satsuma/engine/         images · pdfs · media (FFmpeg) · documents · archives
tests/                  pytest suite (runs on Windows in CI)
```
