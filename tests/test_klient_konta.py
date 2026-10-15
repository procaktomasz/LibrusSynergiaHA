"""Każde konto ma własny słoik ciasteczek i token (librus-apix 1.5.3 współdzieli je domyślnie)."""

from unittest.mock import patch

from custom_components.librus_apix.__init__ import LibrusApiClient, nowy_klient


def test_nowy_klient_ma_wlasne_ciasteczka_i_token():
    a, b = nowy_klient(), nowy_klient()
    assert a.cookies is not b.cookies
    assert a.token is not b.token
    a.cookies.set("oauth_token", "konto-a", domain="synergia.librus.pl", path="/")
    assert b.cookies.get("oauth_token") is None


async def test_dwa_konta_nie_dziela_tokenu_oauth(hass):
    with patch("librus_apix.client.Client.get_token", return_value=object()):
        jan = LibrusApiClient("jan", "haslo")
        ola = LibrusApiClient("ola", "haslo")
        assert await jan.async_authenticate()
        assert await ola.async_authenticate()
    jan._client.cookies.set("oauth_token", "token-jana", domain="synergia.librus.pl", path="/")
    assert ola._client.cookies is not jan._client.cookies
    assert ola._client.cookies.get("oauth_token") is None
