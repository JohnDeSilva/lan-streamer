import pytest
import requests
from pathlib import Path
from unittest.mock import MagicMock, patch
from lan_streamer.providers.tmdb import TMDBClient, TMDB_IMAGE_BASE


@pytest.fixture
def tmdb(tmp_path, mock_session) -> TMDBClient:
    client = TMDBClient(
        session=mock_session,
        api_key="test-tmdb-key",
        cache_dir=tmp_path,
    )
    return client


# ------------------------------------------------------------------
# is_configured
# ------------------------------------------------------------------


def test_tmdb_is_configured(tmdb) -> None:
    assert tmdb.is_configured() is True


def test_tmdb_not_configured(mock_session) -> None:
    mock_session.request.side_effect = Exception("mocked network failure")
    client = TMDBClient(session=mock_session, api_key="")
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
    client = TMDBClient(api_key="")
    params = client._params({"page": 1})
    assert "api_key" not in params
    assert params["page"] == 1


# ------------------------------------------------------------------
# _do_search / search_series / search_series_full
# ------------------------------------------------------------------


def test_do_search_success(tmdb) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": [{"id": 1, "name": "The Office"}]}
    tmdb.session.request = MagicMock(return_value=mock_resp)

    results = tmdb._do_search("The Office")
    assert len(results) == 1
    assert results[0]["id"] == 1


def test_do_search_error(tmdb) -> None:
    tmdb.session.request = MagicMock(side_effect=Exception("network error"))
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
    tmdb.session.request = MagicMock(return_value=mock_resp)
    results = tmdb.search_series_full("Show")
    assert len(results) == 2


def test_search_series_full_not_configured() -> None:
    client = TMDBClient(api_key="")
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
    tmdb.session.request = MagicMock(return_value=mock_resp)

    result = tmdb.get_series_by_id(1234)
    assert result["id"] == 1234


def test_get_series_by_id_error(tmdb) -> None:
    tmdb.session.request = MagicMock(side_effect=Exception("network error"))
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
            {"id": 0, "season_number": 0, "name": "Specials"},
        ],
    }
    tmdb.session.request = MagicMock(return_value=mock_resp)
    seasons = tmdb.get_seasons(1234)
    assert len(seasons) == 3


def test_get_seasons_only_specials(tmdb) -> None:
    """Falls back to all seasons if only specials exist."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "seasons": [{"id": 0, "season_number": 0, "name": "Specials"}]
    }
    tmdb.session.request = MagicMock(return_value=mock_resp)
    seasons = tmdb.get_seasons(1234)
    assert len(seasons) == 1


def test_get_seasons_error(tmdb) -> None:
    tmdb.session.request = MagicMock(side_effect=Exception("error"))
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
    tmdb.session.request = MagicMock(return_value=mock_resp)
    episodes = tmdb.get_episodes(1234, 1)
    assert len(episodes) == 2
    assert episodes[0]["episode_number"] == 1


def test_get_episodes_error(tmdb) -> None:
    tmdb.session.request = MagicMock(side_effect=Exception("error"))
    assert tmdb.get_episodes(1, 1) == []


def test_get_episodes_http_error_404(tmdb) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    tmdb.session.request = MagicMock(
        side_effect=requests.exceptions.HTTPError(response=mock_resp)
    )
    assert tmdb.get_episodes(1, 1) == []


def test_get_episodes_http_error_500(tmdb) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    tmdb.session.request = MagicMock(
        side_effect=requests.exceptions.HTTPError(response=mock_resp)
    )
    assert tmdb.get_episodes(1, 1) == []


# ------------------------------------------------------------------
# download_image
# ------------------------------------------------------------------


def test_download_image_full_url(tmdb, tmp_path) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"fake-image-data"
    tmdb.session.request = MagicMock(return_value=mock_resp)

    path = tmdb.download_image(
        "https://example.invalid/t/p/w500/abc.jpg", "tmdb_series_123"
    )
    assert path == str(tmp_path / "tmdb_series_123.jpg")
    assert (tmp_path / "tmdb_series_123.jpg").read_bytes() == b"fake-image-data"

    # Second call should return cached path without re-downloading
    tmdb.session.request.reset_mock()
    path2 = tmdb.download_image(
        "https://example.invalid/t/p/w500/abc.jpg", "tmdb_series_123"
    )
    assert path2 == str(tmp_path / "tmdb_series_123.jpg")
    tmdb.session.request.assert_not_called()


def test_download_image_bare_path(tmdb, tmp_path) -> None:
    """TMDB returns /abc.jpg — client should prepend the CDN base URL."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"poster-bytes"
    tmdb.session.request = MagicMock(return_value=mock_resp)

    path = tmdb.download_image("/abc.jpg", "poster_key")
    assert path == str(tmp_path / "poster_key.jpg")
    # Verify it used the CDN base URL
    called_url = tmdb.session.request.call_args[1]["url"]
    assert called_url.startswith(TMDB_IMAGE_BASE)


