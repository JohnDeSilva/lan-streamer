"""
Version selection logic for multi-file media items.

Provides scoring functions to determine the "best" version of a movie
or episode when multiple files (e.g. different resolutions, codecs)
exist in the same directory.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("lan_streamer.scanner")


def get_version_score_key(version: Dict[str, Any]) -> tuple:
    """Return a sort key for a version dict so higher-quality versions sort first.

    Factors considered (in order of importance):

    - **Resolution** (*width × height*, higher is better).
    - **Bit rate** (higher is better).
    - **Video codec** (AV1 → HEVC/H.265 → H.264/AVC → other).
    - **Audio codec** (TrueHD/Atmos → DTS-HD → DTS → EAC3/AC3 → AAC/Opus → MP3).

    Parameters
    ----------
    version : Dict[str, Any]
        A version dictionary that may contain keys ``resolution``,
        ``bit_rate``, ``video_codec``, and ``audio_tracks``.

    Returns
    -------
    tuple
        A tuple ``(res_score, bit_rate, video_codec_score, audio_codec_score)``
        suitable for use as ``key`` in :func:`sorted`.
    """
    res = version.get("resolution") or ""
    res_score = 0
    if "x" in res:
        try:
            w, h = res.split("x")
            res_score = int(w) * int(h)
        except Exception:
            pass

    bit_rate = version.get("bit_rate") or 0
    try:
        bit_rate = int(bit_rate)
    except Exception:
        bit_rate = 0

    video_codec = (version.get("video_codec") or "").lower()
    video_ranks = {"av1": 4, "hevc": 3, "h265": 3, "h264": 2, "avc": 2}
    video_codec_score = 1
    for k, v in video_ranks.items():
        if k in video_codec:
            video_codec_score = max(video_codec_score, v)

    audio_tracks = version.get("audio_tracks") or []
    audio_ranks = {
        "truehd": 6,
        "atmos": 6,
        "dts-hd": 5,
        "dts": 4,
        "eac3": 3,
        "ac3": 3,
        "aac": 2,
        "opus": 2,
        "mp3": 1,
    }
    audio_codec_score = 0
    for track in audio_tracks:
        codec = (track.get("codec") or "").lower()
        track_score = 1
        for k, v in audio_ranks.items():
            if k in codec:
                track_score = max(track_score, v)
        audio_codec_score = max(audio_codec_score, track_score)

    return (res_score, bit_rate, video_codec_score, audio_codec_score)


def choose_active_version(
    versions: List[Dict[str, Any]], default_path: Optional[str] = None
) -> Dict[str, Any]:
    """Select the active version from a list of version dicts.

    If ``default_path`` is provided and matches a version, that version is
    returned. Otherwise the version with the highest quality score
    (per :func:`get_version_score_key`) is chosen.

    Parameters
    ----------
    versions : List[Dict[str, Any]]
        List of version dictionaries, each containing at least a ``path`` key.
    default_path : Optional[str], optional
        The path of the previously-selected version, if any.

    Returns
    -------
    Dict[str, Any]
        The chosen version dict, or an empty dict if ``versions`` is empty.
    """
    if not versions:
        return {}
    if default_path:
        for v in versions:
            if v.get("path") == default_path:
                return v
    sorted_versions = sorted(versions, key=get_version_score_key, reverse=True)
    return sorted_versions[0]
