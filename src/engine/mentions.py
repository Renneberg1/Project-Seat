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

# Matches 2+ capitalized words after @
# e.g. @Tom Renneberg, @Alice Smith-Jones
MENTION_RE = re.compile(r"@([A-Z][a-zA-Z'-]+(?: [A-Z][a-zA-Z'-]+)+)")

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
