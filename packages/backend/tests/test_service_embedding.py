from unittest.mock import AsyncMock, MagicMock, patch

from app.services.embedding_service import generate_embeddings, generate_query_embedding


class TestGenerateEmbeddings:
    async def test_empty_input(self):
        result = await generate_embeddings([])
        assert result == []

    async def test_calls_openai(self):
        mock_item1 = MagicMock()
        mock_item1.embedding = [0.1, 0.2, 0.3]
        mock_item2 = MagicMock()
        mock_item2.embedding = [0.4, 0.5, 0.6]

        mock_response = MagicMock()
        mock_response.data = [mock_item1, mock_item2]

        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        with patch(
            "app.services.embedding_service.get_openai_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            result = await generate_embeddings(["hello", "world"])
            assert len(result) == 2
            assert result[0] == [0.1, 0.2, 0.3]
            assert result[1] == [0.4, 0.5, 0.6]


class TestGenerateQueryEmbedding:
    async def test_generates_single_embedding(self):
        with patch(
            "app.services.embedding_service.generate_embeddings",
            new_callable=AsyncMock,
            return_value=[[0.1, 0.2, 0.3]],
        ):
            result = await generate_query_embedding("test query")
            assert result == [0.1, 0.2, 0.3]

    async def test_empty_result(self):
        with patch(
            "app.services.embedding_service.generate_embeddings",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await generate_query_embedding("test query")
            assert result == []
