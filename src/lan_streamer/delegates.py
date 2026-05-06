from PySide6.QtWidgets import QStyledItemDelegate
from PySide6.QtGui import QPainter, QPixmap, QColor, QFontMetrics, QPainterPath
from PySide6.QtCore import Qt, QRect, QSize


class PosterDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.poster_size = QSize(150, 225)
        self.margin = 10
        self.text_height = 30

    def sizeHint(self, option, index):
        return QSize(
            self.poster_size.width() + self.margin * 2,
            self.poster_size.height() + self.text_height + self.margin * 2,
        )

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        rect = option.rect

        from PySide6.QtWidgets import QStyle

        # Hover and Selection states
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, QColor(255, 255, 255, 40))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect, QColor(255, 255, 255, 20))

        # Poster Rect
        poster_rect = QRect(
            rect.x() + self.margin,
            rect.y() + self.margin,
            self.poster_size.width(),
            self.poster_size.height(),
        )

        poster_path = index.data(Qt.ItemDataRole.UserRole + 1)
        if poster_path:
            pixmap = QPixmap(poster_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    self.poster_size,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )

                # Draw rounded image
                path = QPainterPath()
                path.addRoundedRect(poster_rect, 8, 8)
                painter.setClipPath(path)

                # Center the image within the poster_rect
                px_x = (
                    poster_rect.x() + (poster_rect.width() - scaled_pixmap.width()) // 2
                )
                px_y = (
                    poster_rect.y()
                    + (poster_rect.height() - scaled_pixmap.height()) // 2
                )
                painter.drawPixmap(px_x, px_y, scaled_pixmap)

                # Remove clipping for text
                painter.setClipping(False)

        # Draw Text
        title = index.data(Qt.ItemDataRole.DisplayRole)
        if title:
            text_rect = QRect(
                rect.x() + self.margin,
                rect.y() + self.margin + self.poster_size.height() + 5,
                self.poster_size.width(),
                self.text_height,
            )
            font = option.font
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(240, 240, 240))

            fm = QFontMetrics(font)
            elided_text = fm.elidedText(
                title, Qt.TextElideMode.ElideRight, text_rect.width()
            )
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                elided_text,
            )

        painter.restore()
