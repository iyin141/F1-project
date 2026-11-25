# ML worker image: the base API image plus CPU PyTorch and NVIDIA structured-data-models
# (Kumo Tabular). Only the `worker-ml` service uses this image, so torch never
# loads in the web process.

ARG BASE_IMAGE=f1-control-room-api:latest
FROM ${BASE_IMAGE}

USER root
# CPU-only torch (cp313 wheels exist for both): aarch64 PyPI wheels are CPU-only; on amd64 use the CPU index
# (the PyPI x86_64 wheel is the CUDA build). scikit-learn/pyarrow come pinned from the base image.
RUN if [ "$(uname -m)" = "x86_64" ]; then \
      pip install torch --index-url https://download.pytorch.org/whl/cpu ; \
    else \
      pip install torch ; \
    fi \
 && pip install "structured-data-models" lightgbm==4.7.0 \
 && mkdir -p /models /features && chown -R app:app /models /features

# LightGBM loads the OpenMP runtime (libgomp.so.1), which the slim base image does not ship; a separate layer keeps the torch layer cached.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

# Hugging Face weights are cached on a volume so they download once.
ENV HF_HOME=/models/hf \
    FEATURES_DIR=/features

USER app
CMD ["celery", "-A", "f1_project", "worker", "-Q", "ml", "-c", "1", "-n", "worker_ml@%h", "--loglevel=info"]
