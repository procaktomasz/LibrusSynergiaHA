"""Wspolne ustawienia testow."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Pozwol Home Assistantowi ladowac integracje z custom_components."""
    yield
