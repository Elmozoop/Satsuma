# Satsuma 🍊

**Hold Shift while dragging a file. A ring of actions springs open under your cursor. Drop the file on what you want.**

A Windows take on the drag-to-convert idea: convert, compress, trim, merge, lock and edit files
without opening a single app. Everything runs **locally on your PC** — files are never uploaded.

![Satsuma in action: Shift-drag a photo, the ring opens, drop it on WEBP](docs/demo.webp)

---

## Download

1. **[Download Satsuma.exe](https://github.com/Elmozoop/Satsuma/releases/latest/download/Satsuma.exe)**
   (always the newest version). You only need this one file; the *Source code* files on the
   [Releases](https://github.com/Elmozoop/Satsuma/releases/latest) page are for developers.
2. Double-click it. That's all: no installer, no Python. A one-minute **tour** opens the first time,
   with a practice ring to try it on. Afterwards Satsuma waits in the system tray (the 🍊 by the clock);
   hold **Shift** while dragging a file to open the ring.
3. After the tour, Satsuma asks whether it should **start with Windows**. Changed your mind? Right-click
   the 🍊 → **Settings… → Trigger → Start when I sign in**.

Put `Satsuma.exe` anywhere you like (Documents, a Tools folder…). Your settings live in
`%LOCALAPPDATA%\Satsuma`, so moving or updating the exe keeps them.

**It keeps itself up to date.** From 1.14 on, Satsuma.exe installs new versions by itself, quietly,
when you're not using it, and tells you when it has. (Have 1.13 or older? Download it once more.)

> **Windows SmartScreen** may say it "protected your PC" the first time, because Satsuma.exe isn't
> signed with a paid certificate. Click **More info → Run anyway**.

## Run from source

1. Install **Python 3.10 or newer** from [python.org](https://www.python.org/downloads/)
   (tick **“Add python.exe to PATH”**).
2. Double-click **`run.bat`**.
   The first run sets things up (a minute or two); after that it starts instantly. When an update
   needs new packages, `run.bat` installs them by itself.
3. Satsuma lives in the system tray (the 🍊 by the clock).

## Use it

![the ring in dark and light](docs/menu.png)

| Do this | What happens |
|---|---|
| Drag any file, and hold **Shift** while dragging | The ring springs open under your cursor, with a preview of the file in the centre |
| Move over a wedge and rest a moment | It lights up, and an info panel beside it says what it will do and where the new file goes |
| Rest on the **centre** for a moment | The ring swaps between **Convert** and **Tools** (dots show which) — also right after the ring opens under your pointer |
| Drop the file on a wedge | A tick confirms it; the job runs in the background with a card in the corner |
| Let go anywhere else, or press **Esc** | Nothing happens |
| Right-click files → **Send to → Satsuma** | Same ring, click instead of drop *(enable in Settings)* |
| Click the tray icon | A drop window you can drag files onto without Shift (drag its centre to move it) |

**The cards in the corner**

![result cards](docs/cards.png)

- While a job runs: progress, and **Cancel** (a stopped video leaves no half-written file).
- When it's done: a preview of the result, how much smaller (or bigger) it got, **Open**,
  **Show in folder** and **Undo** (sends the new file to the Recycle Bin).
- **Drag a finished card** into WhatsApp, Discord, an email or a folder to share the result.
- The 🍊 in the tray shows a progress ring while anything runs, and a tick when it's all done.

**From the tray menu**

- **Convert clipboard** — copied files, or a copied picture (saved to `Pictures\Satsuma clipboard`).
- **Recent** — your last 10 results; click one to see it in its folder.
- **Undo** — the last conversion, even after its card has gone.
- **Info panel beside wedges** — tick or untick to turn the info panel on or off.

Your original file is **never changed, moved or deleted** (the one exception is **Rename**, which
renames the files you chose; its Undo puts the old names back). Results are saved next to it
(e.g. `photo.png` → `photo.webp`), and if that name is taken you get `photo (1).webp`.

> Shift normally means *move* when you drag in Explorer. Satsuma always takes the drop as a
> **copy**, so Explorer never removes the original.

## What it can do

| Files | Convert to | Tools |
|---|---|---|
| **Images** — PNG, JPG, WEBP, GIF, BMP, TIFF, ICO, HEIC, AVIF… | PNG · JPG · WEBP · GIF · TIFF · ICO · AVIF · HEIC · BMP · PDF | Compress · Resize · Rotate · **Text** (copies the words in a picture, offline) · **Clean** (removes location and camera details) · B&W · Square · Flip |
| **Videos** — MP4, MOV, MKV, WEBM, AVI… | MP4 · MOV · MKV · WEBM · AVI · GIF · MP3 | Compress · Trim · Mute · Frame grab · Speed (¼×–4×) · **Level** (even out the volume) · Boomerang GIF · Rotate · Join |
| **Audio** — MP3, WAV, M4A, FLAC, OGG, OPUS, AIFF… | MP3 · M4A · WAV · FLAC · OGG · OPUS · AIFF | Trim · **Level** (even out the volume) · Join |
| **PDF** | PNG · JPG (per page) · TXT | Merge · Compress · Split · Extract pages · Rotate · Page numbers · Lock / Unlock (password) |
| **Word** — DOCX, DOC, ODT, RTF | PDF · DOCX · DOC · RTF · ODT · TXT · HTML | |
| **Excel** — XLSX, XLS, ODS, CSV | PDF · XLSX · XLS · ODS · CSV · JSON (from CSV) | |
| **PowerPoint** — PPTX, PPT, ODP | PDF · PPTX · PPT · ODP | |
| **Text & web** — TXT, Markdown, HTML, JSON | PDF · HTML ⇄ Markdown · TXT · DOCX (from HTML) · JSON → CSV | |
| **Archives** — ZIP, 7Z, RAR, TAR, TAR.GZ, GZ… | | Extract |
| **Anything** | | ZIP · **Rename** several files at once (`Trip 01`, `Trip 02`…), with a preview |

Drop **several files** at once to batch them, or to **merge** (PDFs, images → one PDF) and
**join** (videos, audio) them. Merging and joining go in file-name order — `part1`, `part2`,
`part10` — so name them to set the order.

Actions that need a value ask in a small window first. **Compress** shows the file's current size and
lets you pick how small (Light, Balanced, Strong, Tiny, or anything in between), with a live estimate
and a warning when the setting is strong enough to make it hard to read. Resize, Trim, Pages, Lock and
Speed ask too:

![a prompt](docs/prompt.png)

### What it needs

- **Images, PDFs, text, data, archives** — nothing extra (7Z and RAR use the `tar` built into
  Windows 10 and 11).
- **Video & audio** — FFmpeg. Satsuma downloads it automatically the first time you use a
  video/audio action (a one-time 100–200 MB download, saved in `%LOCALAPPDATA%\Satsuma\bin`;
  if FFmpeg is already on your PATH it uses that instead). You can also press
  *Download FFmpeg* in Settings.
- **Word / PowerPoint / Excel** — Microsoft Office, or [LibreOffice](https://www.libreoffice.org/)
  (free). Either one works for every Office conversion above; Office runs hidden in the
  background. Password-protected files are refused straight away with a clear message.

## First time? Take the tour

The first time Satsuma starts, a short guided tour walks through everything, with a practice ring
where you can try a drag without touching a real file. Replay it any time from the 🍊 menu → **Tour…**

![the tour's practice step](docs/tour.png)

## Privacy

Your files never leave your PC: every conversion runs locally, and nothing about your files, their
names or what you do with them is ever sent anywhere.

Satsuma goes online for three things only:
- **FFmpeg**, downloaded once the first time you use a video or audio action.
- **Updates** *(Satsuma.exe only)*: a few times a day it asks GitHub whether there's a newer release.
  If there is, it downloads it, checks it against the SHA-256 GitHub lists for it, and installs it
  the next time you're not using Satsuma. Turn it off in **Settings → About → Update automatically**.
- **An anonymous "I'm running" signal**, so the author can see how many people use Satsuma. Every
  10 minutes it sends a random ID made on your PC (not linked to you) and the Satsuma version.
  Turn it off in **Settings → About → Count me as an active user** (also on the tour's last page).

## Customise

Right-click the tray icon → **Settings…** It follows your theme and accent colour.

**Glass or Solid.** Satsuma comes in two styles. **Glass** (the default) makes every surface frosted
and see-through: Settings, prompts and menus use Windows' own acrylic blur, and the ring, result
cards and info panel blur whatever is behind them. **Solid** keeps them plain. Switch in
Settings → Appearance → Style.

![settings](docs/settings.png)

- **Appearance** — with a live preview you can hover and click: style (Glass / Solid), theme (Windows / light / dark),
  accent colour, how see-through the ring is, size, wedges per ring, which ring opens first,
  animation speed and bounce, what the centre shows, icons, a colour for the Convert ring by file type,
  and the info panel beside wedges.
- **Ring actions** — for each kind of file, **click a wedge in the preview** to swap in another
  conversion or take it off the ring; or tick and drag in the list beside it.
- **Trigger** — the key to hold (Shift / Ctrl / Alt), *only for real file drags*, start with
  Windows, *Send to* menu.
- **Saving** — where results go (next to the original, a subfolder, or one folder), with an
  example path; replace or add `(1)`; show in Explorer when done.
- **Watched folders** — run an action on every new file in a folder (say, Screenshots → WEBP).
  Files already there are left alone, and Satsuma never re-processes its own results.
- **Converters** — JPG/WEBP quality, compression strength, FFmpeg and Office/LibreOffice status.
- **About** — version, automatic updates, the user count, log, data folder, reset everything.

![watched folders](docs/watch.png)

## Build an .exe

**On your PC:** double-click **`build.bat`** → `dist\Satsuma.exe`, a single file you can share.
The build then runs `Satsuma.exe --self-test`, which exercises every engine inside the exe (images,
HEIC/AVIF, PDF rendering and passwords, text recognition, archives…) and stops if anything is missing.

**On GitHub (no setup):** put the workflow in `.github/workflows/build.yml` and push. It runs the
tests on Windows, builds the exe, starts it to check it works, and attaches
**Satsuma-windows.zip** to the run (Actions tab → latest run → Artifacts).

## Troubleshooting

- **Menu doesn't appear when dragging from an app running as Administrator.** Windows blocks
  drops from elevated apps into normal ones. Drag from regular Explorer windows, or run Satsuma
  as Administrator too.
- **Menu doesn't appear for files inside a .zip or from Outlook.** Those aren't real files on disk
  yet. Extract/save them first.
- **Shift-drag conflicts with another app.** Change the key in Settings → Trigger, or untick
  *Enabled* in the tray menu.
- **Windows SmartScreen warns about Satsuma.exe.** It's unsigned because it's your own build.
  Click *More info → Run anyway*.
- **Something failed?** The card says why. Full details: tray → **Open log**
  (`%LOCALAPPDATA%\Satsuma\satsuma.log`).

## Uninstall

Untick *Start when I sign in* and *Send to* in Settings, quit from the tray, then delete this
folder and `%LOCALAPPDATA%\Satsuma`.

## Project layout

```
main.py                   entry point
satsuma/app.py            tray, single instance, wiring
satsuma/detector.py       notices Shift-drags (polls GetAsyncKeyState, no hooks; slow when idle)
satsuma/actions.py        which actions show for which files
satsuma/jobs.py           background jobs, cancelling
satsuma/watcher.py        watched folders
satsuma/history.py        the tray's Recent list
satsuma/engine/           images · pdfs · media (FFmpeg) · documents (Qt, Office, LibreOffice) · archives
satsuma/ui/radial.py      the ring: geometry, hit-testing, drawing
satsuma/ui/menu.py        the overlay window (drag/drop, click and pinned modes)
satsuma/ui/toast.py       the result cards
satsuma/ui/settings_window.py, controls.py, prompts.py   Settings, its controls, the small dialogs
tests/                    pytest suite
tools/make_screenshots.py regenerates the pictures in docs/ from the app's own drawing code
```
