import logging
import json
from homeassistant.core import HomeAssistant
from homeassistant.components import conversation
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .ai_prompts import (
    DEFAULT_PROMPT_WEEKLY_PARENT,
    DEFAULT_PROMPT_WEEKLY_STUDENT,
    DEFAULT_PROMPT_MESSAGES_PARENT,
    DEFAULT_PROMPT_MESSAGES_STUDENT,
)

_LOGGER = logging.getLogger(__name__)

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
            
        # Oczyszczenie z markdown jesli model to zignorował
        if result_text.startswith("```json"):
            result_text = result_text.replace("```json", "", 1)
        if result_text.endswith("```"):
            result_text = result_text.rsplit("```", 1)[0]
            
        result_json = json.loads(result_text.strip())
        
        rodzic_text = result_json.get("rodzic", "Brak danych dla rodzica")
        uczen_text = result_json.get("uczen", "Brak danych dla ucznia")
        
        _LOGGER.info("Pomyślnie wygenerowano podsumowanie AI dla %s", imie)
        
        # Rozgłoszenie wygenerowanych tekstów do sensorów
        async_dispatcher_send(
            hass, 
            f"librus_ai_summary_{entry_id}", 
            {"rodzic": rodzic_text, "uczen": uczen_text}
        )
        
    except json.JSONDecodeError as ex:
        _LOGGER.error("Nie udało się sparsować odpowiedzi JSON od AI: %s. Odpowiedź: %s", ex, result_text)
    except Exception as ex:
        _LOGGER.error("Błąd podczas generowania podsumowania AI: %s", ex)

async def async_generate_messages_summary(hass: HomeAssistant, entry_id: str, coordinator_data: dict, agent_id: str, options: dict = None):
    """Generate Daily Messages AI Summary."""
    options = options or {}
    if not coordinator_data:
        _LOGGER.error("Brak danych do wygenerowania podsumowania wiadomości AI")
        return

    student = coordinator_data.get("student_info")
    imie = student.name if student else "Uczeń"
    
    wiadomosci = coordinator_data.get("wiadomosci", [])
    from datetime import date
    today_str = date.today().strftime("%Y-%m-%d")
    
    dzisiejsze_lub_nieprzeczytane = [m for m in wiadomosci if m.get("date", "").startswith(today_str) or m.get("unread", False)]
    
    nieprzeczytane = []
    przeczytane = []
    
    for m in dzisiejsze_lub_nieprzeczytane:
        title = m.get("title", "")
        author = m.get("author", "")
        content = m.get("content", "Brak pobranej treści")
        
        info = f"Od: {author}\nTemat: {title}\nTreść: {content}"
        
        if m.get("unread"):
            nieprzeczytane.append(info)
        else:
            przeczytane.append(info)
            
    stats = f"Do podsumowania zebrano {len(dzisiejsze_lub_nieprzeczytane)} wiadomości, z czego {len(nieprzeczytane)} jest nieprzeczytanych."
    
    if not dzisiejsze_lub_nieprzeczytane:
        _LOGGER.info("Brak wiadomości. Pomijam AI.")
        async_dispatcher_send(hass, f"librus_ai_messages_summary_{entry_id}", {"rodzic": "Brak wiadomości na dziś.", "uczen": "Brak wiadomości na dziś."})
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
            
        if result_text.startswith("```json"):
            result_text = result_text.replace("```json", "", 1)
        if result_text.endswith("```"):
            result_text = result_text.rsplit("```", 1)[0]
            
        result_json = json.loads(result_text.strip())
        
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

