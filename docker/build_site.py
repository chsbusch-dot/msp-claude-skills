#!/usr/bin/env python3
"""Render the MSP Operations Kit into a static, browsable docs site.

Runs at image build time only. Produces plain HTML/CSS/JS plus a client-side search
index; the runtime image is just Caddy serving the result, so nothing in this script
runs on the host.

Layout produced:

    /index.html                     README rendered (kit overview)
    /license.html                   LICENSE rendered
    /skills/<skill>/index.html      SKILL.md rendered
    /skills/<skill>/refs/<f>.html   skills/<skill>/references/<f>.md rendered
    /templates.html                 index of the Office templates
    /script.html                    price_quote.py, rendered + downloadable
    /files/<name>                   the docx/xlsx/py downloadables, byte-identical
    /assets/{style.css,app.js,search.json}

Markdown links are rewritten to their rendered URLs so the tree is navigable without
a server-side router. Nothing here trusts the runtime: the Caddyfile sends a strict CSP,
which is what actually neutralises any inline script or event handler that could ever
arrive in the markdown.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import markdown

# ---------------------------------------------------------------------------
# Doc model
# ---------------------------------------------------------------------------

SKILL_ORDER_HINT = [
    "msp-setup",
    "msp-brand",
    "msp-sales",
    "msp-marketing",
    "msp-leadgen",
    "msp-pricing",
    "msp-legal",
    "msp-website-setup",
    "msp-onboarding",
    "msp-offboarding",
    "msp-helpdesk",
    "msp-maintenance",
    "msp-client-comms",
    "msp-qbr",
    "msp-metrics",
    "msp-security",
]


@dataclass
class Doc:
    src: Path
    out: str  # e.g. "skills/msp-setup/index.html"
    title: str
    group: str  # sidebar grouping key
    group_title: str
    order: tuple = field(default_factory=lambda: (999, 999))
    body: str = ""
    text: str = ""  # plain text for search

    @property
    def url(self) -> str:
        return "/" + self.out


def frontmatter(text: str) -> tuple[dict, str]:
    """Split leading --- YAML-ish frontmatter. Values may be folded block scalars.

    Deliberately a tiny parser, not a YAML dependency: the frontmatter in this kit is
    only ever `name:` and `description:`, sometimes with a `>` folded block.
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text

    meta: dict[str, str] = {}
    key = None
    buf: list[str] = []
    for raw in lines[1:end]:
        if raw and not raw[0].isspace() and ":" in raw:
            if key:
                meta[key] = " ".join(buf).strip()
            key, _, val = raw.partition(":")
            key = key.strip()
            val = val.strip()
            buf = [] if val in (">", "|", ">-", "|-") else [val]
        elif key:
            buf.append(raw.strip())
    if key:
        meta[key] = " ".join(buf).strip()
    return meta, "\n".join(lines[end + 1 :]).lstrip("\n")


