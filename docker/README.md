# Docs site image

Containerize the kit as a browsable internal reference site.

The kit is markdown, one CLI script, and six Office templates. There is nothing to *run*,
so the container is a renderer plus a static file server: markdown is rendered to HTML at
image build time and Caddy serves the result. No runtime dependency, no database, no
network egress.

## Split of responsibilities

This directory owns the **image**. The homelab owns the **runtime composition**
(`/opt/apphost/msp-skills/compose.yaml` on `.212`), the same split as costwatch and
auction-watch:

- image: `docker/Dockerfile` + `docker/build_site.py` + `docker/assets/` here
- runtime: `compose.yaml`, `msp-skills-up.sh`, caddy-lan route, Authelia policy
- the GitOps source of truth for the runtime is
  `homelab-infra/provisioning/apphost/msp-skills/`

## Build

Context is the repository root, not this directory:

```bash
docker build -f docker/Dockerfile -t msp-skills:local .
```

On `.212` the compose file does this from the clone at `/opt/apphost/src/msp-skills`
(see the git-everywhere deploy standard: the box holds a real clone it can `git pull`).

Both bases are pinned by **digest**, not by tag, because that deploy rebuilds on every run: a
floating tag would let an upstream push change the served pages, or the server, with no commit
here. `caddy:2.11-alpine` is pinned to the manifest that reports `CADDY_VERSION=v2.11.4`, the
version the live site was verified against. Do not relax this to a tag for convenience.

## What lands in the image

```
/srv/index.html                      README, rendered (kit overview)
/srv/license.html                    LICENSE, rendered
/srv/skills/<skill>/index.html       SKILL.md, rendered
/srv/skills/<skill>/refs/<f>.html    skills/<skill>/references/<f>.md, rendered
/srv/templates.html                  index of the Office templates
/srv/script.html                     price_quote.py, rendered
/srv/files/<name>                    the docx/xlsx/py originals, byte-identical
/srv/assets/{style.css,app.js,search.json}
```

48 rendered pages plus a 404 page, and a 428-chunk client-side search index.

Relative `.md` links are rewritten at build time, so the tree is fully navigable with no
server-side router. The generator fails the build (`test -s` guards in the Dockerfile) if
a page or asset comes out empty.

## Runtime posture

- listens on `:8080`, **container-internal only**; no host port is published
- reachable exclusively on the Docker `edge` network
- caddy-lan terminates TLS for `msp-skills.lan.synviron.com` and puts Authelia in front
- runs as uid/gid `10001`, never root
- compose adds `read_only` root, `cap_drop: ALL`, `no-new-privileges`; only `/tmp` and the
  Caddy data/config paths are writable, as tmpfs
- no secrets, no environment variables, no volumes beyond Caddy's own state

## Response headers

The content is generated from markdown and markdown can carry raw HTML, so the defense is
the header, not the renderer:

```
Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self';
  img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none';
  form-action 'none'; frame-ancestors 'none'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Resource-Policy: same-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

`script-src 'self'` with no `unsafe-inline` is the load-bearing part: any inline `<script>`
or `on*=` handler that ever arrived in the markdown would not execute. That is why
`app.js` is a separate file rather than inline.

## Local sanity check

```bash
docker build -f docker/Dockerfile -t msp-skills:local .
docker run --rm -p 18099:8080 msp-skills:local
curl -sS -i http://127.0.0.1:18099/healthz      # 200 ok
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18099/nope   # 404
```

Or render without Docker (needs `markdown==3.11`):

```bash
python3 docker/build_site.py --root . --out /tmp/site
```

## License note

The kit is CC BY-NC-SA 4.0 (non-commercial, share-alike). This deployment is for internal
reference use, which the license permits. Adding these container files is an adaptation of
the licensed work, so they carry the same license. Do not repackage or resell.
