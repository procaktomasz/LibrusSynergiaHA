import logging
import json
import re
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .ai_prompts import (
    DEFAULT_PROMPT_WEEKLY_PARENT,
    DEFAULT_PROMPT_WEEKLY_STUDENT,
    DEFAULT_PROMPT_MESSAGES_PARENT,
    DEFAULT_PROMPT_MESSAGES_STUDENT,
)

_LOGGER = logging.getLogger(__name__)


def _parse_ai_json_response(result_text: str) -> dict:
    """Odporne wyodrębnienie i sparsowanie obiektu JSON z odpowiedzi modelu AI."""
    text = (result_text or "").strip()
    if not text:
        return {}

    # 1. Bezpośrednia próba parsowania
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Blok markdown ```json ... ``` lub ``` ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    # 3. Pierwszy i ostatni nawias klamrowy { ... } w tekście
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    # 4. Fallback: jeśli model nie zwrócił poprawnego JSON
    _LOGGER.warning("AI nie zwróciło poprawnego JSONa. Używam surowego tekstu.")
    return {"rodzic": text, "uczen": text}

async def async_generate_summary(hass: HomeAssistant, entry_id: str, coordinator_data: dict, agent_id: str, options: dict = None):
    """Generate Weekly AI Summary using Home Assistant conversation API."""
    options = options or {}
    if not coordinator_data:
        _LOGGER.error("Brak danych do wygenerowania podsumowania AI")
        return

    # Przygotowanie danych do promptu
    student = coordinator_data.get("student_info")
    imie = student.name if student else "Uczeń"
    
    oceny = []
    for subject, grades in coordinator_data.get("oceny_wg_przedmiotu", {}).items():
        nowe_oceny = [g for g in grades if g.get("jest_nowa")]
        if nowe_oceny:
            oceny.append(f"{subject}: " + ", ".join([f"{g['ocena']} ({g.get('kategoria','')})" for g in nowe_oceny]))
            
    frekwencja = coordinator_data.get("frekwencja_stat", {})
    rodzaje_frekwencji = frekwencja.get("rodzaje", {})
    # Filtrujemy 'Obecność', by AI nie myliło tego z nieobecnościami
    nieobecnosci = {k: v for k, v in rodzaje_frekwencji.items() if k.lower() != "obecność"}
    
    zadania = coordinator_data.get("zadania", [])[:5]  # Najblizsze 5 zadan
    
    oceny_str = chr(10).join(oceny) if oceny else "Brak nowych ocen"
    frekwencja_str = str(frekwencja.get("procent_semestr", "Brak danych"))
    nieobecnosci_str = json.dumps(nieobecnosci) if nieobecnosci else "Brak spóźnień i nieobecności"
    zadania_str = chr(10).join([f"- {z.get('przedmiot')}: {z.get('kategoria')} (termin: {z.get('termin')})" for z in zadania]) if zadania else "Brak nadchodzących sprawdzianów"

    prompt_parent = options.get("ai_prompt_weekly_parent", DEFAULT_PROMPT_WEEKLY_PARENT)
    prompt_parent = prompt_parent.replace("{imie}", imie).replace("{oceny}", oceny_str).replace("{frekwencja}", frekwencja_str).replace("{nieobecnosci}", nieobecnosci_str).replace("{zadania}", zadania_str)
    
    prompt_student = options.get("ai_prompt_weekly_student", DEFAULT_PROMPT_WEEKLY_STUDENT)
    prompt_student = prompt_student.replace("{imie}", imie).replace("{oceny}", oceny_str).replace("{frekwencja}", frekwencja_str).replace("{nieobecnosci}", nieobecnosci_str).replace("{zadania}", zadania_str)

    prompt = f"""
Wykonaj podsumowanie tygodnia.

INSTRUKCJA ZWROTU:
Zwróć odpowiedź w formacie JSON (bez znaczników markdown typu ```json), zawierającym dwa klucze:
1. "rodzic" - na podstawie instrukcji: {prompt_parent}
2. "uczen" - na podstawie instrukcji: {prompt_student}

