"""Mention resolver — convert @Name references to Atlassian mention markup.

Users type ``@FirstName LastName`` in their input. The LLM preserves
the ``@`` markers. This module resolves names to Atlassian account IDs
and replaces them with native Confluence XHTML or Jira ADF mention nodes.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.cache import cache
from src.connectors.base import ConnectorError

logger = logging.getLogger(__name__)

# Lowercase surname particles allowed between/before capitalised name words.
# e.g. "van", "der", "de", "la"  →  "@John van der Berg", "@María de la Cruz"
_PARTICLES = (
    "van", "der", "den", "de", "la", "le", "du", "del", "dela", "von",
    "bin", "al", "el", "da", "do", "dos", "das", "di", "ten", "ter",
    "of", "auf", "zu",
)
_PARTICLE_ALT = "|".join(_PARTICLES)

# Matches ``@Name`` patterns. Supports:
#   - single capitalised word       (e.g. @Madonna)
#   - two or more capitalised words  (e.g. @Tom Renneberg, @Alice Smith-Jones)
#   - lowercase surname particles between capitalised words (e.g. @John van der Berg)
# Particles only match when followed by further name content, so prose like
# "@Today is Monday" will at most match "Today" (single word).
# ``_L`` = any Unicode letter (via "non-word OR digit OR underscore" negation).
# Names can include apostrophes and hyphens. First letter must be a capital.
_L = r"[^\W\d_]"
_UPPER = r"[A-Z\u00C0-\u00DE]"  # Latin-1 uppercase incl. accented À-Þ
MENTION_RE = re.compile(
    r"""
    @(                                              # group 1: the display name (no @)
      """ + _UPPER + _L + r"""*['\-]?""" + _L + r"""*   #   first word, starts capital
      (?:
        \s+
        (?:(?:""" + _PARTICLE_ALT + r""")\s+)*      #   optional lowercase particles
        """ + _UPPER + _L + r"""*['\-]?""" + _L + r"""* #   another capital word
      )*                                            #   zero or more continuations
    )
    """,
    re.VERBOSE | re.UNICODE,
)

_CACHE_PREFIX = "user_mention:"
_HIT_TTL = 3600   # 1 hour for found users
_MISS_TTL = 300   # 5 minutes for not-found (retry sooner)


async def search_user(name: str, jira: Any) -> str | None:
    """Look up an Atlassian account ID by display name.

    Uses the module-level TTL cache. Returns the account ID string,
    or ``None`` if no match was found.
    """
    cache_key = f"{_CACHE_PREFIX}{name.lower()}"
    cached = cache.get(cache_key)
    if cached is not None:
        # Empty string means "known miss"
        return cached if cached != "" else None

    try:
        results = await jira.search_users(name, max_results=5)
    except ConnectorError:
        logger.warning("User search failed for '%s'", name)
        return None

    if results:
        account_id = results[0].get("accountId", "")
        if account_id:
            cache.set(cache_key, account_id, ttl=_HIT_TTL)
            return account_id

    # Cache miss so we don't re-query immediately
    cache.set(cache_key, "", ttl=_MISS_TTL)
    return None


# Matches ``[page: Page Title]`` placeholders produced by charter section
# extraction. The LLM may echo these back when referencing other Confluence pages.
PAGE_LINK_RE = re.compile(r"\[page:\s*([^\]\n]+?)\s*\]")

# Simple HTML-attribute escaper (we build attributes, not HTML text).
def _attr_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


async def resolve_confluence_page_links(text: str, confluence: Any) -> str:
    """Replace ``[page: Title]`` placeholders with Confluence XHTML page links.

    For each placeholder, searches Confluence for a page with a matching title
    (case-insensitive exact match on the top result). If found, replaces with:

        <ac:link><ri:page ri:content-title="Title"/></ac:link>

    Unresolved titles are left as-is so the user can see the broken reference.
    """
    matches = list(PAGE_LINK_RE.finditer(text))
    if not matches:
        return text

    unique_titles = {m.group(1).strip() for m in matches}
    resolved: dict[str, str] = {}
    for title in unique_titles:
        try:
            results = await confluence.search_pages_by_title(title, max_results=3)
        except Exception as exc:
            logger.warning("Page link search failed for %r: %s", title, exc)
            continue
        for r in results:
            if r.get("title", "").lower() == title.lower():
                resolved[title] = r["title"]
                break

    if not resolved:
        return text

    # Replace right-to-left to preserve offsets
    result = text
    for m in reversed(matches):
        title = m.group(1).strip()
        if title in resolved:
            markup = (
                f'<ac:link><ri:page ri:content-title="{_attr_escape(resolved[title])}"/>'
                f'</ac:link>'
            )
            result = result[:m.start()] + markup + result[m.end():]

    return result


async def resolve_confluence_mentions(text: str, jira: Any) -> str:
    """Replace ``@Name`` patterns with Confluence XHTML mention markup.

    Unresolved names are left as plain text.
    """
    matches = list(MENTION_RE.finditer(text))
    if not matches:
        return text

    # Resolve all unique names
    unique_names = {m.group(1) for m in matches}
    resolved: dict[str, str] = {}
    for name in unique_names:
        account_id = await search_user(name, jira)
        if account_id:
            resolved[name] = account_id

    if not resolved:
        return text

    # Replace from right to left to preserve offsets
    result = text
    for m in reversed(matches):
        name = m.group(1)
        if name in resolved:
            markup = (
                f'<ac:link><ri:user ri:account-id="{resolved[name]}"/></ac:link>'
            )
            result = result[:m.start()] + markup + result[m.end():]

    return result


async def resolve_adf_mentions(text: str, jira: Any) -> list[dict[str, Any]]:
    """Split text into ADF inline nodes with mention nodes for @Name patterns.

    Returns a list of ADF inline content nodes (text + mention interleaved).
    """
    matches = list(MENTION_RE.finditer(text))
    if not matches:
        return [{"type": "text", "text": text}]

    # Resolve all unique names
    unique_names = {m.group(1) for m in matches}
    resolved: dict[str, str] = {}
    for name in unique_names:
        account_id = await search_user(name, jira)
        if account_id:
            resolved[name] = account_id

    if not resolved:
        return [{"type": "text", "text": text}]

    # Build inline nodes
    nodes: list[dict[str, Any]] = []
    last_end = 0

    for m in matches:
        name = m.group(1)
        if name not in resolved:
            continue

        # Text before the mention
        if m.start() > last_end:
            nodes.append({"type": "text", "text": text[last_end:m.start()]})

        # Mention node
        nodes.append({
            "type": "mention",
            "attrs": {
                "id": resolved[name],
                "text": f"@{name}",
            },
        })
        last_end = m.end()

    # Remaining text after last mention
    if last_end < len(text):
        nodes.append({"type": "text", "text": text[last_end:]})

    # If no nodes were generated (all names unresolved), return plain text
    return nodes if nodes else [{"type": "text", "text": text}]


async def resolve_adf_doc_mentions(adf_doc: dict[str, Any], jira: Any) -> dict[str, Any]:
    """Walk an ADF document tree, resolving @mentions in all text nodes.

    Returns a new ADF document with mention nodes inserted where appropriate.
    """
    if not adf_doc or adf_doc.get("type") != "doc":
        return adf_doc

    new_content = []
    for block in adf_doc.get("content", []):
        new_content.append(await _resolve_block(block, jira))

    return {**adf_doc, "content": new_content}


async def _resolve_block(block: dict[str, Any], jira: Any) -> dict[str, Any]:
    """Recursively resolve mentions in a single ADF block node."""
    block_type = block.get("type", "")

    # Paragraph / heading — has inline content
    if block_type in ("paragraph", "heading"):
        inline_content = block.get("content", [])
        new_inline: list[dict[str, Any]] = []
        for node in inline_content:
            if node.get("type") == "text":
                text = node.get("text", "")
                if MENTION_RE.search(text):
                    resolved_nodes = await resolve_adf_mentions(text, jira)
                    # Preserve marks (bold, etc.) on text nodes
                    marks = node.get("marks")
                    for rn in resolved_nodes:
                        if rn["type"] == "text" and marks:
                            rn = {**rn, "marks": marks}
                        new_inline.append(rn)
                else:
                    new_inline.append(node)
            else:
                new_inline.append(node)
        return {**block, "content": new_inline}

    # Other block types with nested content (e.g. bulletList, listItem)
    if "content" in block:
        new_content = []
        for child in block["content"]:
            new_content.append(await _resolve_block(child, jira))
        return {**block, "content": new_content}

    return block
