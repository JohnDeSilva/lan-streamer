"""Utility for masking and clipping images for premium UI rendering."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter, QPainterPath


def get_circular_pixmap(pixmap: QPixmap, size: int) -> QPixmap:
    """Crop and mask a QPixmap to a circular shape of the specified size.

    Args:
        pixmap: The original QPixmap to process.
        size: Target width/height for the square circular bounding box.

    Returns:
        A new QPixmap cropped to a circle, with transparent background.
    """
    if pixmap.isNull():
        return pixmap

    # Scale to fit within the target size
    scaled_pixmap = pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    # Create target transparent pixmap
    circular_pixmap = QPixmap(size, size)
    circular_pixmap.fill(Qt.GlobalColor.transparent)

    # Setup painter with circular clip path
    painter = QPainter(circular_pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    clip_path = QPainterPath()
    clip_path.addEllipse(0, 0, size, size)
    painter.setClipPath(clip_path)

    # Center-crop the scaled image
    x_offset = (size - scaled_pixmap.width()) // 2
    y_offset = (size - scaled_pixmap.height()) // 2
    painter.drawPixmap(x_offset, y_offset, scaled_pixmap)
    painter.end()

    return circular_pixmap
