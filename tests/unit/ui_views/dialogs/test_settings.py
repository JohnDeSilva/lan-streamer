from unittest.mock import patch
from PySide6.QtWidgets import QListWidget
from lan_streamer.ui_views import SettingsDialog
from lan_streamer.system.config import config

def test_settings_dialog_library_scan_order(qtbot) -> None:
    # Set up staged_libraries with initial order
    initial_libraries = {
        "Movies": {"type": "movie", "paths": ["/movies"]},
        "TV Shows": {"type": "tv", "paths": ["/tv"]},
        "Anime": {"type": "tv", "paths": ["/anime"]}
    }
    
    with patch.dict(config.libraries, initial_libraries, clear=True):
        dialog = SettingsDialog()
        qtbot.addWidget(dialog)
        
        # Verify initial order in list widget
        list_widget = dialog.library_order_list_widget
        assert list_widget.count() == 3
        assert list_widget.item(0).text() == "Movies"
        assert list_widget.item(1).text() == "TV Shows"
        assert list_widget.item(2).text() == "Anime"
        
        # Select "TV Shows" (index 1) and move it up
        list_widget.setCurrentRow(1)
        dialog.move_library_order_up()
        
        # Verify new order in list widget
        assert list_widget.item(0).text() == "TV Shows"
        assert list_widget.item(1).text() == "Movies"
        assert list_widget.item(2).text() == "Anime"
        
        # Verify self.staged_libraries has keys in the new order
        staged_keys = list(dialog.staged_libraries.keys())
        assert staged_keys == ["TV Shows", "Movies", "Anime"]
        
        # Move "Movies" (index 1) down
        list_widget.setCurrentRow(1)
        dialog.move_library_order_down()
        
        # Verify new order
        assert list_widget.item(0).text() == "TV Shows"
        assert list_widget.item(1).text() == "Anime"
        assert list_widget.item(2).text() == "Movies"
        
        staged_keys = list(dialog.staged_libraries.keys())
        assert staged_keys == ["TV Shows", "Anime", "Movies"]
        
        # Call save_config and check that config.libraries gets updated
        with patch.object(config, "save") as mock_save:
            dialog.save_config()
            assert list(config.libraries.keys()) == ["TV Shows", "Anime", "Movies"]
            mock_save.assert_called_once()
            
        dialog.reject()
