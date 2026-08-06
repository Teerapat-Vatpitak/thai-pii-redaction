# Generic hosted-candidate image. Local and CI evidence does not imply an
# official AI for Thai deployment or approved public route contract. The image
# uses the same pinned Python dependency tier as the repository checks.
#
# Multi-platform OCI index for the official Python 3.13.14 slim-trixie image,
# resolved from Docker Hub on 2026-07-22. Pinning the index (rather than one
# architecture manifest) preserves Docker's native amd64/arm64 selection.
FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91

WORKDIR /app

ENV PYTHONUTF8=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# PyThaiNLP defaults its data dir to ~/pythainlp-data. The runtime user has no
# home (--no-create-home below), so pin a fixed, appuser-owned location that the
# baked model lives in and the container can read at boot.
ENV PYTHAINLP_DATA=/opt/pythainlp-data

# Deliberately no build-essential: requirements.lock resolves to wheels on
# cp313/linux. If a future dependency needs a compiler the docker-smoke CI job
# fails loudly here, which is the right place to find out — adding the toolchain
# pre-emptively would hide a ~300 MB regression in image size.
COPY requirements.lock ./
RUN python -m pip install --no-cache-dir pip==26.1.2 \
    && python -m pip install --no-cache-dir --require-hashes -r requirements.lock

# Bake the Thai NER model into the image. Without this the first request in a
# fresh container reaches out to download it — which fails on an isolated
# runner and silently makes cold-start latency a network measurement. This
# step is the download, so it must run BEFORE PYTHAINLP_OFFLINE is set —
# offline mode blocks the fetch and the prewarm fails with corpus-not-found.
RUN mkdir -p "$PYTHAINLP_DATA" \
    && python -c "from pythainlp.tag import NER; NER(engine='thainer')"

# Now that the model is baked in, forbid any runtime fetch so a container
# without egress behaves identically to one with it.
ENV PYTHAINLP_OFFLINE=1

COPY . .

# Run as non-root user
RUN useradd --no-create-home --shell /bin/false appuser \
    && chown -R appuser /app "$PYTHAINLP_DATA"
USER appuser

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.hosted:app", "--host", "0.0.0.0", "--port", "8000"]
