"""Root entry point for Streamlit Community Cloud and local development."""

import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The real app builds its UI at module scope. Reload it on Streamlit reruns so
# widgets and session-state changes are processed after every user interaction.
_APP_MODULE = "compatibility_analyzer.app.migration_analyzer_streamlit_app"
if _APP_MODULE in sys.modules:
    importlib.reload(sys.modules[_APP_MODULE])
else:
    importlib.import_module(_APP_MODULE)
