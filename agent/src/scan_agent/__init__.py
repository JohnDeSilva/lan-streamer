"""Remote scan agent for lan-streamer.

The agent owns scanning, metadata resolution, subtitle management, and
technical probing for the lan-streamer media library, exposing a REST API
for the desktop client and a web UI.
"""

try:
    from lan_streamer import __version__ as __version__
except ImportError:
    __version__ = "0.1.0"
