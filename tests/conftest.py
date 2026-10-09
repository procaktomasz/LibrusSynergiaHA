"""Wspolne ustawienia testow."""

import pytest
import sys

# On Windows, normalize backslashes in frame inspection so HA detects custom_components
if sys.platform == "win32":
    try:
        import homeassistant.helpers.frame as ha_frame
        _orig_get_integration_frame = ha_frame.get_integration_frame
        def _win_get_integration_frame(exclude_integrations=None):
            try:
                return _orig_get_integration_frame(exclude_integrations)
            except ha_frame.MissingIntegrationFrame:
                frame = ha_frame.get_current_frame()
                while frame is not None:
                    filename = frame.f_code.co_filename.replace("\\", "/")
                    for path in ("custom_components/", "homeassistant/components/"):
                        try:
                            index = filename.index(path)
                            start = index + len(path)
                            end = filename.index("/", start)
                            integration = filename[start:end]
                            return ha_frame.IntegrationFrame(
                                custom_integration=(path == "custom_components/"),
                                integration=integration,
                                module=None,
                                relative_filename=filename,
                                frame=frame,
                            )
                        except ValueError:
                            pass
                    frame = frame.f_back
                raise ha_frame.MissingIntegrationFrame
        ha_frame.get_integration_frame = _win_get_integration_frame
    except Exception:
        pass


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Pozwol Home Assistantowi ladowac integracje z custom_components."""
    yield
