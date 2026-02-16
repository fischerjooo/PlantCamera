# PlantCamera

A small Python web server designed for Termux on Android.

## Run

```bash
python main.py
```

Then open `http://127.0.0.1:8080` in your browser.

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