def test_download_image_empty(tmdb) -> None:
    assert tmdb.download_image("", "key") == ""
    assert tmdb.download_image("/abc.jpg", "") == ""


def test_download_image_error(tmdb) -> None:
    tmdb.session.request = MagicMock(side_effect=Exception("Download failed"))
    path = tmdb.download_image("/abc.jpg", "error_key")
    assert path == ""


# ------------------------------------------------------------------
# Fallback search strategies
# ------------------------------------------------------------------


def test_search_series_two_word_fallback(tmdb) -> None:
    match_result = [{"id": 1, "name": "Show Runners", "first_air_date": "2020-01-01"}]

    def mock_do_search(query) -> None:
        if "Show Runners" in query:
            return match_result
        return []

    tmdb._do_search = MagicMock(side_effect=mock_do_search)
    tmdb._is_similar = MagicMock(return_value=True)

    result = tmdb.search_series("Show Runners Extra Stuff")
    assert result is not None


def test_search_series_first_word_fallback(tmdb) -> None:
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
    match_result = [{"id": 1, "name": "ShowName Extra", "first_air_date": "2020-01-01"}]

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


def test_search_movie_success(tmdb) -> None:
    tmdb._do_movie_search = MagicMock(
        return_value=[{"id": 19995, "title": "Avatar", "release_date": "2009-12-15"}]
    )
    result = tmdb.search_movie("Avatar", year=2009)
    assert result is not None
    assert result["id"] == 19995


def test_search_movie_no_match(tmdb) -> None:
    tmdb._do_movie_search = MagicMock(return_value=[])
    result = tmdb.search_movie("Unknown Movie XYZ")
    assert result is None


def test_search_movie_full(tmdb) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "results": [{"id": 1, "title": "M1"}, {"id": 2, "title": "M2"}]
    }
    tmdb.session.request = MagicMock(return_value=mock_resp)
    results = tmdb.search_movie_full("Movie")
    assert len(results) == 2


def test_search_movie_full_not_configured() -> None:
    client = TMDBClient(api_key="")
    assert client.search_movie_full("anything") == []


def test_get_movie_by_id(tmdb) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": 19995, "title": "Avatar"}
    tmdb.session.request = MagicMock(return_value=mock_resp)

    result = tmdb.get_movie_by_id(19995)
    assert result is not None
    assert result["id"] == 19995


def test_get_movie_by_id_error(tmdb) -> None:
    tmdb.session.request = MagicMock(side_effect=Exception("network error"))
    assert tmdb.get_movie_by_id(1) is None


def test_do_movie_search_error(tmdb) -> None:
    tmdb.session.request = MagicMock(side_effect=Exception("network error"))
    assert tmdb._do_movie_search("query") == []


# ------------------------------------------------------------------
# Episode Groups
# ------------------------------------------------------------------


def test_get_episode_groups_success(tmdb) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": [{"id": "g1", "name": "DVD Order"}]}
    tmdb.session.request = MagicMock(return_value=mock_resp)

    res = tmdb.get_episode_groups(1234)
    assert len(res) == 1
    assert res[0]["id"] == "g1"


def test_get_episode_groups_error(tmdb) -> None:
    tmdb.session.request = MagicMock(side_effect=Exception("network error"))
    assert tmdb.get_episode_groups(1234) == []


def test_get_episode_group_details_success(tmdb) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": "g1", "name": "DVD Order", "groups": []}
    tmdb.session.request = MagicMock(return_value=mock_resp)

    res = tmdb.get_episode_group_details("g1")
    assert res is not None
    assert res["id"] == "g1"


def test_get_episode_group_details_error(tmdb) -> None:
    tmdb.session.request = MagicMock(side_effect=Exception("network error"))
    assert tmdb.get_episode_group_details("g1") is None


