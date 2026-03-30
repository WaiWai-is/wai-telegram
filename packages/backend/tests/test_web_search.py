"""Tests for web search module used by digital agents."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.web_search import _format_results, search_web


class TestFormatResults:
    def test_abstract_text(self):
        data = {
            "AbstractText": "Python is a programming language.",
            "AbstractSource": "Wikipedia",
            "AbstractURL": "https://en.wikipedia.org/wiki/Python",
        }
        result = _format_results("python", data)
        assert "Python is a programming language." in result
        assert "Wikipedia" in result
        assert "https://en.wikipedia.org/wiki/Python" in result

    def test_answer_field(self):
        data = {"Answer": "42"}
        result = _format_results("meaning of life", data)
        assert "42" in result
        assert "**Answer**" in result

    def test_related_topics(self):
        data = {
            "RelatedTopics": [
                {
                    "Text": "Bitcoin is a cryptocurrency",
                    "FirstURL": "https://example.com/btc",
                },
                {
                    "Text": "Ethereum is a blockchain",
                    "FirstURL": "https://example.com/eth",
                },
            ]
        }
        result = _format_results("crypto", data)
        assert "Bitcoin is a cryptocurrency" in result
        assert "Ethereum is a blockchain" in result
        assert "https://example.com/btc" in result

    def test_sub_topics(self):
        data = {
            "RelatedTopics": [
                {
                    "Topics": [
                        {
                            "Text": "Sub topic result",
                            "FirstURL": "https://example.com/sub",
                        }
                    ]
                }
            ]
        }
        result = _format_results("test", data)
        assert "Sub topic result" in result

    def test_definition(self):
        data = {"Definition": "A type of software."}
        result = _format_results("software", data)
        assert "A type of software." in result
        assert "**Definition**" in result

    def test_no_results(self):
        data = {}
        result = _format_results("xyzgarbage", data)
        assert "No results found for: xyzgarbage" in result

    def test_combined_fields(self):
        data = {
            "AbstractText": "Main summary.",
            "Answer": "Quick answer.",
            "Definition": "A definition.",
        }
        result = _format_results("test", data)
        assert "Main summary." in result
        assert "Quick answer." in result
        assert "A definition." in result

    def test_max_topics_capped(self):
        data = {
            "RelatedTopics": [
                {"Text": f"Result {i}", "FirstURL": f"https://example.com/{i}"}
                for i in range(20)
            ]
        }
        result = _format_results("many results", data)
        # Should cap at 8 topics, then at 10 lines total
        assert "Result 0" in result
        assert "Result 7" in result

    def test_empty_topic_text_skipped(self):
        data = {
            "RelatedTopics": [
                {"Text": "", "FirstURL": "https://example.com/empty"},
                {"Text": "Real result", "FirstURL": "https://example.com/real"},
            ]
        }
        result = _format_results("test", data)
        assert "Real result" in result
        assert "example.com/empty" not in result


class TestSearchWeb:
    @pytest.mark.asyncio
    async def test_search_web_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "AbstractText": "Test result about AI.",
            "AbstractSource": "Wikipedia",
            "AbstractURL": "https://en.wikipedia.org/wiki/AI",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client

        with patch(
            "app.services.agent.web_search.httpx.AsyncClient", return_value=mock_client
        ):
            result = await search_web("artificial intelligence")

        assert "Test result about AI." in result
        assert "Wikipedia" in result
        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args
        assert call_kwargs[1]["params"]["q"] == "artificial intelligence"

    @pytest.mark.asyncio
    async def test_search_web_http_error(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception(
            "503 Service Unavailable"
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client

        with patch(
            "app.services.agent.web_search.httpx.AsyncClient", return_value=mock_client
        ):
            with pytest.raises(Exception, match="503"):
                await search_web("test query")

    @pytest.mark.asyncio
    async def test_search_web_empty_results(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client

        with patch(
            "app.services.agent.web_search.httpx.AsyncClient", return_value=mock_client
        ):
            result = await search_web("xyzgarbage")

        assert "No results found" in result
