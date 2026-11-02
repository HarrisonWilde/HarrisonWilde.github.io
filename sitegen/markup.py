"""Markdown with the Obsidian syntax used in the archive.

- %% comments %% are private: removed from the public build, shown as notes in the private one.
- [[Note]] / [[Note|text]] link to another entry when it's visible in this build, else plain text.
- ![[image.jpg]] embeds an image when the caller allows it, else disappears.
- ==highlight== becomes <mark>.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import PurePosixPath

import markdown

BLOCK_COMMENT = re.compile(r"(?ms)^[ \t]*%%[ \t]*\r?\n(.*?)\r?\n[ \t]*%%[ \t]*$")
LINE_COMMENT = re.compile(r"(?m)^[ \t]*%%(.+?)%%[ \t]*$")
INLINE_COMMENT = re.compile(r"%%(.+?)%%", re.S)
EMBED = re.compile(r"!\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#([^\]|]*))?(?:\|([^\]]*))?\]\]")
HIGHLIGHT = re.compile(r"==(?=\S)(.+?)(?<=\S)==")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg"}
EXTENSIONS = ["extra", "smarty", "sane_lists"]
# U+FE0E keeps the footnote back-arrow from turning into an emoji on Apple devices.
EXTENSION_CONFIGS = {"extra": {"footnotes": {"BACKLINK_TEXT": "&#8617;&#xFE0E;"}}}


def strip_private(text: str) -> str:
    text = BLOCK_COMMENT.sub("", text)
    text = INLINE_COMMENT.sub("", text)
    return text.replace("%%", "")  # an unclosed marker hides nothing, but leaves no trace


def is_image(name: str) -> bool:
    return PurePosixPath(name).suffix.lower() in IMAGE_SUFFIXES


class Renderer:
    def __init__(
        self,
        private: bool,
        resolve_note: Callable[[str], str | None],
        resolve_image: Callable[[str], str | None],
    ):
        self.private = private
        self.resolve_note = resolve_note
        self.resolve_image = resolve_image

    def __call__(self, text: str, images: bool = True) -> str:
        if self.private:
            text = BLOCK_COMMENT.sub(
                lambda m: f'\n<div class="private-note" markdown="1">\n\n{m.group(1)}\n\n</div>\n', text
            )
            text = LINE_COMMENT.sub(lambda m: f'\n<div class="private-note" markdown="1">\n\n{m.group(1).strip()}\n\n</div>\n', text)
            text = INLINE_COMMENT.sub(lambda m: f'<span class="private-note">{m.group(1)}</span>', text)
        else:
            text = strip_private(text)
        text = EMBED.sub(lambda m: self._embed(m, images), text)
        text = WIKILINK.sub(self._link, text)
        text = HIGHLIGHT.sub(r"<mark>\1</mark>", text)
        return markdown.markdown(text, extensions=EXTENSIONS, extension_configs=EXTENSION_CONFIGS, output_format="html")

    def inline(self, text: str) -> str:
        """Render a one-line snippet without the wrapping <p>."""
        html = self(text, images=False).strip()
        if html.startswith("<p>") and html.endswith("</p>") and html.count("<p>") == 1:
            html = html[3:-4]
        return html

    def _embed(self, m: re.Match, images: bool) -> str:
        target, option = m.group(1).strip(), (m.group(2) or "").strip()
        if not is_image(target):
            return self._link(m)  # embedded notes become links
        url = self.resolve_image(target) if images else None
        if not url:
            return ""
        width = f' width="{option}"' if option.isdigit() else ""
        alt = "" if option.isdigit() else option
        return f'<img src="{url}" alt="{alt}" loading="lazy"{width}>'

    def _link(self, m: re.Match) -> str:
        target, alias = m.group(1).strip(), m.group(3)
        text = (alias or target).strip()
        url = self.resolve_note(target)
        return f"[{text}]({url})" if url else text
