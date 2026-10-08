import logging
import json
from homeassistant.core import HomeAssistant
from homeassistant.components import conversation
from homeassistant.helpers.dispatcher import async_dispatcher_send

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
    
    default_prompt = f"""
Na podstawie poniższych danych z dziennika elektronicznego ucznia ({imie}), przygotuj dwa oddzielne, krótkie podsumowania tygodnia (każde po około 3-4 zdania).

DANE:
Nowe oceny w tym tygodniu:
{chr(10).join(oceny) if oceny else "Brak nowych ocen"}

Frekwencja (bieżący semestr): {frekwencja.get("procent_semestr", "Brak danych")}%
Zarejestrowane problemy z frekwencją (ilość): {json.dumps(nieobecnosci) if nieobecnosci else "Brak spóźnień i nieobecności"}

Najbliższe zadania/sprawdziany:
{chr(10).join([f"- {z.get('przedmiot')}: {z.get('kategoria')} (termin: {z.get('termin')})" for z in zadania]) if zadania else "Brak nadchodzących sprawdzianów"}

INSTRUKCJA ZWROTU:
Zwróć odpowiedź w formacie JSON (bez znaczników markdown typu ```json), zawierającym dwa klucze:
1. "rodzic" - podsumowanie skierowane do rodzica (obiektywne, wskazujące co poszło dobrze, a na co trzeba zwrócić uwagę w nadchodzącym tygodniu).
2. "uczen" - podsumowanie skierowane bezpośrednio do ucznia ({imie}) (w drugiej osobie, motywujące, chwalące za sukcesy i zachęcające do poprawy).

Format odpowiedzi:
{{
  "rodzic": "Twój tekst dla rodzica...",
  "uczen": "Twój tekst dla ucznia..."
}}
"""

    prompt = options.get("ai_prompt_weekly")
    if prompt:
        prompt = prompt.replace("{imie}", imie).replace("{oceny}", chr(10).join(oceny) if oceny else "Brak nowych ocen").replace("{frekwencja}", str(frekwencja.get("procent_semestr", "Brak danych"))).replace("{zadania}", chr(10).join([f"- {z.get('przedmiot')}: {z.get('kategoria')} (termin: {z.get('termin')})" for z in zadania]) if zadania else "Brak nadchodzących sprawdzianów")
    else:
        prompt = default_prompt


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
    
    dzisiejsze = [m for m in wiadomosci if m.get("date", "").startswith(today_str)]
    
    nieprzeczytane = []
    przeczytane = []
    
    for m in dzisiejsze:
        title = m.get("title", "")
        author = m.get("author", "")
        content = m.get("content", "Brak pobranej treści")
        
        info = f"Od: {author}\nTemat: {title}\nTreść: {content}"
        
        if m.get("unread"):
            nieprzeczytane.append(info)
        else:
            przeczytane.append(info)
            
    stats = f"Dzisiaj przyszło {len(dzisiejsze)} wiadomości, z czego {len(nieprzeczytane)} jest nieprzeczytanych."
    
    if not dzisiejsze:
        _LOGGER.info("Brak wiadomości z dzisiaj. Pomijam AI.")
        async_dispatcher_send(hass, f"librus_ai_messages_summary_{entry_id}", {"rodzic": "Brak wiadomości na dziś.", "uczen": "Brak wiadomości na dziś."})
        return
        
    dane_tekst = f"STATYSTYKI:\n{stats}\n\nNIEPRZECZYTANE:\n"
    dane_tekst += "\n---\n".join(nieprzeczytane) if nieprzeczytane else "Brak"
    dane_tekst += "\n\nPRZECZYTANE:\n"
    dane_tekst += "\n---\n".join(przeczytane) if przeczytane else "Brak"

    default_prompt_parent = f"""
Jesteś asystentem zajętego rodzica. Przeanalizuj poniższe dzisiejsze wiadomości ze szkoły (uczeń: {imie}). 
Podaj zwięzłe streszczenie w punktach. Wyodrębnij to co ważne: wywiadówki, składki, problemy wychowawcze, zapowiedzi.

DANE Z DZIENNIKA:
{dane_tekst}
"""

    default_prompt_student = f"""
Jesteś asystentem ucznia ({imie}). Przeanalizuj poniższe dzisiejsze wiadomości ze szkoły. 
Napisz krótkie, luźne streszczenie. Skup się tylko na tym, co uczeń musi zrobić (zadania, sprawdziany, przyniesienie czegoś). Zignoruj wiadomości dla rodziców.

DANE Z DZIENNIKA:
{dane_tekst}
"""

    prompt_parent = options.get("ai_prompt_messages_parent")
    if prompt_parent:
        prompt_parent = prompt_parent.replace("{imie}", imie).replace("{wiadomosci}", dane_tekst)
    else:
        prompt_parent = default_prompt_parent
        
    prompt_student = options.get("ai_prompt_messages_student")
    if prompt_student:
        prompt_student = prompt_student.replace("{imie}", imie).replace("{wiadomosci}", dane_tekst)
    else:
        prompt_student = default_prompt_student

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

