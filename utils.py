# utils.py
import os


def write_step_summary(text: str) -> None:
    """Append a summary to GitHub Step Summary file if available."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
