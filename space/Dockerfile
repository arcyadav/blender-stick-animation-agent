# Hugging Face Space (Docker): Blender 4.5 LTS headless + the Gradio app, CPU only.
# Workbench renders through EGL with Mesa's software driver; no GPU or display is needed.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        wget xz-utils ca-certificates \
        libegl1 libegl-mesa0 libgl1 libglx-mesa0 libgl1-mesa-dri libgbm1 \
        libx11-6 libxext6 libxi6 libxrender1 libxfixes3 libxkbcommon0 libsm6 libice6 libxxf86vm1 \
        libbsd0 libuuid1 \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q https://download.blender.org/release/Blender4.5/blender-4.5.14-linux-x64.tar.xz \
    && tar xf blender-4.5.14-linux-x64.tar.xz -C /opt && rm blender-4.5.14-linux-x64.tar.xz

RUN pip install --no-cache-dir "gradio==5.50.0"

# Spaces run as user 1000; the app writes clips under outputs/
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user BLENDER_EXE=/opt/blender-4.5.14-linux-x64/blender P5_PUBLIC=1 \
    PYTHONUNBUFFERED=1 GRADIO_ANALYTICS_ENABLED=False
WORKDIR /home/user/app
COPY --chown=user . .
EXPOSE 7860
CMD ["python", "demo_app.py"]
