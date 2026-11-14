"""Keep imported helpers on the same release as Streamlit's rerun entry script."""
import importlib
from threading import RLock

_LOCK = RLock()
MODULES = ("analysis_core", "market_data", "case_analysis", "charts", "asset_resolution", "target_extraction", "tracker_core", "tracker_ui", "tiktok_import", "photo_import", "video_pipeline", "tiktok_ui")


def import_flow(expected_version):
    """Reload once on a release mismatch, never on ordinary widget reruns."""
    with _LOCK:
        modules = [importlib.import_module(name) for name in MODULES]
        if any(getattr(module, "IMPORT_VERSION", None) != expected_version for module in modules):
            importlib.invalidate_caches()
            for module in modules:  # Dependency order matters for from-imports.
                importlib.reload(module)
        if any(getattr(module, "IMPORT_VERSION", None) != expected_version for module in modules):
            raise RuntimeError("The app update is still loading. Please reload in a moment.")
        return modules[-1].tiktok_mode
