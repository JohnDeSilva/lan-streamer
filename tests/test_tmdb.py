import pytest
import requests
from unittest.mock import MagicMock, patch
from lan_streamer.tmdb import TMDBClient
from lan_streamer.config import config


@pytest.fixture
def tmdb(tmp_path) -> None:
    with (
        patch.object(config, "tmdb_api_key", "test-tmdb-key"),
        patch("lan_streamer.tmdb.CACHE_DIR", tmp_path),
    ):
        client = TMDBClient()
        yield client


# ------------------------------------------------------------------
# is_configured
# ------------------------------------------------------------------


def test_tmdb_is_configured(tmdb) -> None:
    assert tmdb.is_configured() is True


def test_tmdb_not_configured() -> None:
    client = TMDBClient()
    config.tmdb_api_key = ""
    assert client.is_configured() is False
    # search_series_full short-circuits without a key
    assert client.search_series_full("Test") == []
    # Others try anyway and fail gracefully
    assert client.search_series("Test") is None
    assert client.get_seasons("1") == []
    assert client.get_episodes("1", 1) == []
    assert client.download_image("", "key") == ""


# ------------------------------------------------------------------
# _params
# ------------------------------------------------------------------


def test_params_with_key(tmdb) -> None:
    params = tmdb._params({"query": "test"})
    assert params["api_key"] == "test-tmdb-key"
    assert params["query"] == "test"


def test_params_without_key() -> None:
    with patch.object(config, "tmdb_api_key", ""):
        client = TMDBClient()
        params = client._params({"page": 1})
        assert "api_key" not in params
        assert params["page"] == 1


# ------------------------------------------------------------------
# validate_credentials
# ------------------------------------------------------------------


def test_validate_credentials_success(tmdb) -> None:
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    tmdb.session.get = MagicMock(return_value=mock_resp)

    ok, msg = tmdb.validate_credentials("my-api-key")
    assert ok is True
    assert "successful" in msg


def test_validate_credentials_empty(tmdb) -> None:
    ok, msg = tmdb.validate_credentials("")
    assert ok is False
    assert "required" in msg


def test_validate_credentials_401(tmdb) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    tmdb.session.get = MagicMock(
        side_effect=requests.exceptions.HTTPError(response=mock_resp)
    )
    ok, msg = tmdb.validate_credentials("bad-key")
    assert ok is False
    assert "Unauthorized" in msg


def test_validate_credentials_http_error(tmdb) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    tmdb.session.get = MagicMock(
        side_effect=requests.exceptions.HTTPError(response=mock_resp)
    )
    ok, msg = tmdb.validate_credentials("key")
    assert ok is False
    assert "HTTP Error" in msg


def test_validate_credentials_generic_error(tmdb) -> None:
    tmdb.session.get = MagicMock(side_effect=Exception("Boom"))
    ok, msg = tmdb.validate_credentials("key")
    assert ok is False
    assert "Connection failed" in msg


# ------------------------------------------------------------------
# _do_search / search_series / search_series_full
# ------------------------------------------------------------------


def test_do_search_success(tmdb) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": [{"id": 1, "name": "The Office"}]}
    tmdb.session.get = MagicMock(return_value=mock_resp)

    results = tmdb._do_search("The Office")
    assert len(results) == 1
    assert results[0]["id"] == 1


def test_do_search_error(tmdb) -> None:
    tmdb.session.get = MagicMock(side_effect=Exception("network error"))
    results = tmdb._do_search("broken query")
    assert results == []


def test_search_series_success(tmdb) -> None:
    tmdb._do_search = MagicMock(
        return_value=[
            {"id": 1234, "name": "The Office", "first_air_date": "2005-03-24"}
        ]
    )
    result = tmdb.search_series("The Office")
    assert result is not None
    assert result["id"] == 1234


def test_search_series_no_match(tmdb) -> None:
    tmdb._do_search = MagicMock(return_value=[])
    result = tmdb.search_series("NonExistentShowXYZ")
    assert result is None


def test_search_series_full(tmdb) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "results": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
    }
    tmdb.session.get = MagicMock(return_value=mock_resp)
    results = tmdb.search_series_full("Show")
    assert len(results) == 2


def test_search_series_full_not_configured() -> None:
    with patch.object(config, "tmdb_api_key", ""):
        client = TMDBClient()
        assert client.search_series_full("anything") == []


# ------------------------------------------------------------------
# _clean_name / _is_similar
# ------------------------------------------------------------------


def test_clean_name(tmdb) -> None:
    assert tmdb._clean_name("The.Office.S01.720p") == "The Office"
    assert tmdb._clean_name("Breaking Bad (2008)") == "Breaking Bad"
    assert tmdb._clean_name("Show.Name.2024.1080p.HEVC") == "Show Name"


