from PySide6.QtGui import QPixmap
from lan_streamer.ui_views.image_masking import get_circular_pixmap


def test_get_circular_pixmap_null(qtbot) -> None:
    """Null pixmap should be returned as is."""
    null_pixmap = QPixmap()
    result = get_circular_pixmap(null_pixmap, 60)
    assert result.isNull()


def test_get_circular_pixmap_valid(qtbot) -> None:
    """Valid pixmap should be clipped to the requested square size."""
    # Create a 100x100 base pixmap
    pixmap = QPixmap(100, 100)
    pixmap.fill()
    assert not pixmap.isNull()

    result = get_circular_pixmap(pixmap, 60)
    assert not result.isNull()
    assert result.width() == 60
    assert result.height() == 60
