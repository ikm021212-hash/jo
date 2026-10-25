"""Per-user data, independent of the extracted source folder."""
import os
import sys
from pathlib import Path


def default_data_dir(platform=None):
    if (platform or sys.platform) == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "SmallCloset"
    return Path.home() / ".local" / "share" / "smallcloset"


def data_dir():
    return Path(os.environ.get("SM_DATA_DIR") or default_data_dir()).expanduser().resolve()
