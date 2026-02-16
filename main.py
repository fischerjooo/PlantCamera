from pathlib import Path

from src.webapp import run_web_server

# =============================
# Hardcoded runtime parameters
# =============================
HOST = "0.0.0.0"
PORT = 8080
REPO_ROOT = Path(__file__).resolve().parent
REMOTE_NAME = "origin"
MAIN_BRANCH = "main"
UPDATE_ENDPOINT = "/update"


if __name__ == "__main__":
    run_web_server(
        host=HOST,
        port=PORT,
        repo_root=REPO_ROOT,
        remote_name=REMOTE_NAME,
        main_branch=MAIN_BRANCH,
        update_endpoint=UPDATE_ENDPOINT,
    )
