"""Stage the app, the final results and the replayed clips, and upload them to the Hugging Face Space.

Needs `huggingface-cli login` with a write token (done for Projects 3 and 4).
    python space/deploy.py [--space Arcyadav/stick-animation-agent] [--dry-run]
"""
import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "outputs" / ".space"
INCLUDE = ["config.py", "demo_app.py", "story.py", "tasks.json", "agent", "blender_worker", "checks", "motions",
           "stories", "results/final_2026-10-25"]
SKIP = {"__pycache__", "claude_runs"}
CLIPS = ROOT / "outputs" / "replays"


def stage():
    shutil.rmtree(STAGE, ignore_errors=True)
    for rel in INCLUDE:
        src, dst = ROOT / rel, STAGE / rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        else:
            shutil.copytree(src, dst, ignore=lambda d, names: [n for n in names if n in SKIP or
                                                                n.endswith((".pyc", ".log", ".blend", ".png"))])
    for f in CLIPS.glob("*/*.mp4"):                    # outputs/replays/<agent>/<task>.mp4
        dst = STAGE / "outputs" / "replays" / f.parent.name / f.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
    for name in ("Dockerfile", "README.md"):
        shutil.copy2(ROOT / "space" / name, STAGE / name)
    (STAGE / ".gitattributes").write_text("*.mp4 filter=lfs diff=lfs merge=lfs -text\n")
    files = [p for p in STAGE.rglob("*") if p.is_file()]
    print(f"staged {len(files)} files, {sum(p.stat().st_size for p in files) / 1e6:.1f} MB -> {STAGE}")


def upload(space):
    from huggingface_hub import HfApi
    api = HfApi()
    print("logged in as", api.whoami()["name"])
    api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)
    api.upload_folder(folder_path=str(STAGE), repo_id=space, repo_type="space",
                      commit_message="Deploy stick animation agent")
    print(f"https://huggingface.co/spaces/{space}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default="Arcyadav/stick-animation-agent")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    stage()
    if not a.dry_run:
        upload(a.space)