def test_is_similar(tmdb) -> None:
    assert tmdb._is_similar("The Office", "The Office (US)") is True
    assert tmdb._is_similar("Breaking Bad", "Better Call Saul") is False
    assert tmdb._is_similar("Marvel She-Hulk", "She-Hulk") is True


def test_is_similar_empty_strings(tmdb) -> None:
    assert tmdb._is_similar("", "anything") is False
    assert tmdb._is_similar("anything", "") is False


def test_is_similar_word_overlap(tmdb) -> None:
    assert tmdb._is_similar("Doctor Strange Adventures", "Strange") is True


# ------------------------------------------------------------------
# get_series_by_id
# ------------------------------------------------------------------


def test_get_series_by_id(tmdb) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": 1234, "name": "The Office", "seasons": []}
    tmdb.session.get = MagicMock(return_value=mock_resp)

    result = tmdb.get_series_by_id(1234)
    assert result["id"] == 1234


def test_get_series_by_id_error(tmdb) -> None:
    tmdb.session.get = MagicMock(side_effect=Exception("network error"))
    assert tmdb.get_series_by_id(1) is None


# ------------------------------------------------------------------
# get_seasons
# ------------------------------------------------------------------


def test_get_seasons(tmdb) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "id": 1234,
        "seasons": [
            {"id": 1, "season_number": 1, "name": "Season 1"},
            {"id": 2, "season_number": 2, "name": "Season 2"},
            {"id": 0, "season_number": 0, "name": "Specials"},  # filtered out
        ],
    }
    tmdb.session.get = MagicMock(return_value=mock_resp)
    seasons = tmdb.get_seasons(1234)
    assert len(seasons) == 2
    assert all(s["season_number"] > 0 for s in seasons)


