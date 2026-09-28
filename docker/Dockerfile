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
# Bases are pinned by digest, not by tag. The compose stack on .212 rebuilds from the git
# clone on every deploy (msp-skills-up.sh does `up -d --build`), so a floating tag would let
# an upstream push change the served bytes with no commit here. Resolved 2026-09-27.
FROM python:3.12-alpine@sha256:4c47124a8391cb7a9f571164147d154777cf012a4ece5f86097130d7a4478111 AS build

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
# Pinned by digest (resolved 2026-09-27): this manifest is CADDY_VERSION=v2.11.4, the version
# the live deployment was validated against. Same rule as the digest-pinned lan-portal images.
FROM caddy:2.11-alpine@sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b

# Caddy's own user, so the process never runs as root.
RUN addgroup -S -g 10001 site 2>/dev/null || true \
 && adduser -S -D -H -u 10001 -G site site 2>/dev/null || true \
 && mkdir -p /srv /data /config /etc/caddy \
 && chown -R 10001:10001 /srv /data /config /etc/caddy

# The upstream image grants the binary cap_net_bind_service=ep so a non-root Caddy can bind
# :80. This container listens on :8080, so the capability is never needed, and leaving it on
# makes the binary UNEXECUTABLE under the compose hardening: cap_drop ALL plus
# no-new-privileges makes the exec fail with EPERM ("tini: exec caddy failed: Operation not
# permitted"). Stripping it removes the escalation vector and lets the hardening hold.
RUN setcap -r /usr/bin/caddy

COPY --from=build --chown=10001:10001 /srv /srv
COPY --chown=10001:10001 docker/Caddyfile /etc/caddy/Caddyfile

USER 10001:10001

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["caddy"]
CMD ["run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
