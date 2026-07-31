from __future__ import annotations

from htpy import Node, body, head, html, meta, script, title


def page(*, page_title: str, content: Node) -> Node:
    return html(lang="en")[
        head[
            meta(charset="utf-8"),
            title[page_title],
            script(src="/static/htmx.min.js"),
        ],
        body[content],
    ]
