"""Plan lekcji: wpisy przekreślone przy przesunięciu lekcji (Issue #59).

HTML komórek pochodzi z prawdziwego planu (13.11.2026, lekcje 1 i 2 zamienione
miejscami), z danymi zanonimizowanymi.
"""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.librus_apix.__init__ import LibrusApiClient
from custom_components.librus_apix.plan_lekcji import get_timetable


def _podpowiedz(z, na, przedmiot, nauczyciel, sala):
    title = (
        f"&lt;b&gt;Data:&lt;/b&gt; 2026-11-09&lt;br&gt;&lt;b&gt;Nr lekcji:&lt;/b&gt; {z} -&gt; {na}"
        f"&lt;br&gt;&lt;b&gt;Klasa:&lt;/b&gt; 7a SZKOLA&lt;br&gt;&lt;b&gt;Nauczyciel:&lt;/b&gt; "
        f"{nauczyciel} -&gt; {nauczyciel}&lt;br&gt;&lt;b&gt;Przedmiot:&lt;/b&gt; {przedmiot}"
        f"&lt;br&gt;&lt;b&gt;Sala:&lt;/b&gt; {sala} -&gt; [brak]&lt;br&gt;&lt;b&gt;Uwaga:&lt;/b&gt; "
        f"Przesunięcie&lt;br&gt;&lt;b&gt;Data dodania:&lt;/b&gt; 2026-11-08 nd."
    )
    return (
        f'<a href="javascript:void(0);" title="{title}">'
        '<div class="center plan-lekcji-info">przesunięcie</div></a>'
    )


def _wpis(przedmiot, nauczyciel):
    return f'<div class="text"><b>{przedmiot}</b><br/>- {nauczyciel}</div>'


# Lekcja 1: Matematyka przeniesiona stąd na 2., Historia przeniesiona tutaj z 2.
# Na początku komórki Librus wstawia pusty <s></s>.
LEKCJA_1 = (
    "<s></s>"
    + _podpowiedz(1, 2, "Matematyka", "Nauczyciel A", "110")
    + "<s>" + _wpis("Matematyka", "Nauczyciel A") + "</s>"
    + _podpowiedz(2, 1, "Historia", "Nauczyciel B", "25")
    + _wpis("Historia", "Nauczyciel B")
)
LEKCJA_2 = (
    "<s></s>"
    + _podpowiedz(2, 1, "Historia", "Nauczyciel B", "25")
    + "<s>" + _wpis("Historia", "Nauczyciel B") + "</s>"
    + _podpowiedz(1, 2, "Matematyka", "Nauczyciel A", "110")
    + _wpis("Matematyka", "Nauczyciel A")
)
# Lekcja przeniesiona stąd, nic w zamian.
TYLKO_PRZEKRESLONA = (
    "<s></s>"
    + _podpowiedz(3, 7, "Fizyka", "Nauczyciel C", "12")
    + "<s>" + _wpis("Fizyka", "Nauczyciel C") + "</s>"
)
# Podział na grupy, bez zmian w planie.
GRUPY = _wpis("Język angielski", "Nauczyciel D") + _wpis("Informatyka", "Nauczyciel E")


def _html(komorki_poniedzialku):
    """Tabela planu: każdy wiersz = numer lekcji, poniedziałek z podanej listy,
    reszta tygodnia pusta."""
    wiersze = []
    for nr, komorka in enumerate(komorki_poniedzialku, start=1):
        tds = "".join(
            f'<td class="line1" id="timetableEntryBox" data-date="2026-11-{9 + d:02d}" '
            f'data-time_from="08:00" data-time_to="08:45">{komorka if d == 0 else ""}</td>'
            for d in range(7)
        )
        wiersze.append(f'<tr class="line1"><td class="center">{nr}</td>{tds}</tr>')
    return f'<html><body><table class="decorated plan-lekcji">{"".join(wiersze)}</table></body></html>'


def _poniedzialek(*komorki):
    client = SimpleNamespace(
        TIMETABLE_URL="https://synergia.librus.pl/przegladaj_plan_lekcji",
        post=lambda url, data: SimpleNamespace(text=_html(komorki)),
    )
    return get_timetable(client, datetime(2026, 11, 9))[0]


def test_przesuniecie_bierze_wpis_nieprzekreslony():
    l1, l2 = _poniedzialek(LEKCJA_1, LEKCJA_2)

    assert l1.subject == "Historia"
    assert l1.teacher_and_classroom == "Nauczyciel B"
    assert l1.skreslony is False
    assert l1.info["przesunięcie"]["subject_swap"] == "Historia"

    assert l2.subject == "Matematyka"
    assert l2.teacher_and_classroom == "Nauczyciel A"
    assert l2.skreslony is False
    assert l2.info["przesunięcie"]["subject_swap"] == "Matematyka"


def test_tylko_przekreslony_wpis():
    (lekcja,) = _poniedzialek(TYLKO_PRZEKRESLONA)
    assert lekcja.subject == "Fizyka"
    assert lekcja.skreslony is True
    assert "przesunięcie" in lekcja.info


def test_grupy_i_pusta_komorka_jak_w_bibliotece():
    grupy, pusta = _poniedzialek(GRUPY, "")
    assert grupy.subject == "Język angielski / Informatyka"
    assert grupy.teacher_and_classroom == "Nauczyciel D / Nauczyciel E"
    assert grupy.skreslony is False
    assert grupy.info == {}
    assert pusta.subject == ""
    assert pusta.skreslony is False


def _klient():
    lib = MagicMock()
    lib.BASE_URL = "https://synergia.librus.pl"
    lib.cookies = {}
    lib.refresh_oauth.return_value = "fresh-oauth-token"
    lib.get.return_value.json.return_value = {"data": []}
    client = LibrusApiClient("user", "pass")
    client._client = lib
    client._token = "token"
    return client


def _tydzien(skreslony):
    lekcja = SimpleNamespace(
        subject="Historia",
        teacher_and_classroom="Nauczyciel B",
        date_from="08:00",
        date_to="08:45",
        date=None,
        number=1,
        info={"przesunięcie": {
            "teacher_swap": "Nauczyciel B -> Nauczyciel B",
            "subject_swap": "Historia",
            "classroom_swap": "25 -> [brak]",
            "date_added": "2026-11-08 nd.",
        }},
        skreslony=skreslony,
    )
    return [[lekcja] for _ in range(7)]


@pytest.mark.asyncio
@pytest.mark.parametrize("skreslony, odwolana", [(False, False), (True, True)])
async def test_przesuniecie_odwoluje_tylko_przekreslony(skreslony, odwolana):
    client = _klient()
    with patch("custom_components.librus_apix.plan_lekcji.get_timetable",
               return_value=_tydzien(skreslony)):
        wynik = await client.async_get_timetable()
    dzis = next(d for d in wynik if d["data"] == date.today().strftime("%Y-%m-%d"))
    (lekcja,) = dzis["lekcje"]
    assert lekcja["przedmiot"] == "Historia"
    assert lekcja["odwolana"] is odwolana
