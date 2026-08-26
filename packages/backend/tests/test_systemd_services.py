from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[3]


def test_search_index_service_can_access_postgres_ssl_home_paths() -> None:
    service = REPOSITORY_ROOT.joinpath("systemd/wai-search-indexes.service").read_text()

    assert "ProtectHome=false" in service
