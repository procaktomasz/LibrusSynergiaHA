import pytest
from custom_components.librus_apix.ai_summary import _parse_ai_json_response


def test_parse_clean_json():
    """Weryfikacja bezpośredniego parsowania czystego JSON."""
    raw = '{"rodzic": "Wszystko w porządku.", "uczen": "Dobra robota!"}'
    res = _parse_ai_json_response(raw)
    assert res == {"rodzic": "Wszystko w porządku.", "uczen": "Dobra robota!"}


def test_parse_markdown_json_block():
    """Weryfikacja parsowania bloku ```json ... ```."""
    raw = """```json
{
  "rodzic": "Ocena 5 z historii.",
  "uczen": "Świetny tydzień!"
}
```"""
    res = _parse_ai_json_response(raw)
    assert res == {"rodzic": "Ocena 5 z historii.", "uczen": "Świetny tydzień!"}


def test_parse_markdown_without_language_tag():
    """Weryfikacja parsowania bloku ``` ... ``` bez etykiety json."""
    raw = """```
{"rodzic": "Brak uwag.", "uczen": "Odpocznij."}
```"""
    res = _parse_ai_json_response(raw)
    assert res == {"rodzic": "Brak uwag.", "uczen": "Odpocznij."}


def test_parse_with_conversational_preamble_and_postamble():
    """Weryfikacja parsowania gdy model dodaje wstęp i zakończenie."""
    raw = """Oto wygenerowane podsumowanie:

```json
{
  "rodzic": "Wiadomość od wychowawcy o zebraniu.",
  "uczen": "Pamiętaj o stroju galowym."
}
```

Mam nadzieję, że pomogłem! Pozdrawiam serdecznie."""
    res = _parse_ai_json_response(raw)
    assert res == {
        "rodzic": "Wiadomość od wychowawcy o zebraniu.",
        "uczen": "Pamiętaj o stroju galowym.",
    }


def test_parse_embedded_json_without_markdown():
    """Weryfikacja parsowania gdy JSON jest wpleciony w tekst bez znaczników markdown."""
    raw = 'Oto dane: {"rodzic": "Podsumowanie", "uczen": "Zadania domowe zrobione"} - koniec raportu.'
    res = _parse_ai_json_response(raw)
    assert res == {"rodzic": "Podsumowanie", "uczen": "Zadania domowe zrobione"}


def test_parse_fallback_raw_text():
    """Weryfikacja działania fallbacku gdy model zwróci czysty tekst zamiast JSON."""
    raw = "W tym tygodniu uczeń radził sobie znakomicie we wszystkich przedmiotach."
    res = _parse_ai_json_response(raw)
    assert res == {"rodzic": raw, "uczen": raw}


def test_parse_empty():
    """Weryfikacja pustej odpowiedzi."""
    assert _parse_ai_json_response("") == {}
    assert _parse_ai_json_response("   \n  ") == {}


def test_default_prompts_placeholders():
    """Weryfikacja czy domyślne prompty zawierają wymagane placeholdery."""
    from custom_components.librus_apix.ai_prompts import (
        DEFAULT_PROMPT_MESSAGES_PARENT,
        DEFAULT_PROMPT_MESSAGES_STUDENT,
        DEFAULT_PROMPT_WEEKLY_PARENT,
        DEFAULT_PROMPT_WEEKLY_STUDENT,
    )
    for p in (DEFAULT_PROMPT_MESSAGES_PARENT, DEFAULT_PROMPT_MESSAGES_STUDENT):
        assert "{dzisiejsza_data}" in p
        assert "{imie}" in p
        assert "{wiadomosci}" in p

    for p in (DEFAULT_PROMPT_WEEKLY_PARENT, DEFAULT_PROMPT_WEEKLY_STUDENT):
        assert "{imie}" in p
        assert "{oceny}" in p
        assert "{frekwencja}" in p
        assert "{nieobecnosci}" in p
        assert "{zadania}" in p
        assert "{uwagi}" in p


