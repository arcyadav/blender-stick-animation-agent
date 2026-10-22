"""Contact sheet of a rendered clip: N evenly spaced frames in a grid.

    python -m scripts.sheet outputs/eval/A0/p04/final.mp4 [--n 12] [--cols 4]
"""
import argparse
import os
import shutil
import subprocess

FFMPEG = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or \
    r"C:\Users\ysarc\Downloads\ffmpeg-8.0-full_build\ffmpeg-8.0-full_build\bin\ffmpeg.exe"


def frames(video):
    probe = os.path.join(os.path.dirname(FFMPEG), "ffprobe")
    out = subprocess.run([probe, "-v", "error", "-count_frames",
                          "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0",
                          video], capture_output=True, text=True).stdout
    return int(out.strip())


def sheet(video, n=12, cols=4, out=None):
    total = frames(video)
    picks = [round(i * (total - 1) / (n - 1)) for i in range(n)]
    sel = "+".join(f"eq(n\\,{p})" for p in picks)
    rows = -(-n // cols)
    out = out or os.path.join(os.path.dirname(video), "sheet.png")
    vf = (f"select='{sel}',scale=400:-1,drawtext=text='%{{n}}':x=6:y=6:fontsize=16:fontcolor=gray,"
          f"tile={cols}x{rows}:padding=4:color=white")
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", video, "-vf", vf, "-frames:v", "1",
                    "-fps_mode", "vfr", out], check=True)
    return out, picks


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--cols", type=int, default=4)
    a = ap.parse_args()
    print(sheet(a.video, a.n, a.cols))
