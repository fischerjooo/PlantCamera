# PlantCamera

A small Python web server designed for Termux on Android.

## Run

```bash
python main.py
```

Then open one of the addresses printed in the terminal.

- On the same device, use `http://127.0.0.1:8080`.
- From another PC on the same network, use the phone/computer LAN IP, for example `http://192.168.1.23:8080`.

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

- Shows the current git branch and last commit timestamp at the top.
- Has an **Update** button.
- Update flow:
  - fetches/prunes remotes,
  - switches to the first branch found that is not `main` (if any),
  - otherwise switches to `main`,
  - pulls latest changes from `origin`,
  - restarts the Python process to run the updated code.

## Termux notes

Install Python + Git:

```bash
pkg update
pkg install python git
```

Run inside your repo clone:

```bash
python main.py
```
