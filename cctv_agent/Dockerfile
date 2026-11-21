# Upande Security CCTV site agent (+ ffmpeg for on-demand playback/transcode).
FROM python:3.12-slim

RUN apt-get update \
	&& apt-get install -y --no-install-recommends ffmpeg tini \
	&& rm -rf /var/lib/apt/lists/* \
	&& useradd --system --uid 10001 agent \
	&& mkdir -p /data /config && chown agent /data

WORKDIR /app
COPY pyproject.toml ./
COPY cctv_agent ./cctv_agent
RUN pip install --no-cache-dir .

USER agent
VOLUME ["/data"]
ENTRYPOINT ["tini", "--", "python", "-m", "cctv_agent"]
CMD ["--config", "/config/agent.yml"]
