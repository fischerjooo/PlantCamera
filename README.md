# PlantCamera

PlantCamera is a lightweight Termux-friendly timelapse dashboard.

## Run

```bash
python -m plantcamera
```

Compatibility entrypoint is still available:

```bash
python main.py
```

## Architecture

- `plantcamera/config.py`: central env/CLI configuration.
- `plantcamera/web/`: HTTP server, route dispatch, and HTML template rendering.
- `plantcamera/services/`: timelapse/media/update business logic.
- `plantcamera/infra/`: subprocess wrappers (`termux-camera-photo`, `ffmpeg`, `git`, process restart).

## Default media directory

`/sdcard/DCIM/PlantCamera`

## Testing

```bash
pytest -q
```