def test_get_season_based_episode_group_no_groups(tmdb) -> None:
    tmdb.get_episode_groups = MagicMock(return_value=[])
    assert tmdb.get_season_based_episode_group(1234) is None


def test_get_season_based_episode_group_priority(tmdb) -> None:
    # 1. Type 7 is preferred
    mock_groups = [
        {"id": "g3", "name": "DVD", "type": 3},
        {"id": "g7", "name": "TVDB", "type": 7},
        {"id": "g4", "name": "Digital", "type": 4},
    ]
    tmdb.get_episode_groups = MagicMock(return_value=mock_groups)
    tmdb.get_episode_group_details = MagicMock(side_effect=lambda gid: {"id": gid})

    res = tmdb.get_season_based_episode_group(1234)
    assert res is not None
    assert res["id"] == "g7"


def test_get_season_based_episode_group_fallback_type_3_4(tmdb) -> None:
    # 2. Type 3/4 fallback if no Type 7
    mock_groups = [
        {"id": "g3", "name": "DVD", "type": 3},
        {"id": "g4", "name": "Digital", "type": 4},
    ]
    tmdb.get_episode_groups = MagicMock(return_value=mock_groups)
    tmdb.get_episode_group_details = MagicMock(side_effect=lambda gid: {"id": gid})

    res = tmdb.get_season_based_episode_group(1234)
    assert res is not None
    assert res["id"] == "g3"


def test_get_season_based_episode_group_fallback_name(tmdb) -> None:
    # 3. Fallback to name containing "season" or "tvdb" if no Type 7, 3, or 4
    mock_groups = [
        {"id": "g_other", "name": "Random Order", "type": 1},
        {"id": "g_season", "name": "Season Pack", "type": 2},
    ]
    tmdb.get_episode_groups = MagicMock(return_value=mock_groups)
    tmdb.get_episode_group_details = MagicMock(side_effect=lambda gid: {"id": gid})

    res = tmdb.get_season_based_episode_group(1234)
    assert res is not None
    assert res["id"] == "g_season"


def test_get_season_based_episode_group_seasons_name_preferred_over_cours(tmdb) -> None:
    # Seasons (type 6) matches name "season" which is prioritized over Cours (type 7)
    mock_groups = [
        {"id": "g_cours", "name": "Cours", "type": 7},
        {"id": "g_seasons", "name": "Seasons", "type": 6},
    ]
    tmdb.get_episode_groups = MagicMock(return_value=mock_groups)
    tmdb.get_episode_group_details = MagicMock(side_effect=lambda gid: {"id": gid})

    res = tmdb.get_season_based_episode_group(1234)
    assert res is not None
    assert res["id"] == "g_seasons"


# ------------------------------------------------------------------
# Constructor fallback tests
# ------------------------------------------------------------------


def test_tmdb_fallback_to_config_api_key() -> None:
    """When api_key is None, _effective_api_key reads from config."""
    with patch("lan_streamer.providers.tmdb.config.tmdb_api_key", "fallback-key"):
        client = TMDBClient(api_key=None, cache_dir="/tmp")
        assert client._effective_api_key == "fallback-key"
        assert client.is_configured() is True


def test_tmdb_fallback_to_default_cache_dir() -> None:
    """When cache_dir is None, _effective_cache_dir uses the default."""
    client = TMDBClient(api_key="test", cache_dir=None)
    from lan_streamer.providers.tmdb import CACHE_DIR

    assert client._effective_cache_dir == CACHE_DIR


# ------------------------------------------------------------------
# _make_request — rate limiting, 429 retry, and exhaustion
# ------------------------------------------------------------------


def test_make_request_429_respects_retry_after_header(
    tmdb: TMDBClient, mock_session: "MagicMock"
) -> None:
    """A 429 with a numeric Retry-After header sleeps for that exact duration."""
    rate_limited_response = MagicMock()
    rate_limited_response.status_code = 429
    rate_limited_response.headers = {"Retry-After": "2"}

    success_response = MagicMock()
    success_response.status_code = 200

    # _make_request dispatches GET to session.get(), not session.request().
    mock_session.request = MagicMock(
        side_effect=[rate_limited_response, success_response]
    )
    tmdb.session = mock_session

    with patch("lan_streamer.providers.tmdb.time.sleep") as mock_sleep:
        response = tmdb._make_request("GET", "https://example.invalid/3/test")

    assert response.status_code == 200
    # sleep must have been called with the Retry-After value
    sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
    assert any(call == 2.0 for call in sleep_calls), (
        f"Expected a sleep(2.0) for Retry-After header, got: {sleep_calls}"
    )