def strip_md(text: str) -> str:
    """Good-enough plain text for the search index."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.M)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)
    text = re.sub(r"^\s*\|.*$", " ", text, flags=re.M)
    text = re.sub(r"^\s*[-:|\s]+$", " ", text, flags=re.M)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Source -> output URL mapping
# ---------------------------------------------------------------------------

LINK_RE = re.compile(r"(!?\[[^\]]*\]\()([^)\s]+)(\s+\"[^\"]*\")?(\))")


def build_map(root: Path) -> dict[Path, str]:
    """Map every source file we intend to publish to its output path."""
    m: dict[Path, str] = {}

    readme = root / "README.md"
    if readme.is_file():
        m[readme.resolve()] = "index.html"
    lic = root / "LICENSE"
    if lic.is_file():
        m[lic.resolve()] = "license.html"

    for skill_dir in sorted((root / "skills").iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if skill_md.is_file():
            m[skill_md.resolve()] = f"skills/{skill_dir.name}/index.html"
        refs = skill_dir / "references"
        if refs.is_dir():
            for f in sorted(refs.glob("*.md")):
                m[f.resolve()] = f"skills/{skill_dir.name}/refs/{f.stem}.html"

    return m


def rewrite_links(body: str, src: Path, outmap: dict[Path, str], root: Path) -> str:
    """Rewrite relative .md links to rendered URLs; leave anything unknown alone."""

    def sub(mo: re.Match) -> str:
        pre, href, title, post = mo.group(1), mo.group(2), mo.group(3) or "", mo.group(4)
        if href.startswith(("http://", "https://", "mailto:", "#", "data:")):
            return mo.group(0)

        anchor = ""
        target = href
        if "#" in target:
            target, _, anchor = target.partition("#")
            anchor = "#" + anchor

        resolved = (src.parent / target).resolve()

        if resolved in outmap:
            url = "/" + outmap[resolved]
            if anchor:
                # keep the fragment; ids inside the rendered page are preserved
                url += anchor
            return f"{pre}{url}{title}{post}"

        # Templates and scripts are served as flat downloads under /files/.
        if target and resolved.is_file():
            return f"{pre}/files/{resolved.name}{anchor}{title}{post}"

        return mo.group(0)

    return LINK_RE.sub(sub, body)


# ---------------------------------------------------------------------------
# Page shell
# ---------------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{title} · MSP Operations Kit</title>
<link rel="stylesheet" href="/assets/style.css">
</head>
<body>
<header class="topbar">
  <button id="navtoggle" class="navtoggle" aria-label="Toggle navigation" aria-expanded="false">☰</button>
  <a class="brand" href="/">MSP Operations Kit</a>
  <span class="brandsub">internal reference</span>
  <div class="searchwrap">
    <input id="q" type="search" placeholder="Search all skills…" autocomplete="off"
           spellcheck="false" aria-label="Search all skills">
    <div id="results" class="results" hidden></div>
  </div>
</header>
<nav id="nav" class="sidebar">{nav}</nav>
<main class="content">
<div class="pagemeta">{meta}</div>
<article>{article}</article>
<footer class="pagefoot">
  Adapted from <a href="https://github.com/RTFM-IT-Services-LLC/msp-claude-skills">RTFM-IT-Services-LLC/msp-claude-skills</a>,
  licensed CC BY-NC-SA 4.0. Internal use only.
</footer>
</main>
<script src="/assets/app.js" defer></script>
</body>
</html>
"""


