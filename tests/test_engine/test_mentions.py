"""Tests for the mention resolver — regex, XHTML, ADF, caching, graceful degradation."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.engine.mentions import (
    MENTION_RE,
    PAGE_LINK_RE,
    resolve_adf_doc_mentions,
    resolve_adf_mentions,
    resolve_confluence_mentions,
    resolve_confluence_page_links,
    search_user,
)


# ---------------------------------------------------------------------------
# Regex tests
# ---------------------------------------------------------------------------


class TestMentionRegex:

    @pytest.mark.parametrize("text,expected", [
        ("@Tom Renneberg", ["Tom Renneberg"]),
        ("@Alice Smith-Jones", ["Alice Smith-Jones"]),
        ("@Tom Renneberg should review", ["Tom Renneberg"]),
        ("Ask @Alice Smith and @Bob Jones", ["Alice Smith", "Bob Jones"]),
        ("@lowercase name", []),  # lowercase first word — no match
        ("@Tom", ["Tom"]),  # single capitalised word is now allowed
        ("@Tom is tall", ["Tom"]),  # stops at lowercase word
        ("tom@example.com", []),  # email address
        ("@Tom O'Brien", ["Tom O'Brien"]),  # apostrophe
        # Lowercase surname particles are preserved between capital words
        ("@John van der Berg", ["John van der Berg"]),
        ("@María de la Cruz", ["María de la Cruz"]),
        ("@Jean-Claude Van Damme", ["Jean-Claude Van Damme"]),
    ])
    def test_mention_regex_matches(self, text, expected):
        matches = [m.group(1) for m in MENTION_RE.finditer(text)]
        assert matches == expected

    def test_mention_regex_no_match_in_email(self):
        assert MENTION_RE.findall("contact tom@renneberg.com") == []


# ---------------------------------------------------------------------------
# search_user
# ---------------------------------------------------------------------------


class TestSearchUser:

    async def test_returns_account_id_on_match(self):
        jira = AsyncMock()
        jira.search_users = AsyncMock(return_value=[
            {"accountId": "abc123", "displayName": "Tom Renneberg"},
        ])

        with patch("src.engine.mentions.cache") as mock_cache:
            mock_cache.get.return_value = None
            result = await search_user("Tom Renneberg", jira)

        assert result == "abc123"
        mock_cache.set.assert_called_once()

    async def test_returns_none_when_no_results(self):
        jira = AsyncMock()
        jira.search_users = AsyncMock(return_value=[])

        with patch("src.engine.mentions.cache") as mock_cache:
            mock_cache.get.return_value = None
            result = await search_user("Nobody Known", jira)

        assert result is None
        # Should cache empty string for miss
        mock_cache.set.assert_called_once()
        args = mock_cache.set.call_args
        assert args[0][1] == ""  # empty string = known miss

    async def test_uses_cache_hit(self):
        jira = AsyncMock()

        with patch("src.engine.mentions.cache") as mock_cache:
            mock_cache.get.return_value = "cached-id"
            result = await search_user("Tom Renneberg", jira)

        assert result == "cached-id"
        jira.search_users.assert_not_called()

    async def test_uses_cache_miss(self):
        jira = AsyncMock()

        with patch("src.engine.mentions.cache") as mock_cache:
            mock_cache.get.return_value = ""  # known miss
            result = await search_user("Unknown Person", jira)

        assert result is None
        jira.search_users.assert_not_called()

    async def test_graceful_on_connector_error(self):
        from src.connectors.base import ConnectorError

        jira = AsyncMock()
        jira.search_users = AsyncMock(side_effect=ConnectorError(500, "Server error"))

        with patch("src.engine.mentions.cache") as mock_cache:
            mock_cache.get.return_value = None
            result = await search_user("Tom Renneberg", jira)

        assert result is None


# ---------------------------------------------------------------------------
# resolve_confluence_mentions
# ---------------------------------------------------------------------------


class TestResolveConfluenceMentions:

    async def test_replaces_mention_with_xhtml(self):
        jira = AsyncMock()
        jira.search_users = AsyncMock(return_value=[
            {"accountId": "abc123", "displayName": "Tom Renneberg"},
        ])

        with patch("src.engine.mentions.cache") as mock_cache:
            mock_cache.get.return_value = None
            result = await resolve_confluence_mentions(
                "Ask @Tom Renneberg to review", jira
            )

        assert '<ac:link><ri:user ri:account-id="abc123"/></ac:link>' in result
        assert "@Tom Renneberg" not in result
        assert "Ask " in result
        assert " to review" in result

    async def test_leaves_unresolved_as_plain_text(self):
        jira = AsyncMock()
        jira.search_users = AsyncMock(return_value=[])

        with patch("src.engine.mentions.cache") as mock_cache:
            mock_cache.get.return_value = None
            result = await resolve_confluence_mentions(
                "Ask @Unknown Person to review", jira
            )

        assert "@Unknown Person" in result

    async def test_no_mentions_returns_unchanged(self):
        jira = AsyncMock()

        result = await resolve_confluence_mentions("No mentions here", jira)

        assert result == "No mentions here"
        jira.search_users.assert_not_called()

    async def test_multiple_mentions(self):
        jira = AsyncMock()

        async def _mock_search(query, max_results=5):
            users = {
                "Alice Smith": [{"accountId": "a1", "displayName": "Alice Smith"}],
                "Bob Jones": [{"accountId": "b2", "displayName": "Bob Jones"}],
            }
            return users.get(query, [])

        jira.search_users = _mock_search

        with patch("src.engine.mentions.cache") as mock_cache:
            mock_cache.get.return_value = None
            result = await resolve_confluence_mentions(
                "@Alice Smith and @Bob Jones discussed", jira
            )

        assert 'ri:account-id="a1"' in result
        assert 'ri:account-id="b2"' in result


# ---------------------------------------------------------------------------
# resolve_adf_mentions
# ---------------------------------------------------------------------------


class TestResolveAdfMentions:

    async def test_splits_into_text_and_mention_nodes(self):
        jira = AsyncMock()
        jira.search_users = AsyncMock(return_value=[
            {"accountId": "abc123", "displayName": "Tom Renneberg"},
        ])

        with patch("src.engine.mentions.cache") as mock_cache:
            mock_cache.get.return_value = None
            nodes = await resolve_adf_mentions(
                "Ask @Tom Renneberg to review", jira
            )

        assert len(nodes) == 3
        assert nodes[0] == {"type": "text", "text": "Ask "}
        assert nodes[1]["type"] == "mention"
        assert nodes[1]["attrs"]["id"] == "abc123"
        assert nodes[1]["attrs"]["text"] == "@Tom Renneberg"
        assert nodes[2] == {"type": "text", "text": " to review"}

    async def test_no_mentions_returns_single_text_node(self):
        jira = AsyncMock()

        nodes = await resolve_adf_mentions("Just plain text", jira)

        assert nodes == [{"type": "text", "text": "Just plain text"}]

    async def test_unresolved_returns_plain_text(self):
        jira = AsyncMock()
        jira.search_users = AsyncMock(return_value=[])

        with patch("src.engine.mentions.cache") as mock_cache:
            mock_cache.get.return_value = None
            nodes = await resolve_adf_mentions(
                "Ask @Unknown Person about it", jira
            )

        assert nodes == [{"type": "text", "text": "Ask @Unknown Person about it"}]


# ---------------------------------------------------------------------------
# resolve_adf_doc_mentions
# ---------------------------------------------------------------------------


class TestResolveAdfDocMentions:

    async def test_resolves_mentions_in_paragraph(self):
        jira = AsyncMock()
        jira.search_users = AsyncMock(return_value=[
            {"accountId": "xyz789", "displayName": "Sarah Lee"},
        ])

        adf_doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "@Sarah Lee raised this concern."},
                    ],
                },
            ],
        }

        with patch("src.engine.mentions.cache") as mock_cache:
            mock_cache.get.return_value = None
            result = await resolve_adf_doc_mentions(adf_doc, jira)

        para = result["content"][0]
        assert len(para["content"]) == 2
        assert para["content"][0]["type"] == "mention"
        assert para["content"][0]["attrs"]["id"] == "xyz789"
        assert para["content"][1]["type"] == "text"
        assert para["content"][1]["text"] == " raised this concern."

    async def test_preserves_marks_on_resolved_text(self):
        jira = AsyncMock()
        jira.search_users = AsyncMock(return_value=[
            {"accountId": "abc", "displayName": "Tom Renneberg"},
        ])

        adf_doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Background by @Tom Renneberg here",
                            "marks": [{"type": "strong"}],
                        },
                    ],
                },
            ],
        }

        with patch("src.engine.mentions.cache") as mock_cache:
            mock_cache.get.return_value = None
            result = await resolve_adf_doc_mentions(adf_doc, jira)

        para = result["content"][0]
        # First node is text with marks, second is mention, third is text with marks
        text_nodes = [n for n in para["content"] if n["type"] == "text"]
        for tn in text_nodes:
            assert tn.get("marks") == [{"type": "strong"}]

    async def test_empty_doc_returns_unchanged(self):
        jira = AsyncMock()
        result = await resolve_adf_doc_mentions({}, jira)
        assert result == {}

    async def test_non_doc_returns_unchanged(self):
        jira = AsyncMock()
        result = await resolve_adf_doc_mentions({"type": "panel"}, jira)
        assert result == {"type": "panel"}

    async def test_skips_non_text_nodes(self):
        jira = AsyncMock()

        adf_doc = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "No mentions here."},
                        {"type": "hardBreak"},
                    ],
                },
                {"type": "rule"},
            ],
        }

        result = await resolve_adf_doc_mentions(adf_doc, jira)

        # Structure preserved, no changes
        assert len(result["content"]) == 2
        assert result["content"][0]["content"][0]["text"] == "No mentions here."
        assert result["content"][0]["content"][1]["type"] == "hardBreak"
        assert result["content"][1]["type"] == "rule"


# ---------------------------------------------------------------------------
# resolve_confluence_page_links
# ---------------------------------------------------------------------------


class TestPageLinkRegex:

    @pytest.mark.parametrize("text,expected", [
        ("See [page: Stakeholder Roster] for details", ["Stakeholder Roster"]),
        ("Refer to [page:Scope Doc] and [page: Architecture]", ["Scope Doc", "Architecture"]),
        ("[page:   Trimmed  ]", ["Trimmed"]),
        ("no placeholders here", []),
        ("[Page: wrong case]", []),  # case-sensitive prefix
        ("[page: spans\nnewline]", []),  # single-line only
    ])
    def test_page_link_regex_matches(self, text, expected):
        matches = [m.group(1).strip() for m in PAGE_LINK_RE.finditer(text)]
        assert matches == expected


class TestResolveConfluencePageLinks:

    async def test_replaces_placeholder_with_page_link_xhtml(self):
        confluence = AsyncMock()
        confluence.search_pages_by_title = AsyncMock(return_value=[
            {"id": "123", "title": "Stakeholder Roster"},
        ])

        result = await resolve_confluence_page_links(
            "See [page: Stakeholder Roster] for details", confluence,
        )

        assert (
            '<ac:link><ri:page ri:content-title="Stakeholder Roster"/></ac:link>'
            in result
        )
        assert "[page:" not in result
        assert "See " in result
        assert " for details" in result

    async def test_leaves_unresolved_placeholders_as_is(self):
        confluence = AsyncMock()
        confluence.search_pages_by_title = AsyncMock(return_value=[])

        original = "See [page: Nonexistent Page] for details"
        result = await resolve_confluence_page_links(original, confluence)

        assert result == original

    async def test_case_insensitive_exact_title_match_only(self):
        """Partial matches should be rejected — only exact (case-insensitive) titles resolve."""
        confluence = AsyncMock()
        confluence.search_pages_by_title = AsyncMock(return_value=[
            {"id": "123", "title": "Stakeholder Roster and Governance"},  # partial
        ])

        result = await resolve_confluence_page_links(
            "[page: Stakeholder Roster]", confluence,
        )
        # Not an exact match → left unresolved
        assert result == "[page: Stakeholder Roster]"

    async def test_escapes_attribute_special_chars_in_title(self):
        confluence = AsyncMock()
        confluence.search_pages_by_title = AsyncMock(return_value=[
            {"id": "123", "title": 'Ideas "v2" & Roadmap'},
        ])

        result = await resolve_confluence_page_links(
            '[page: Ideas "v2" & Roadmap]', confluence,
        )

        # Quotes and ampersands must be XML-attribute-escaped
        assert 'ri:content-title="Ideas &quot;v2&quot; &amp; Roadmap"' in result

    async def test_graceful_on_search_error(self):
        confluence = AsyncMock()
        confluence.search_pages_by_title = AsyncMock(side_effect=Exception("boom"))

        original = "See [page: Some Page] for details"
        result = await resolve_confluence_page_links(original, confluence)

        assert result == original

    async def test_no_placeholders_returns_unchanged(self):
        confluence = AsyncMock()
        result = await resolve_confluence_page_links("plain text only", confluence)
        assert result == "plain text only"
        confluence.search_pages_by_title.assert_not_called()
