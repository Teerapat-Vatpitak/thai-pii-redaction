# The image NECTEC hosts. Until now this was the one build input that sat
# outside the verifiable-build system entirely: Python 3.11 while every other
# environment is 3.13, and a loose `requirements.txt` install while CI and the
# release build use the hash-pinned lockfile. It had also never been built or
# booted in CI, so nothing proved it worked at all.
#
# TODO before shipping to the platform: pin the base image by digest
# (python:3.13-slim@sha256:...) like every GitHub Action is pinned. Left as a
# tag here because the digest must be read from the registry, not guessed.
FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUTF8=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# The NER model is baked in below; forbid any runtime fetch so a container
# without egress behaves identically to one with it.
ENV PYTHAINLP_OFFLINE=1

# Deliberately no build-essential: requirements.lock resolves to wheels on
# cp313/linux. If a future dependency needs a compiler the docker-smoke CI job
# fails loudly here, which is the right place to find out — adding the toolchain
# pre-emptively would hide a ~300 MB regression in image size.
COPY requirements.lock ./
RUN python -m pip install --no-cache-dir pip==26.1.2 \
    && python -m pip install --no-cache-dir --require-hashes -r requirements.lock

# Bake the Thai NER model into the image. Without this the first request in a
# fresh container reaches out to download it — which fails on an isolated
# runner and silently makes cold-start latency a network measurement.
RUN python -c "from pythainlp.tag import NER; NER(engine='thainer')"

COPY . .

# Run as non-root user
RUN useradd --no-create-home --shell /bin/false appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