def build_nav(docs: list[Doc], current: str) -> str:
    groups: dict[str, list[Doc]] = {}
    for d in docs:
        groups.setdefault(d.group, []).append(d)

    # Ordering: the "skill" groups in the kit's own suggested order, then extras.
    def group_key(g: str) -> tuple:
        if g in SKILL_ORDER_HINT:
            return (0, SKILL_ORDER_HINT.index(g))
        return (1, g)

    out: list[str] = []
    overview = [d for d in docs if d.group == "_overview"]
    if overview:
        out.append('<div class="navgroup">')
        for d in overview:
            cls = "navlink current" if d.out == current else "navlink"
            out.append(f'<a class="{cls}" href="{d.url}">{html.escape(d.group_title)}</a>')
        out.append("</div>")

    for g in sorted(groups, key=group_key):
        if g == "_overview":
            continue
        items = sorted(groups[g], key=lambda d: (d.order, d.title))
        heads = [d for d in items if d.out.endswith("/index.html")]
        refs = [d for d in items if not d.out.endswith("/index.html")]
        label = heads[0].group_title if heads else g
        out.append('<div class="navgroup">')
        if heads:
            d = heads[0]
            cls = "navlink current" if d.out == current else "navlink"
            out.append(f'<a class="{cls} navskill" href="{d.url}">{html.escape(label)}</a>')
        else:
            out.append(f'<span class="navskill">{html.escape(label)}</span>')
        if refs:
            out.append('<div class="navrefs">')
            for d in refs:
                cls = "navref current" if d.out == current else "navref"
                out.append(f'<a class="{cls}" href="{d.url}">{html.escape(d.title)}</a>')
            out.append("</div>")
        out.append("</div>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/src", type=Path)
    ap.add_argument("--out", default="/site", type=Path)
    args = ap.parse_args()

    root: Path = args.root.resolve()
    out: Path = args.out.resolve()
    if not (root / "skills").is_dir():
        print(f"no skills/ under {root}", file=sys.stderr)
        return 1

    out.mkdir(parents=True, exist_ok=True)
    assets_out = out / "assets"
    assets_out.mkdir(exist_ok=True)

    # Static assets live beside this script so a local run and an image build produce the
    # same tree. Copied here rather than in the Dockerfile for exactly that reason.
    assets_src = Path(__file__).resolve().parent / "assets"
    if not assets_src.is_dir():
        print(f"assets/ not found next to {__file__}", file=sys.stderr)
        return 1
    for f in sorted(assets_src.iterdir()):
        if f.is_file():
            shutil.copy2(f, assets_out / f.name)

    outmap = build_map(root)
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list", "md_in_html"],
        output_format="html5",
    )

    docs: list[Doc] = []
    missing_links: list[str] = []

    # --- README as index -----------------------------------------------------
    if (root / "README.md").is_file():
        docs.append(
            Doc(
                src=root / "README.md",
                out="index.html",
                title="Overview",
                group="_overview",
                group_title="Overview",
            )
        )

    # --- one group per skill -------------------------------------------------
    for skill_dir in sorted((root / "skills").iterdir()):
        if not skill_dir.is_dir():
            continue
        name = skill_dir.name
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        meta, _ = frontmatter(skill_md.read_text(encoding="utf-8"))
        pretty = name.removeprefix("msp-").replace("-", " ")
        title = pretty.title()
        idx = SKILL_ORDER_HINT.index(name) if name in SKILL_ORDER_HINT else 99

        docs.append(
            Doc(
                src=skill_md,
                out=f"skills/{name}/index.html",
                title="Overview",
                group=name,
                group_title=title,
                order=(0, ""),
            )
        )
        refs = skill_dir / "references"
        if refs.is_dir():
            for i, f in enumerate(sorted(refs.glob("*.md"))):
                docs.append(
                    Doc(
                        src=f,
                        out=f"skills/{name}/refs/{f.stem}.html",
                        title=f.stem.replace("-", " ").title(),
                        group=name,
                        group_title=title,
                        order=(1, f.stem),
                    )
                )

    # --- rendered docs -------------------------------------------------------
    search: list[dict] = []
    for d in docs:
        raw = d.src.read_text(encoding="utf-8")
        meta, body = frontmatter(raw)
        if d.src.name == "SKILL.md":
            # the frontmatter description is the most useful summary line
            desc = meta.get("description", "")
            if desc:
                body = f"> {desc}\n\n" + body
        body = rewrite_links(body, d.src, outmap, root)
        md.reset()
        d.body = md.convert(body)
        d.text = strip_md(raw)

        meta_bits = [f'<span class="crumb">{html.escape(d.group_title)}</span>']
        if d.src.name == "SKILL.md":
            meta_bits.append(f'<code class="srcpath">skills/{d.group}/SKILL.md</code>')
        else:
            meta_bits.append(
                f'<code class="srcpath">skills/{d.group}/references/{d.src.name}</code>'
            )
        d.meta_html = " ".join(meta_bits)

        path = out / d.out
        path.parent.mkdir(parents=True, exist_ok=True)

        # search chunks, split on headings for tighter hits
        chunks = re.split(r"\n(?=#{2,4}\s)", raw)
        for ch in chunks:
            m = re.match(r"#{2,4}\s+(.+)", ch)
            heading = m.group(1).strip() if m else (meta.get("description", "") or d.title)
            text = strip_md(ch)
            if len(text) < 24:
                continue
            search.append(
                {
                    "u": d.url,
                    "t": d.group_title,
                    "h": heading[:120],
                    "x": text[:400],
                }
            )

        # figure out the group title for other docs
        if not hasattr(d, "meta_html"):
            d.meta_html = ""
        d.title_html = d.title

    # --- templates + script pages -------------------------------------------
    tmpl_dir = root / "templates"
    script_py = root / "skills/msp-pricing/scripts/price_quote.py"
    files_out = out / "files"
    files_out.mkdir(exist_ok=True)

    tpl_rows = []
    if tmpl_dir.is_dir():
        for f in sorted(tmpl_dir.iterdir()):
            if not f.is_file():
                continue
            shutil.copy2(f, files_out / f.name)
            tpl_rows.append(
                f'<tr><td><a href="/files/{html.escape(f.name)}">{html.escape(f.name)}</a></td>'
                f"<td>{f.stat().st_size:,} B</td></tr>"
            )

    script_html = ""
    if script_py.is_file():
        shutil.copy2(script_py, files_out / script_py.name)
        src = script_py.read_text(encoding="utf-8")
        script_html = (
            f'<p><a href="/files/{script_py.name}">Download {script_py.name}</a>'
            f" ({script_py.stat().st_size:,} B)</p>"
            f"<pre class=\"code\">{html.escape(src)}</pre>"
        )
        search.append(
            {
                "u": "/script.html",
                "t": "Pricing",
                "h": "price_quote.py",
                "x": strip_md(src)[:400],
            }
        )

    extra_docs = [
        Doc(
            src=root / "templates",
            out="templates.html",
            title="Templates",
            group="_overview",
            group_title="Templates",
            body=(
                "<p>Office templates shipped with the kit. These are the example drafts that "
                "require your own attorney's review before first use (see msp-legal).</p>"
                '<table><thead><tr><th>File</th><th>Size</th></tr></thead><tbody>'
                + "".join(tpl_rows)
                + "</tbody></table>"
            ),
            text="templates docx xlsx office documents msa sow dpa risk acceptance waiver "
            "service order qbr scorecard monthly review",
        ),
        Doc(
            src=root / "skills/msp-pricing/scripts/price_quote.py",
            out="script.html",
            title="price_quote.py",
            group="_overview",
            group_title="Pricing script",
            body=(
                "<p>The pricing configurator, verbatim as shipped. Run it locally; it only "
                "reads a JSON file you point it at and prints a report. No network calls.</p>"
                + script_html
            ),
            text=strip_md(script_py.read_text(encoding="utf-8"))[:8000]
            if script_py.is_file()
            else "",
        ),
    ]

    # LICENSE
    if (root / "LICENSE").is_file():
        extra_docs.append(
            Doc(
                src=root / "LICENSE",
                out="license.html",
                title="License",
                group="_overview",
                group_title="License",
                body="<pre class=\"code\">"
                + html.escape((root / "LICENSE").read_text(encoding="utf-8"))
                + "</pre>",
                text="license CC BY-NC-SA 4.0 non-commercial attribution",
            )
        )

    all_docs = docs + extra_docs
    for d in all_docs:
        meta = getattr(d, "meta_html", "")
        if d.out in ("index.html",):
            meta = '<span class="crumb">Overview</span>'
        if not meta:
            meta = f'<span class="crumb">{html.escape(d.group_title)}</span>'
        (out / d.out).write_text(
            PAGE.format(
                title=html.escape(d.group_title + " · " + d.title if d.title != "Overview" else d.group_title),
                nav=build_nav(all_docs, d.out),
                meta=meta,
                article=d.body,
            ),
            encoding="utf-8",
        )

    (assets_out / "search.json").write_text(
        json.dumps(search, ensure_ascii=False), encoding="utf-8"
    )

    # 404 page
    (out / "404.html").write_text(
        PAGE.format(
            title="Not found",
            nav=build_nav(all_docs, ""),
            meta='<span class="crumb">Not found</span>',
            article="<h1>Not found</h1><p>No such page. Start at the "
            '<a href="/">overview</a>.</p>',
        ),
        encoding="utf-8",
    )

    print(f"rendered {len(all_docs)} pages, {len(search)} search chunks into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
