"""No untrusted CSS, scripts, SVG, URLs or attributes survive publication."""

import html
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit
import bleach
from bs4 import BeautifulSoup
from PIL import Image

TAGS = set(
    "p div span h1 h2 h3 h4 h5 h6 a img figure figcaption table thead tbody tfoot tr th td caption "
    "ul ol li dl dt dd blockquote pre code b strong i em u s sup sub br hr math mrow mi mn mo "
    "mfrac msqrt mroot msup msub msubsup munder mover munderover mtable mtr mtd mtext semantics "
    "annotation menclose mstyle mpadded mspace".split()
)
ATTRS = {
    "*": ["id"],
    "a": ["href", "title"],
    "img": ["src", "alt"],
    "math": ["display"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
    "annotation": ["encoding"],
}


def publish_html(raw_file: Path, destination: Path, paper_id: str):
    if raw_file.stat().st_size > 20_000_000:
        raise ValueError("HTML output too large")
    soup = BeautifulSoup(raw_file.read_text(encoding="utf-8"), "html.parser")
    for tag in soup.find_all(["script", "style", "iframe", "object", "embed", "form", "svg", "meta", "link"]):
        tag.decompose()
    destination.mkdir(parents=True, exist_ok=True)
    assets = {}
    for image in soup.find_all("img"):
        src = unquote(image.get("src", ""))
        if urlsplit(src).scheme or src.startswith(("/", "\\")) or "\\" in src:
            image.decompose()
            continue
        file = (raw_file.parent / src).resolve()
        if (
            not file.is_relative_to(raw_file.parent.resolve())
            or not file.is_file()
            or file.stat().st_size > 30_000_000
        ):
            raise ValueError("Missing or unsafe image resource")
        name = f"asset-{len(assets)}.png"
        with Image.open(file) as decoded:
            if decoded.width * decoded.height > 40_000_000:
                raise ValueError("Image dimensions too large")
            decoded.convert("RGBA").save(destination / name, "PNG")
        assets[name] = name
        image["src"] = f"/paper-assets/{paper_id}/{name}"
    for anchor in soup.find_all("a"):
        href = anchor.get("href", "")
        if not href.startswith("#"):
            anchor.attrs.pop("href", None)
    body = str(soup.body or soup)
    clean = bleach.clean(body, tags=TAGS, attributes=ATTRS, protocols=["https", "http"], strip=True)
    soup = BeautifulSoup(clean, "html.parser")
    toc = []
    for index, heading in enumerate(soup.find_all(["h1", "h2", "h3", "h4"])):
        heading["id"] = f"section-{index}"
        toc.append({"id": heading["id"], "title": heading.get_text(" ", strip=True)[:200]})
    for node in soup.find_all(["math", "code", "pre"]):
        node["translate"] = "no"
        node["class"] = "notranslate"
    if len(soup.get_text(strip=True)) < 20:
        raise ValueError("No readable article text")
    (destination / "article.html").write_text(str(soup), encoding="utf-8")
    (destination / "manifest.json").write_text(json.dumps({"assets": assets, "toc": toc}), encoding="utf-8")
    return len(assets)


def reader_document(paper, article, manifest, settings):
    title = html.escape(paper.title)
    toc = "".join(
        f'<a href="#{html.escape(item["id"])}">{html.escape(item["title"])}</a>' for item in manifest["toc"]
    )
    width = int(settings.get("reader_width", 780))
    size = int(settings.get("font_scale", 17))
    theme = html.escape(settings.get("theme", "system"))
    return f'''<!doctype html><html lang="en" data-theme="{theme}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · PaperFlow</title>
<link rel="stylesheet" href="/reader-static/reader.css"><link rel="stylesheet" href="/reader-static/katex.min.css">
<script defer src="/reader-static/katex.min.js"></script><script defer src="/reader-static/reader.js"></script>
</head><body data-paper="{paper.id}" data-width="{width}" data-size="{size}">
<header translate="no"><a href="/">← Library</a><span>{title}</span><a href="/papers/{paper.id}/pdf">Original PDF</a>
<button id="help">Read Frog 翻译帮助</button><button id="theme">明 / 暗</button>
<label>字号 <input id="font" type="range" min="14" max="24" value="{size}"></label>
<label>宽度 <input id="width" type="range" min="600" max="1000" value="{width}"></label></header>
<aside translate="no">{toc}</aside><main><article>{article}</article></main>
<dialog id="translation-help" translate="no"><h2>使用 Read Frog 双语阅读</h2>
<p>在 Chrome 的 Read Frog 扩展中选择你已配置的 DeepSeek，然后使用扩展的翻译页面或段落翻译按钮。</p>
<p>PaperFlow 不读取插件密钥，也不保存插件译文。翻译会向所选服务发送正文并可能产生费用。</p>
<p>若扩展没出现，请检查此站点权限并刷新。公式和导航已标记禁翻；翻译效果仍需人工确认。</p>
<a href="https://www.readfrog.app/en/docs/local-files" target="_blank" rel="noopener noreferrer">官方 localhost 指南</a>
<button id="close-help">关闭</button></dialog></body></html>'''