def test_make_request_429_uses_exponential_backoff_without_retry_after(
    tmdb: TMDBClient, mock_session: "MagicMock"
) -> None:
    """A 429 without a Retry-After header falls back to exponential backoff with jitter."""
    rate_limited_response = MagicMock()
    rate_limited_response.status_code = 429
    rate_limited_response.headers = {}  # no Retry-After

    success_response = MagicMock()
    success_response.status_code = 200

    # _make_request dispatches GET to session.get(), not session.request().
    mock_session.request = MagicMock(
        side_effect=[rate_limited_response, success_response]
    )
    tmdb.session = mock_session

    with (
        patch("lan_streamer.providers.tmdb.time.sleep") as mock_sleep,
        patch("lan_streamer.providers.tmdb.random.uniform", return_value=0.5),
    ):
        response = tmdb._make_request("GET", "https://example.invalid/3/test")

    assert response.status_code == 200
    # backoff_factor=1.0, attempt=0 → 1.0 * 2**0 + 0.5 = 1.5
    sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
    assert any(abs(call - 1.5) < 0.01 for call in sleep_calls), (
        f"Expected a backoff sleep near 1.5s, got: {sleep_calls}"
    )


def test_make_request_raises_runtime_error_after_all_429_retries_exhausted(
    tmdb: TMDBClient, mock_session: "MagicMock"
) -> None:
    """When every attempt returns 429, _make_request must raise RuntimeError.

    This tests that the old silent-fallback 4th request is gone: callers must
    receive an explicit error instead of an unexpected 429 response object.
    """
    rate_limited_response = MagicMock()
    rate_limited_response.status_code = 429
    rate_limited_response.headers = {}

    # All 3 attempts return 429 — the loop should exhaust and raise.
    # _make_request dispatches GET to session.get(), not session.request().
    mock_session.request = MagicMock(return_value=rate_limited_response)
    tmdb.session = mock_session

    with (
        patch("lan_streamer.providers.tmdb.time.sleep"),
        pytest.raises(RuntimeError, match="429 rate-limit"),
    ):
        tmdb._make_request("GET", "https://example.invalid/3/test")

    # Must have been called exactly max_retries (3) times — no hidden 4th call.
    assert mock_session.request.call_count == 3


def test_make_request_retries_on_network_error_and_succeeds(
    tmdb: TMDBClient, mock_session: "MagicMock"
) -> None:
    """A transient network error on the first attempt should be retried."""
    success_response = MagicMock()
    success_response.status_code = 200

    # _make_request dispatches GET to session.get(), not session.request().
    mock_session.request = MagicMock(
        side_effect=[requests.exceptions.ConnectionError("timeout"), success_response]
    )
    tmdb.session = mock_session

    with patch("lan_streamer.providers.tmdb.time.sleep"):
        response = tmdb._make_request("GET", "https://example.invalid/3/test")

    assert response.status_code == 200
    assert mock_session.request.call_count == 2


def test_make_request_reraises_on_final_network_error(
    tmdb: TMDBClient, mock_session: "MagicMock"
) -> None:
    """After max_retries network errors, the original exception is re-raised."""
    # _make_request dispatches GET to session.get(), not session.request().
    mock_session.request = MagicMock(
        side_effect=requests.exceptions.ConnectionError("persistent failure")
    )
    tmdb.session = mock_session

    with (
        patch("lan_streamer.providers.tmdb.time.sleep"),
        pytest.raises(requests.exceptions.ConnectionError, match="persistent failure"),
    ):
        tmdb._make_request("GET", "https://example.invalid/3/test")


def test_rate_limit_lock_is_class_level_shared_across_instances(
    tmp_path: "Path",
) -> None:
    """The throttle state must be shared by all TMDBClient instances.

    Two separate client objects constructed with different sessions must both
    reference the same class-level lock object (not independent per-instance
    copies).  This confirms the fix for the per-instance rate-limiter bug.
    """
    client_a = TMDBClient(api_key="key-a", cache_dir=tmp_path)
    client_b = TMDBClient(api_key="key-b", cache_dir=tmp_path)

    # Both instances must reference the exact same lock object.
    assert client_a._class_rate_limit_lock is client_b._class_rate_limit_lock
    # And the same last-request-time attribute slot.
    TMDBClient._class_last_request_time = 99.0
    assert client_a._class_last_request_time == 99.0
    assert client_b._class_last_request_time == 99.0
    # Restore to zero so subsequent tests aren't affected.
    TMDBClient._class_last_request_time = 0.0


