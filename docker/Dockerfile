# MSP Operations Kit, internal docs site image.
#
# The app repo owns the IMAGE; the homelab owns the RUNTIME COMPOSITION
# (/opt/apphost/msp-skills/compose.yaml on .212). Same split as costwatch and
# auction-watch.
#
# Two stages. The build stage is the only one with Python and network access, and it
# disappears from the final image: stage 2 is Caddy plus files. That keeps the runtime
# surface to one static binary serving pre-generated HTML.
#
# Build context is the repository root:
#
#   docker build -f docker/Dockerfile -t msp-skills:local .
#
# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: render the markdown into static HTML
# ---------------------------------------------------------------------------
FROM python:3.12-alpine AS build

WORKDIR /src

# Dependencies first so the layer caches across content edits.
COPY docker/requirements.txt /src/docker/requirements.txt
RUN pip install --no-cache-dir --no-compile -r /src/docker/requirements.txt

COPY docker/build_site.py /src/docker/build_site.py
COPY docker/assets /src/docker/assets

# Content. Copied explicitly rather than `COPY . .` so nothing unexpected (git objects,
# local scratch files, .env) can reach the renderer or the image.
COPY README.md LICENSE /src/
COPY skills /src/skills
COPY templates /src/templates

RUN python3 /src/docker/build_site.py --root /src --out /srv \
 && test -s /srv/assets/search.json \
 && test -s /srv/assets/style.css \
 && test -s /srv/assets/app.js \
 && test -f /srv/index.html \
 && test -f /srv/skills/msp-pricing/index.html

# ---------------------------------------------------------------------------
# Stage 2: serve it. Nothing from stage 1 survives except /srv.
# ---------------------------------------------------------------------------
FROM caddy:2.11-alpine

# Caddy's own user, so the process never runs as root.
RUN addgroup -S -g 10001 site 2>/dev/null || true \
 && adduser -S -D -H -u 10001 -G site site 2>/dev/null || true \
 && mkdir -p /srv /data /config /etc/caddy \
 && chown -R 10001:10001 /srv /data /config /etc/caddy

COPY --from=build --chown=10001:10001 /srv /srv
COPY --chown=10001:10001 docker/Caddyfile /etc/caddy/Caddyfile

USER 10001:10001

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["caddy"]
CMD ["run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
