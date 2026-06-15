import logging


def test_queries_metadata_matching_import() -> None:
    # Trigger logger definition and verify it exists
    import lan_streamer.db.queries_metadata_matching as qmm

    assert qmm.logger is not None
    assert isinstance(qmm.logger, logging.Logger)
