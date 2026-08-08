#!/usr/bin/env python3
"""
Mirror the official Semarchy xDM documentation into the corpus as Markdown.

    pip install requests beautifulsoup4 lxml
    python scripts/fetch_docs.py .                 # ~300 pages, a few minutes
    python scripts/fetch_docs.py . --images        # also download the screenshots

Source : https://semarchy.com/doc/semarchy-xdm/xdm/latest/  (Antora static site)
Output : docs/<Section>/<page>.md   one Markdown file per doc page
         docs/index.yaml            url -> local path -> title -> section
         docs/_images/              screenshots, when --images is passed

Crawl is a BFS over in-scope links starting from the site nav, so it follows the
documentation's own structure rather than a guessed URL list. Idempotent: pages that
already exist on disk are skipped unless --force.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup, NavigableString, Tag
except ImportError:
    sys.exit("pip install requests beautifulsoup4 lxml")

ORIGIN = "https://semarchy.com"
PREFIX = "/doc/semarchy-xdm/xdm/latest/"
SEED = PREFIX + "Install/overview.html"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"


# ----------------------------------------------------------------- conversion
def _inline(node, base: str) -> str:
    """Render inline content (links, code, emphasis, images) to Markdown."""
    if isinstance(node, NavigableString):
        return str(node).replace("\xa0", " ")
    if not isinstance(node, Tag):
        return ""

    name = node.name
    classes = " ".join(node.get("class") or [])
    inner = "".join(_inline(c, base) for c in node.children)

    # Antora emits EMPTY inline elements: <a class="anchor"> inside every heading and
    # <i class="conum"> before every callout marker. Decorating them yields stray
    # markup ("[](url)Overview", "****1**"), and the anchor URL then lands in the
    # search index on every heading of every page.
    if name in ("a", "strong", "b", "em", "i", "code", "kbd") and not inner.strip():
        return ""

    if name in ("code", "kbd") or (name == "span" and "code" in classes):
        return f"`{node.get_text().strip()}`"
    if name in ("strong", "b"):
        return f"**{inner.strip()}**"
    if name in ("em", "i"):
        return f"*{inner.strip()}*"
    if name == "a":
        href = node.get("href")
        return f"[{inner.strip()}]({urljoin(base, href)})" if href else inner
    if name == "br":
        return "\n"
    if name == "img":
        return f"![{node.get('alt', '')}]({urljoin(base, node.get('src', ''))})"
    return inner


def _walk(el, base: str, out: list[str], depth: int = 0) -> None:
    for node in el.children:
        if not isinstance(node, Tag):
            continue
        name = node.name
        classes = " ".join(node.get("class") or [])

        if re.fullmatch(r"h[1-6]", name):
            out += ["", "#" * int(name[1]) + " " + _inline(node, base).strip(), ""]
            continue

        if "listingblock" in classes or "literalblock" in classes:
            pre = node.find("pre")
            if not pre:
                continue
            code = pre.find("code")
            lang = ""
            if code:
                m = re.search(r"language-([\w-]+)", " ".join(code.get("class") or []))
                lang = m.group(1) if m else ""
            cap = node.find(class_="title")
            if cap:
                out.append(f"*{cap.get_text().strip()}*")
            out += ["```" + lang, pre.get_text().rstrip(), "```", ""]
            continue

        if "admonitionblock" in classes:
            icon = node.find(class_="icon")
            kind = (icon.get_text().strip() if icon else "NOTE") or "NOTE"
            body = node.find(class_="content")
            text = _inline(body, base).strip() if body else ""
            text = re.sub(r"\n+", "\n> ", text)
            out += [f"> **{kind.upper()}** {text}", ""]
            continue

        if "imageblock" in classes:
            img = node.find("img")
            if img:
                out.append(f"![{img.get('alt', '')}]({urljoin(base, img.get('src', ''))})")
            cap = node.find(class_="title")
            if cap:
                out.append(f"*{cap.get_text().strip()}*")
            out.append("")
            continue

        if name == "table" or "tableblock" in classes:
            table = node if name == "table" else node.find("table")
            if not table:
                continue
            cap = node.find(class_="title") or table.find("caption")
            if cap:
                out.append(f"*{cap.get_text().strip()}*")
            for i, tr in enumerate(table.find_all("tr")):
                cells = [
                    re.sub(r"\s+", " ", _inline(td, base)).replace("|", r"\|").strip()
                    for td in tr.find_all(["td", "th"])
                ]
                out.append("| " + " | ".join(cells) + " |")
                if i == 0:
                    out.append("|" + "|".join("---" for _ in cells) + "|")
            out.append("")
            continue

        if name in ("ul", "ol"):
            ordered = name == "ol"
            for i, li in enumerate(node.find_all("li", recursive=False)):
                nested = li.find_all(["ul", "ol"], recursive=False) + [
                    d for d in li.find_all(class_=["ulist", "olist"], recursive=False)
                ]
                clone = BeautifulSoup(str(li), "lxml").find("li")
                for tag in clone.find_all(["ul", "ol"]):
                    tag.decompose()
                text = re.sub(r"\s+", " ", _inline(clone, base)).strip()
                if text:
                    bullet = f"{i + 1}. " if ordered else "- "
                    out.append("  " * depth + bullet + text)
                for sub in nested:
                    _walk(sub if sub.name in ("ul", "ol") else sub, base, out, depth + 1)
            out.append("")
            continue

        if name == "p":
            text = _inline(node, base).strip()
            if text:
                out += [text, ""]
            continue

        if name == "dl":
            for child in node.find_all(["dt", "dd"], recursive=False):
                text = _inline(child, base).strip()
                if text:
                    out.append(f"**{text}**" if child.name == "dt" else f"  {text}")
            out.append("")
            continue

        _walk(node, base, out, depth)


def html_to_markdown(article, base: str) -> str:
    out: list[str] = []
    _walk(article, base, out)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def drop_leading_title(body: str, title: str) -> str:
    """Remove a leading H1 that just repeats the page title.

    Antora sometimes puts an <h1 class="page"> inside the article and sometimes does
    not — we observed the same URL served both ways within minutes. Since the file
    already opens with `# {title}`, keeping the article's copy produces the title
    twice, and *which* form you get depends on which variant the server happened to
    serve. Normalising here makes the mirror reproducible either way.

    Compared with whitespace normalised: titles routinely contain U+00A0, which
    _inline converts to a plain space, so the two forms are not equal as strings.
    """
    lines = body.split("\n")
    if not lines or not lines[0].startswith("# "):
        return body
    norm = lambda t: " ".join(t.replace("\xa0", " ").split())
    if norm(lines[0][2:]) != norm(title):
        return body
    rest = lines[1:]
    while rest and not rest[0].strip():
        rest.pop(0)
    return "\n".join(rest)


# ---------------------------------------------------------------------- crawl
def _image_path(src: str) -> str:
    """Section-qualified image path, e.g. "Design/menu.svg".

    Keying by basename alone flattens all sections into one namespace: `menu.svg`
    exists under both Design/ and Discovery/, and the loser is silently dropped.
    """
    parts = Path(urlparse(src).path).parts
    section = parts[parts.index("_images") - 1] if "_images" in parts else "_root"
    return f"{section}/{Path(src).name}"


def local_path(url_path: str) -> str:
    rel = url_path[len(PREFIX):]
    return re.sub(r"\.html$", ".md", rel)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--images", action="store_true", help="download screenshots too")
    ap.add_argument("--force", action="store_true", help="refetch pages already on disk")
    ap.add_argument("--delay", type=float, default=0.2, help="seconds between requests")
    ap.add_argument("--limit", type=int, help="stop after N pages (for smoke tests)")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = UA

    queue, seen = deque([SEED]), {SEED}
    manifest, failures, images = [], [], {}

    while queue:
        if args.limit and len(manifest) >= args.limit:
            break
        path = queue.popleft()
        url = ORIGIN + path
        dest = docs / local_path(path)

        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            failures.append((path, str(exc)[:100]))
            continue

        soup = BeautifulSoup(resp.text, "lxml")

        # discover more pages regardless of whether we rewrite this one
        for a in soup.find_all("a", href=True):
            nxt = urlparse(urljoin(url, a["href"])).path
            if nxt.startswith(PREFIX) and nxt.endswith(".html") and nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)

        article = (soup.find("article", class_="doc")
                   or soup.find("article") or soup.find("main"))
        h1 = soup.find("h1")
        title = re.sub(r" :: .*$", "", (h1.get_text() if h1 else soup.title.get_text())).strip()
        section = path[len(PREFIX):].split("/")[0]

        manifest.append({"url": url, "file": f"docs/{local_path(path)}",
                         "title": title, "section": section})

        if dest.exists() and not args.force:
            continue

        if article:
            # the page's own <h1> duplicates the title we emit in the front matter
            first_h1 = article.find("h1")
            if first_h1:
                first_h1.decompose()
        body = drop_leading_title(html_to_markdown(article, url), title) if article else ""
        if args.images and article:
            for img in article.find_all("img", src=True):
                src = urljoin(url, img["src"])
                images[src] = _image_path(src)

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            f"# {title}\n\n"
            f"> Source: {url}\n"
            f"> Section: {section} | Semarchy xDM documentation (latest)\n\n"
            + body + "\n"
        )
        print(f"[{len(manifest)}] {path}  {len(body)} chars", flush=True)
        time.sleep(args.delay)

    # ------------------------------------------------------------- images
    if args.images and images:
        img_dir = docs / "_images"
        img_dir.mkdir(exist_ok=True)
        for i, (src, name) in enumerate(images.items(), 1):
            target = img_dir / name
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                r = session.get(src, timeout=30)
                r.raise_for_status()
                target.write_bytes(r.content)
            except Exception as exc:  # noqa: BLE001
                failures.append((src, str(exc)[:100]))
            if i % 25 == 0:
                print(f"  images {i}/{len(images)}", flush=True)
        print(f"images: {len(images)} -> {img_dir}")

    # ----------------------------------------------------------- manifest
    try:
        import yaml
        (docs / "index.yaml").write_text(yaml.dump(
            {"source": ORIGIN + PREFIX, "product": "Semarchy xDM", "version": "latest",
             "page_count": len(manifest), "pages": sorted(manifest, key=lambda p: p["file"])},
            sort_keys=False, allow_unicode=True, width=120))
    except ImportError:
        print("pyyaml missing - skipped docs/index.yaml")

    print(f"\npages: {len(manifest)}  failures: {len(failures)}")
    for path, err in failures[:10]:
        print(f"  FAIL {path}: {err}")


if __name__ == "__main__":
    main()