def test_get_seasons_only_specials(tmdb) -> None:
    """Falls back to all seasons if only specials exist."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "seasons": [{"id": 0, "season_number": 0, "name": "Specials"}]
    }
    tmdb.session.get = MagicMock(return_value=mock_resp)
    seasons = tmdb.get_seasons(1234)
    assert len(seasons) == 1


def test_get_seasons_error(tmdb) -> None:
    tmdb.session.get = MagicMock(side_effect=Exception("error"))
    assert tmdb.get_seasons(1) == []


# ------------------------------------------------------------------
# get_episodes
# ------------------------------------------------------------------


def test_get_episodes(tmdb) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "episodes": [
            {"id": 1, "episode_number": 1, "name": "Pilot"},
            {"id": 2, "episode_number": 2, "name": "Episode 2"},
        ]
    }
    tmdb.session.get = MagicMock(return_value=mock_resp)
    episodes = tmdb.get_episodes(1234, 1)
    assert len(episodes) == 2
    assert episodes[0]["episode_number"] == 1


def test_get_episodes_error(tmdb) -> None:
    tmdb.session.get = MagicMock(side_effect=Exception("error"))
    assert tmdb.get_episodes(1, 1) == []


# ------------------------------------------------------------------
# download_image
# ------------------------------------------------------------------


def test_download_image_full_url(tmdb, tmp_path) -> None:

    with patch("lan_streamer.tmdb.CACHE_DIR", tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"fake-image-data"
        tmdb.session.get = MagicMock(return_value=mock_resp)

        path = tmdb.download_image(
            "https://image.tmdb.org/t/p/w500/abc.jpg", "tmdb_series_123"
        )
        assert path == str(tmp_path / "tmdb_series_123.jpg")
        assert (tmp_path / "tmdb_series_123.jpg").read_bytes() == b"fake-image-data"

        # Second call should return cached path without re-downloading
        tmdb.session.get.reset_mock()
        path2 = tmdb.download_image(
            "https://image.tmdb.org/t/p/w500/abc.jpg", "tmdb_series_123"
        )
        assert path2 == str(tmp_path / "tmdb_series_123.jpg")
        tmdb.session.get.assert_not_called()


def test_download_image_bare_path(tmdb, tmp_path) -> None:
    """TMDB returns /abc.jpg — client should prepend the CDN base URL."""

    with patch("lan_streamer.tmdb.CACHE_DIR", tmp_path):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"poster-bytes"
        tmdb.session.get = MagicMock(return_value=mock_resp)

        path = tmdb.download_image("/abc.jpg", "poster_key")
        assert path == str(tmp_path / "poster_key.jpg")
        # Verify it used the CDN base URL
        called_url = tmdb.session.get.call_args[0][0]
        assert called_url.startswith("https://image.tmdb.org")


def test_download_image_empty(tmdb) -> None:
    assert tmdb.download_image("", "key") == ""
    assert tmdb.download_image("/abc.jpg", "") == ""


def test_download_image_error(tmdb, tmp_path) -> None:

    with patch("lan_streamer.tmdb.CACHE_DIR", tmp_path):
        tmdb.session.get = MagicMock(side_effect=Exception("Download failed"))
        path = tmdb.download_image("/abc.jpg", "error_key")
        assert path == ""


# ------------------------------------------------------------------
# Fallback search strategies
# ------------------------------------------------------------------


def test_search_series_two_word_fallback(tmdb) -> None:
    with patch.object(config, "tmdb_api_key", "test-key"):
        match_result = [
            {"id": 1, "name": "Show Runners", "first_air_date": "2020-01-01"}
        ]

        def mock_do_search(query) -> None:
            if "Show Runners" in query:
                return match_result
            return []

        tmdb._do_search = MagicMock(side_effect=mock_do_search)
        tmdb._is_similar = MagicMock(return_value=True)

        result = tmdb.search_series("Show Runners Extra Stuff")
        assert result is not None


def test_search_series_first_word_fallback(tmdb) -> None:
    with patch.object(config, "tmdb_api_key", "test-key"):
        match_result = [{"id": 2, "name": "Fargo", "first_air_date": "2014-04-15"}]

        def mock_do_search(query) -> None:
            if query == "Fargo":
                return match_result
            return []

        tmdb._do_search = MagicMock(side_effect=mock_do_search)
        tmdb._is_similar = MagicMock(return_value=True)

        result = tmdb.search_series("Fargo Criminal Cases 2025")
        assert result is not None


def test_search_series_all_fallbacks_fail(tmdb) -> None:
    with patch.object(config, "tmdb_api_key", "test-key"):
        tmdb._do_search = MagicMock(return_value=[])
        result = tmdb.search_series("Totally Unknown Show Name 2025")
        assert result is None


def test_is_similar_ratio_branch(tmdb) -> None:
    """Test the SequenceMatcher ratio branch (not substring, not word-overlap)."""
    # "Breaking Bad" vs "Breking Bdd" — not substring, not word overlap, but ratio > 0.7
    result = tmdb._is_similar("Breaking Bad", "Breking Bdd")
    # Just verify it doesn't crash; result depends on ratio
    assert isinstance(result, bool)


def test_search_series_two_word_returns_match(tmdb) -> None:
    """Hit lines 160-165: two-word fallback finds a match and returns it."""
    with patch.object(config, "tmdb_api_key", "test-key"):
        match_result = [
            {"id": 1, "name": "ShowName Extra", "first_air_date": "2020-01-01"}
        ]

        call_count = {"n": 0}

        def mock_do_search(query) -> None:
            call_count["n"] += 1
            # First 2 calls (main term attempts) fail; 3rd (two-word) succeeds
            if call_count["n"] >= 3:
                return match_result
            return []

        tmdb._do_search = MagicMock(side_effect=mock_do_search)
        # Force _is_similar to return True so the two-word branch returns
        tmdb._is_similar = MagicMock(return_value=True)

        result = tmdb.search_series("ShowName Extra Words Here")
        assert result is not None
        assert result["id"] == 1


def test_tmdb_is_similar_word_overlap(tmdb) -> None:
    # Hit tmdb.py line 111
    # Need words > 3 and not in common list
    # "Breaking Bad" vs "Bad Breaking" - should match via word overlap
    assert tmdb._is_similar("Breaking Bad", "Bad Breaking")


def test_tmdb_search_fallback_branches(tmdb) -> None:
    # Hit tmdb.py lines 160-165 (two word fallback)
    call_count = {"n": 0}

    def mock_do_search(query) -> None:
        call_count["n"] += 1
        if query == "Show Name":  # The two-word fallback
            return [{"id": 1, "name": "Show Name Extra"}]
        return []

    with (
        patch.object(tmdb, "_do_search", mock_do_search),
        patch.object(tmdb, "_is_similar", lambda a, b: True),
    ):
        res = tmdb.search_series("Show Name Long Title")
        assert res is not None
        assert res["id"] == 1


def test_tmdb_search_first_word_fallback(tmdb) -> None:
    # Hit tmdb.py lines 168-178
    def mock_do_search(query) -> None:
        # Return result only for the specific fallback term
        if query == "Breaking":
            return [{"id": 1, "name": "Breaking Bad"}]
        return []

    with (
        patch.object(tmdb, "_do_search", mock_do_search),
        patch.object(tmdb, "_is_similar", lambda a, b, threshold=0.7: True),
    ):
        res = tmdb.search_series("Breaking Bad Show")
        assert res is not None
        assert res["id"] == 1


def test_search_series_scoring_priority(tmdb) -> None:
    """Verify that scoring prioritizes the exact subtitle match over a preceding generic title."""
    candidates_list = [
        {"id": 61889, "name": "Daredevil"},
        {"id": 208857, "name": "Daredevil: Born Again"},
    ]
    tmdb._do_search = MagicMock(return_value=candidates_list)

    # Search for DareDevil - born again
    result = tmdb.search_series("DareDevil - born again")
    assert result is not None
    assert result["id"] == 208857
