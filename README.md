# PlantCamera

A small Python web server designed for Termux on Android.

## Run

```bash
python main.py
```

Or use the launcher script:

```bash
./main
```

Then open `http://127.0.0.1:8000` in your browser.

## Hardcoded parameters

All runtime parameters are hardcoded at the top of `main.py`:

- `HOST`
- `PORT`
- `REPO_ROOT`
- `REMOTE_NAME`
- `MAIN_BRANCH`
- `UPDATE_ENDPOINT`

`main.py` takes no command-line parameters.

## Features

- Timelapse manager (integrated into the existing app):
  - captures `frames_current/frame_YYYYMMDD_HHMMSS.jpg` every 30 minutes via `termux-camera-photo`,
  - keeps the latest capture in `live.jpg`,
  - runs 24-hour sessions,
  - encodes collected frames with `ffmpeg` into H.264 MP4 (`libx264`) at 24 fps,
  - stores output as `videos/timelapse_YYYYMMDD_HHMMSS_YYYYMMDD_HHMMSS.mp4`,
  - deletes source frames only when encode succeeds,
  - preserves frames and retries encoding on the next cycle if encoding fails.
- Dashboard (`/`) with 5-second refresh:
  - live view,
  - last capture timestamp and errors,
  - timelapse progress and image counters,
  - video management (watch, download, delete).
- Media endpoints:
  - `/live.jpg`
  - `/videos/<file>.mp4`
  - `/download/<file>.mp4`
  - `POST /delete/<file>.mp4`
- Git updater:
  - fetches/prunes remotes,
  - keeps the current non-`main` branch only while it still exists on the remote,
  - otherwise switches to the first branch found that is not `main` (if any),
  - if no non-`main` branch exists, switches to `main`,
  - pulls latest changes from `origin`,
  - restarts the Python process to run the updated code.

## Termux notes

Install Python + Git + ffmpeg:

```bash
pkg update
pkg install python git ffmpeg
```

Run inside your repo clone:

```bash
python main.py
```

To manually sync the repo to the latest `main` with rebase:

```bash
./update_main.sh
```