Format odpowiedzi:
{{
  "rodzic": "Twój tekst dla rodzica...",
  "uczen": "Twój tekst dla ucznia..."
}}
"""
    _LOGGER.debug("Wysyłanie zapytania do AI (%s)...", agent_id)
    try:
        service_data = {"text": prompt}
        if agent_id:
            service_data["agent_id"] = agent_id
            
        response = await hass.services.async_call(
            "conversation",
            "process",
            service_data,
            blocking=True,
            return_response=True
        )
        
        result_text = ""
        if isinstance(response, dict):
            result_text = response.get("response", {}).get("speech", {}).get("plain", {}).get("speech", "")
        elif hasattr(response, "response"):
            result_text = response.response.speech.get("plain", {}).get("speech", "")
            
        if not result_text:
            _LOGGER.error("Pusta odpowiedź od modelu AI.")
            return
            
        result_json = _parse_ai_json_response(result_text)
        
        rodzic_text = result_json.get("rodzic", "Brak danych dla rodzica")
        uczen_text = result_json.get("uczen", "Brak danych dla ucznia")
        
        _LOGGER.info("Pomyślnie wygenerowano podsumowanie AI dla %s", imie)
        
        # Rozgłoszenie wygenerowanych tekstów do sensorów
        async_dispatcher_send(
            hass, 
            f"librus_ai_summary_{entry_id}", 
            {"rodzic": rodzic_text, "uczen": uczen_text}
        )
        
    except Exception as ex:
        _LOGGER.error("Błąd podczas generowania podsumowania AI: %s", ex)
        async_dispatcher_send(
            hass, 
            f"librus_ai_summary_{entry_id}", 
            {"rodzic": f"Błąd AI: {ex}", "uczen": f"Błąd AI: {ex}"}
        )

async def async_generate_messages_summary(hass: HomeAssistant, entry_id: str, coordinator_data: dict, agent_id: str, options: dict = None):
    """Generate Daily Messages AI Summary."""
    options = options or {}
    if not coordinator_data:
        _LOGGER.error("Brak danych do wygenerowania podsumowania wiadomości AI")
        return

    student = coordinator_data.get("student_info")
    imie = student.name if student else "Uczeń"
    
    wiadomosci = coordinator_data.get("wiadomosci", [])
    nieprzeczytane = []
    przeczytane = []
    
    client = hass.data.get("librus_apix", {}).get(entry_id)
    if client and hasattr(client, "_message_cache"):
        for m in wiadomosci:
            if not m.get("content") and m.get("href") in client._message_cache:
                m["content"] = client._message_cache[m.get("href")]

    for m in wiadomosci:
        date_str = m.get("date", "Brak daty")
        title = m.get("title", "")
        author = m.get("author", "")
        content = m.get("content") or "Brak pobranej treści"
        
        info = f"Data: {date_str}\nOd: {author}\nTemat: {title}\nTreść: {content}"
        
        if m.get("unread"):
            nieprzeczytane.append(info)
        else:
            przeczytane.append(info)
            
    stats = f"Do podsumowania zebrano {len(wiadomosci)} wiadomości (cała historia skrzynki), z czego {len(nieprzeczytane)} jest nieprzeczytanych."
    
    if not wiadomosci:
        _LOGGER.info("Brak wiadomości w skrzynce. Pomijam AI.")
        async_dispatcher_send(hass, f"librus_ai_messages_summary_{entry_id}", {"rodzic": "Brak wiadomości.", "uczen": "Brak wiadomości."})
        return
        
    dane_tekst = f"STATYSTYKI:\n{stats}\n\nNIEPRZECZYTANE:\n"
    dane_tekst += "\n---\n".join(nieprzeczytane) if nieprzeczytane else "Brak"
    dane_tekst += "\n\nPRZECZYTANE:\n"
    dane_tekst += "\n---\n".join(przeczytane) if przeczytane else "Brak"

    prompt_parent = options.get("ai_prompt_messages_parent", DEFAULT_PROMPT_MESSAGES_PARENT)
    prompt_parent = prompt_parent.replace("{imie}", imie).replace("{wiadomosci}", dane_tekst)
        
    prompt_student = options.get("ai_prompt_messages_student", DEFAULT_PROMPT_MESSAGES_STUDENT)
    prompt_student = prompt_student.replace("{imie}", imie).replace("{wiadomosci}", dane_tekst)

    # Złożony prompt do modelu
    prompt = f"""
Wykonaj podsumowanie wiadomości. 

INSTRUKCJA ZWROTU:
Zwróć odpowiedź w formacie JSON (bez znaczników markdown), zawierającym dwa klucze:
1. "rodzic" - na podstawie instrukcji: {prompt_parent}
2. "uczen" - na podstawie instrukcji: {prompt_student}

Format odpowiedzi:
{{
  "rodzic": "Twój tekst dla rodzica...",
  "uczen": "Twój tekst dla ucznia..."
}}
"""

    _LOGGER.debug("Wysyłanie zapytania do AI (wiadomosci)...")
    try:
        service_data = {"text": prompt}
        if agent_id:
            service_data["agent_id"] = agent_id
            
        response = await hass.services.async_call("conversation", "process", service_data, blocking=True, return_response=True)
        
        result_text = ""
        if isinstance(response, dict):
            result_text = response.get("response", {}).get("speech", {}).get("plain", {}).get("speech", "")
        elif hasattr(response, "response"):
            result_text = response.response.speech.get("plain", {}).get("speech", "")
            
        if not result_text:
            return
            
        result_json = _parse_ai_json_response(result_text)
        
        async_dispatcher_send(
            hass, 
            f"librus_ai_messages_summary_{entry_id}", 
            {
                "rodzic": result_json.get("rodzic", "Brak"), 
                "uczen": result_json.get("uczen", "Brak")
            }
        )
    except Exception as ex:
        _LOGGER.error("Błąd podczas generowania podsumowania wiadomości AI: %s", ex)
        async_dispatcher_send(
            hass, 
            f"librus_ai_messages_summary_{entry_id}", 
            {
                "rodzic": f"Wystąpił błąd AI: {ex}", 
                "uczen": f"Wystąpił błąd AI: {ex}"
            }
        )

