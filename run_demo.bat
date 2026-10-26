@echo off
REM Live demo with a public link: share the https://....gradio.live link it prints.
REM Keep this window open and the laptop awake while the link is used.
cd /d %~dp0
python demo_app.py --share
pause