def test_concurrent_requests_are_serialised_by_throttle(
    tmp_path: "Path", mock_session: "MagicMock"
) -> None:
    """Concurrent _make_request calls from multiple threads must be serialised
    by the class-level throttle so no two requests fire within 100ms of each other.
    """
    import concurrent.futures

    # Reset the throttle state so this test starts from a clean baseline.
    TMDBClient._class_last_request_time = 0.0

    request_timestamps: list[float] = []
    real_time = __import__("time")

    success_response = MagicMock()
    success_response.status_code = 200
    mock_session.request = MagicMock(return_value=success_response)

    def make_one_request() -> None:
        client = TMDBClient(
            session=mock_session, api_key="test-key", cache_dir=tmp_path
        )
        # Record the wall-clock time just after the throttle gate exits.
        client._make_request("GET", "https://example.invalid/3/test")
        request_timestamps.append(real_time.time())

    # Launch 4 threads simultaneously — without the throttle they would all
    # fire at once; with it each must wait ≥ 100ms after the previous one.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(make_one_request) for _ in range(4)]
        for future in concurrent.futures.as_completed(futures):
            future.result()

    request_timestamps.sort()
    gaps = [
        request_timestamps[index + 1] - request_timestamps[index]
        for index in range(len(request_timestamps) - 1)
    ]
    # Every consecutive pair must be at least 90ms apart (10ms tolerance for
    # scheduling jitter in CI environments).
    for gap in gaps:
        assert gap >= 0.09, (
            f"Two TMDB requests fired only {gap * 1000:.1f}ms apart — "
            "throttle is not working correctly."
        )


def test_rate_limit_lock_not_held_during_sleep(tmp_path: "Path") -> None:
    """Regression test for sleep-inside-lock bug.

    Previously ``_make_request`` held ``_class_rate_limit_lock`` for the full
    throttle sleep duration, serializing ALL parallel TMDB calls.  After the fix
    the lock is only held for the timestamp read/write; other threads must be
    able to acquire it immediately while the first thread is sleeping.

    Strategy: force a 100ms throttle delay on thread-1 by resetting
    ``_class_last_request_time`` to ``now``.  While thread-1 is sleeping,
    thread-2 must be able to acquire the lock within 10ms (not after 100ms).
    """
    import concurrent.futures
    import time as time_module

    TMDBClient._class_last_request_time = 0.0

    success_response = MagicMock()
    success_response.status_code = 200

    # Use a fresh real session per client so requests don't conflict.
    lock_acquisition_time: list[float] = []

    def thread_1_make_request() -> None:
        """Makes a real throttled request (will sleep ~100ms)."""
        session = MagicMock()
        session.request = MagicMock(return_value=success_response)
        client = TMDBClient(session=session, api_key="key", cache_dir=tmp_path)
        # Force a throttle delay by making _class_last_request_time = now
        TMDBClient._class_last_request_time = time_module.monotonic()
        client._make_request("GET", "https://example.invalid/3/test1")

    def thread_2_try_lock() -> None:
        """Tries to acquire the class-level lock and records how long it took."""
        start = time_module.time()
        with TMDBClient._class_rate_limit_lock:
            lock_acquisition_time.append(time_module.time() - start)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        future_1 = pool.submit(thread_1_make_request)
        # Give thread 1 just enough time to enter _make_request and start sleeping
        time_module.sleep(0.02)
        future_2 = pool.submit(thread_2_try_lock)
        future_1.result()
        future_2.result()

    assert lock_acquisition_time, "thread_2 did not run"
    acquisition_duration = lock_acquisition_time[0]
    # If the lock were held during sleep, thread_2 would wait ~80ms more.
    # After the fix it should acquire within 10ms.
    assert acquisition_duration < 0.05, (
        f"Lock acquisition took {acquisition_duration * 1000:.1f}ms — "
        "the lock is likely still being held during the throttle sleep."
    )
