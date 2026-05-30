from lan_streamer.ui_views import get_application_stylesheet


def test_stylesheet_validity() -> None:
    css_content: str = get_application_stylesheet()
    assert "background-color" in css_content
    assert "border-radius" in css_content
