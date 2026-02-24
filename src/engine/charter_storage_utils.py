"""Utilities for extracting and replacing sections in Confluence Charter XHTML.

The Charter page stores its content as a ``<table>`` inside an
``<ac:structured-macro ac:name="details">`` block.  Each ``<tr>`` contains
a ``<th>`` (section name) and ``<td>`` (section content).

Special case: **Project Scope** uses ``rowspan="2"`` — one ``<th>`` spanning
two rows, with the first ``<td>`` being "In Scope" and the second row
containing only a ``<td>`` for "Out of Scope".

This module provides:
- ``extract_sections`` — parse the XHTML into a list of ``{name, content}`` dicts
- ``replace_section_content`` — swap one section's ``<td>`` inner HTML
"""

from __future__ import annotations

import re
from html import escape as _html_escape


def _strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace to produce plain text."""
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", "", text)
    # Unescape common HTML entities
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    # Collapse whitespace but preserve newlines
    lines = text.split("\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in lines]
    return "\n".join(line for line in lines if line)


def _escape_html(text: str) -> str:
    """Escape text for safe inclusion in XHTML storage format."""
    return _html_escape(text, quote=True)


def extract_sections(storage_body: str) -> list[dict[str, str]]:
    """Parse ``<th>``/``<td>`` pairs from Charter XHTML.

    Returns a list of dicts with ``name`` (plain text header) and
    ``content`` (plain text from the ``<td>``).

    Handles ``rowspan`` for the Project Scope row by emitting two entries:
    "Project Scope — In Scope" and "Project Scope — Out of Scope".
    """
    sections: list[dict[str, str]] = []

    # Find all <tr> blocks
    tr_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
    th_pattern = re.compile(r"<th[^>]*>(.*?)</th>", re.DOTALL)
    td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
    rowspan_pattern = re.compile(r'rowspan="(\d+)"')

    rows = tr_pattern.findall(storage_body)
    skip_next_th = False  # True when we're in a rowspan continuation

    for row_html in rows:
        th_match = th_pattern.search(row_html)
        td_matches = td_pattern.findall(row_html)

        if skip_next_th:
            # This is a continuation row from a rowspan (e.g. Out of Scope)
            if td_matches:
                content = _strip_html(td_matches[0])
                sections.append({
                    "name": f"{rowspan_name} — Out of Scope",
                    "content": content,
                })
            skip_next_th = False
            continue

        if th_match is None:
            continue

        th_html = th_match.group(0)  # Full <th ...>...</th>
        th_inner = th_match.group(1)
        header_text = _strip_html(th_inner).rstrip(":")

        # Check for rowspan
        rowspan_match = rowspan_pattern.search(th_html)
        if rowspan_match and int(rowspan_match.group(1)) > 1:
            # Multi-row section (Project Scope)
            rowspan_name = header_text
            if td_matches:
                content = _strip_html(td_matches[0])
                sections.append({
                    "name": f"{header_text} — In Scope",
                    "content": content,
                })
            skip_next_th = True
            continue

        if td_matches:
            content = _strip_html(td_matches[0])
            sections.append({
                "name": header_text,
                "content": content,
            })

    return sections


def replace_section_content(
    storage_body: str, section_name: str, new_content: str,
    *, raw_xhtml: bool = False,
) -> str:
    """Replace the ``<td>`` content adjacent to the matching ``<th>`` section.

    Args:
        storage_body: The full Confluence storage-format XHTML body.
        section_name: The section name as returned by ``extract_sections``
            (e.g. ``"Commercial Objective"`` or ``"Project Scope — In Scope"``).
        new_content: Plain text to replace the section content with.
            Will be wrapped in ``<p>`` tags and HTML-escaped.
        raw_xhtml: If ``True``, insert *new_content* verbatim (caller
            provides valid XHTML).  Skips escaping and ``<p>`` wrapping.

    Returns:
        The modified storage body string.

    Raises:
        ValueError: If the section name is not found in the Charter.
    """
    if raw_xhtml:
        new_html = new_content
    else:
        escaped_content = _escape_html(new_content)
        # Wrap each line in a <p> tag
        lines = escaped_content.split("\n")
        new_html = "".join(f"<p>{line}</p>" for line in lines if line.strip())
        if not new_html:
            new_html = f"<p>{escaped_content}</p>"

    # Handle "Section — In Scope" / "Section — Out of Scope" sub-sections
    is_in_scope = section_name.endswith("— In Scope")
    is_out_scope = section_name.endswith("— Out of Scope")

    if is_in_scope or is_out_scope:
        base_name = section_name.rsplit("—", 1)[0].strip()
        return _replace_rowspan_section(
            storage_body, base_name, new_html, is_out_scope
        )

    return _replace_simple_section(storage_body, section_name, new_html)


def _replace_simple_section(
    storage_body: str, section_name: str, new_td_html: str
) -> str:
    """Replace <td> content in a regular (non-rowspan) row."""
    # Find the <tr> that contains a <th> matching section_name
    tr_pattern = re.compile(r"(<tr[^>]*>)(.*?)(</tr>)", re.DOTALL)
    found = False

    def _replace_in_tr(match: re.Match) -> str:
        nonlocal found
        tr_open, tr_body, tr_close = match.group(1), match.group(2), match.group(3)
        th_match = re.search(r"<th[^>]*>(.*?)</th>", tr_body, re.DOTALL)
        if th_match is None:
            return match.group(0)

        header = _strip_html(th_match.group(1)).rstrip(":")
        if header != section_name:
            return match.group(0)

        # Check this isn't a rowspan row
        if re.search(r'rowspan="[2-9]"', th_match.group(0)):
            return match.group(0)

        # Replace the <td> inner content
        td_match = re.search(r"(<td[^>]*>)(.*?)(</td>)", tr_body, re.DOTALL)
        if td_match is None:
            return match.group(0)

        found = True
        new_tr_body = (
            tr_body[: td_match.start(2)]
            + new_td_html
            + tr_body[td_match.end(2):]
        )
        return tr_open + new_tr_body + tr_close

    result = tr_pattern.sub(_replace_in_tr, storage_body)
    if not found:
        raise ValueError(f"Charter section not found: '{section_name}'")
    return result


def _replace_rowspan_section(
    storage_body: str,
    base_name: str,
    new_td_html: str,
    is_out_scope: bool,
) -> str:
    """Replace <td> in a rowspan row (In Scope = first td, Out of Scope = next row's td)."""
    tr_pattern = re.compile(r"(<tr[^>]*>)(.*?)(</tr>)", re.DOTALL)
    matches = list(tr_pattern.finditer(storage_body))

    found = False
    result = storage_body

    for i, match in enumerate(matches):
        tr_body = match.group(2)
        th_match = re.search(r"<th[^>]*>(.*?)</th>", tr_body, re.DOTALL)
        if th_match is None:
            continue

        header = _strip_html(th_match.group(1)).rstrip(":")
        if header != base_name:
            continue

        if not re.search(r'rowspan="[2-9]"', th_match.group(0)):
            continue

        if is_out_scope:
            # Replace in the NEXT row
            if i + 1 >= len(matches):
                break
            next_match = matches[i + 1]
            next_body = next_match.group(2)
            td_match = re.search(r"(<td[^>]*>)(.*?)(</td>)", next_body, re.DOTALL)
            if td_match:
                new_next_body = (
                    next_body[: td_match.start(2)]
                    + new_td_html
                    + next_body[td_match.end(2):]
                )
                result = (
                    result[: next_match.start(2)]
                    + new_next_body
                    + result[next_match.end(2):]
                )
                found = True
        else:
            # Replace the first <td> in this row
            td_match = re.search(r"(<td[^>]*>)(.*?)(</td>)", tr_body, re.DOTALL)
            if td_match:
                new_tr_body = (
                    tr_body[: td_match.start(2)]
                    + new_td_html
                    + tr_body[td_match.end(2):]
                )
                result = (
                    result[: match.start(2)]
                    + new_tr_body
                    + result[match.end(2):]
                )
                found = True
        break

    if not found:
        raise ValueError(f"Charter section not found: '{base_name}'")
    return result
