# 🎓 Librus APIX Integration for Home Assistant

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/LukMaverick)

Integracja Home Assistant z systemem Librus Synergia, umożliwiająca monitorowanie ocen, wiadomości i innych danych szkolnych.

## ✨ Funkcje

- 📊 **Monitoring ocen** - wszystkie oceny ze wszystkich przedmiotów
- 📈 **Statystyki** - średnie ocen, liczba ocen, trend
- 📧 **Wiadomości** - najnowsze wiadomości z dziennika
- 📅 **Kalendarze** - wbudowany plan lekcji i terminarz w HA
- ✅ **Zadania domowe** - wsparcie dla systemowych list To-Do
- 📢 **Ogłoszenia** - odczyt szkolnej tablicy ogłoszeń
- 👨‍🎓 **Frekwencja** - monitorowanie spóźnień i nieobecności
- 🔔 **Powiadomienia** - automatyczne powiadomienia o nowych ocenach/wiadomościach
- 🏠 **Dashboard** - piękne karty w Home Assistant

## 🚀 Sensory

Integracja tworzy następujące sensory:

| Sensor | Opis | Wartość |
|--------|------|---------|
| `sensor.librus_uczen` | Informacje o uczniu (klasa, wychowawca, szkoła) | imię i nazwisko |
| `sensor.librus_szczesliwy_numerek` | Szczęśliwy numerek dnia | numer |
| `sensor.librus_oceny` | Wszystkie oceny bieżącego semestru | liczba ocen |
| `sensor.librus_srednia_ocen` | **Globalna średnia** ze wszystkich przedmiotów | float (wykres 📈) |
| `sensor.librus_wiadomosci` | Ostatnie 5 wiadomości z pełną treścią | liczba nieprzeczytanych |
| `sensor.librus_<przedmiot>` | Oceny z danego przedmiotu (np. `sensor.librus_matematyka`) | lista ocen: "4, 3+, 5" |
| `sensor.librus_srednia_<przedmiot>` | **Średnia** z danego przedmiotu (np. `sensor.librus_srednia_matematyka`) | float (wykres 📈) |
| `sensor.librus_plan_lekcji` | Plan lekcji na pełne 7 dni z rozbiciem na dni tygodnia | - |
| `sensor.librus_frekwencja` | Lista nieobecności i spóźnień | liczba nieobecności |
| `sensor.librus_ogloszenia` | Najnowsze ogłoszenia | liczba ogłoszeń |
| `calendar.*_calendar_timetable` | Wbudowany kalendarz lekcji ucznia | wydarzenia |
| `calendar.*_calendar_schedule` | Wbudowany kalendarz sprawdzianów i wydarzeń | wydarzenia |
| `todo.*_todo_homework` | Systemowa lista zadań domowych z terminami oddania | lista zadań |

Sensory średnich mają `state_class: measurement` — HA automatycznie rysuje dla nich wykres historyczny po kliknięciu w encję.

## 📦 Instalacja

### Opcja 1: HACS (Zalecana)

Kliknij poniższy przycisk, aby automatycznie dodać repozytorium do HACS z właściwą kategorią:

[![Otwórz w HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=procaktomasz&repository=LibrusSynergiaHA&category=integration)

Lub ręcznie:

1. Otwórz HACS w Home Assistant
2. Kliknij trzy kropki (⋮) w prawym górnym rogu
3. Wybierz **"Custom repositories"**
4. W polu URL wpisz dokładnie: `https://github.com/procaktomasz/LibrusSynergiaHA`  
   ⚠️ **Bez `.git` na końcu!**
5. W polu **Category** wybierz: **`Integration`**  
   ⚠️ **NIE wybieraj "AppDaemon", "Plugin" ani żadnej innej opcji!**
6. Kliknij **ADD**
7. Znajdź **"Librus Synergia HA"** na liście i zainstaluj
8. Restartuj Home Assistant

> **Uwaga:** Błąd *"is not a valid app repository"* pojawia się, gdy w kroku 5 zostanie wybrana nieprawidłowa kategoria (np. "AppDaemon"). Upewnij się, że wybrano **Integration**.

### Opcja 2: Instalacja manualna

1. Skopiuj folder `custom_components/librus_apix` do `config/custom_components/`
2. Restartuj Home Assistant
3. Idź do Konfiguracja > Integracje > Dodaj integrację
4. Wyszukaj "Librus APIX"

## ⚙️ Konfiguracja

1. W Home Assistant: **Konfiguracja** > **Integracje** > **Dodaj integrację**
2. Wyszukaj **"Librus APIX"**  
3. Podaj swoje dane logowania do Librus Synergia:
   - **Login/Username**: Twój login do Librus
   - **Hasło**: Twoje hasło do Librus
4. Kliknij **"Prześlij"**


## 📊 Przykładowe karty Lovelace

### Karta ocen i średnich
```yaml
type: entities
title: "📚 Oceny Librus"
entities:
  - entity: sensor.librus_srednia_ocen
    name: "Globalna średnia"
  - entity: sensor.librus_oceny
    name: "Liczba ocen"
  - entity: sensor.librus_szczesliwy_numerek
    name: "Szczęśliwy numerek"
```

### Karta wiadomości (Markdown - Dynamiczna)

Ta karta automatycznie dostosowuje się do ilości wiadomości i nie wyświetla pustych wierszy!

> **WAŻNE:** Znajdź nazwę encji w **Developer Tools → States** (szukaj `wiadomosci`). 
> Pamiętaj, aby we wszystkich poniższych kodach zmienić `sensor.librus_imie_nazwisko_...` na poprawną nazwę swojej encji!

```yaml
type: markdown
title: 📬 Wiadomości Librus
content: >
  {% set msgs = state_attr('sensor.librus_imie_nazwisko_wiadomosci', 'wiadomosci') %}
  {% set nieprzeczytane = state_attr('sensor.librus_imie_nazwisko_wiadomosci', 'liczba_nieprzeczytanych') %}
  
  **Status:** {% if nieprzeczytane > 0 %}🔴 {{ nieprzeczytane }} nieprzeczytanych{% else %}⚫ Wszystkie przeczytane{% endif %}
  
  ***

  {% if msgs %}
    {% for m in msgs %}
      {% if m.temat != 'Brak' %}
  **{{ m.data }}** | {{ m.nadawca }}
  > {% if m.nieprzeczytana %}🔴{% else %}⚫{% endif %} **{{ m.temat }}** {% if m.ma_zalacznik %}📎{% endif %}
  
  <br>
      {% endif %}
    {% endfor %}
  {% else %}
    Brak wiadomości.
  {% endif %}
```

Legenda ikon:
- 🔴 czerwona = nieprzeczytana
- ⚫ szara = przeczytana
- 📎 = ma załącznik

### Karta terminarza (wszystkie zdarzenia)

> **WAŻNE:** Znajdź nazwę encji w **Developer Tools → States** (szukaj `terminarz`).
> Zastąp `sensor.librus_imie_nazwisko_terminarz` w poniższym kodzie swoją własną nazwą!

```yaml
type: markdown
title: 📅 Terminarz
content: >
  {% set zdarzenia = state_attr('sensor.librus_imie_nazwisko_terminarz',
  'zdarzenia') %} {% if zdarzenia %} | Data | Dzień | Typ | Przedmiot | Opis |
   |------|-------|-----|-----------|------|
  {% for z in zdarzenia %} | **{{ z.data }}** | {{ z.tydzien }} | {{ z.tytul }}
  | {{ z.przedmiot }} | {{ z.szczegoly.Opis if z.szczegoly.Opis != 'unknown'
  else '' }} |

  {% endfor %} {% else %} Brak nadchodzących zdarzeń. {% endif %}
```

### Karta sprawdzianów i klasówek (bez dni wolnych)

> **WAŻNE:** Pamiętaj, aby podmienić w kodzie `sensor.librus_imie_nazwisko_terminarz` na nazwę z Twojego systemu!

```yaml
type: markdown
title: 📝 Sprawdziany i klasówki
content: >
  {% set zdarzenia = state_attr('sensor.librus_imie_nazwisko_terminarz',
  'zdarzenia') %} {% set typy_testow = ['Sprawdzian', 'Kartkówka', 'Klasówka',
  'Praca klasowa'] %} {% set sprawdziany = zdarzenia | selectattr('tytul', 'in',
  typy_testow) | list %} {% if sprawdziany %} | Data | Dzień | Typ | Przedmiot |
  Opis |
   |------|-------|-----|-----------|------|
  {% for z in sprawdziany %} | **{{ z.data }}** | {{ z.tydzien }} | {{ z.tytul
  }} | {{ z.przedmiot }} | {{ z.szczegoly.Opis if z.szczegoly.Opis != 'unknown'
  else '' }} |

  {% endfor %} {% else %} Brak nadchodzących zdarzeń. {% endif %}
```

### Karta natywnego Kalendarza (Home Assistant)
Zamiast budować tabele markdown dla planu lekcji i sprawdzianów, możesz użyć systemowej karty kalendarza!
```yaml
type: calendar
title: 📅 Szkoła - Plan i Terminarz
entities:
  - calendar.plan_lekcji
  - calendar.terminarz
initial_view: dayGridMonth
```

### Karta Zadań Domowych (To-Do List)
Wyświetl natywną listę kontrolną prac domowych prosto z Librusa!
```yaml
type: todo-list
entity: todo.zadania_domowe
title: ✅ Prace domowe
```

### Karta ogłoszeń i frekwencji (Markdown)

> **WAŻNE:** Pamiętaj, aby podmienić w kodzie `imie_nazwisko` na poprawne dane z Twoich encji!

```yaml
type: markdown
title: 📢 Szkolne Aktualności
content: >
  **Bieżące Ogłoszenia:**
  
  {% set ogl = state_attr('sensor.librus_imie_nazwisko_ogloszenia', 'lista_ogloszen') %}
  {% if ogl %}
    {% for o in ogl %}
      - **{{ o.data }} ({{ o.nadawca }})**: {{ o.tytul }} - {{ o.opis }}
    {% endfor %}
  {% else %}
    Brak nowych ogłoszeń.
  {% endif %}

  ***

  **Statystyki Frekwencji:**
  - Spóźnienia: {{ state_attr('sensor.librus_imie_nazwisko_frekwencja', 'liczba_spoznien') | default(0) }}
  - Nieobecności: {{ state_attr('sensor.librus_imie_nazwisko_frekwencja', 'liczba_nieobecnosci') | default(0) }}
```

### Karta pełnego Planu Lekcji (7 dni) na własnym szablonie Markdown

> **WAŻNE:** Zastąp `sensor.librus_imie_nazwisko_plan_lekcji` poprawną encją z Twojego panelu (Developer Tools → States)!

```yaml
type: markdown
title: 📚 Plan Lekcji na cały tydzień
content: >
  {% set encja = 'sensor.librus_imie_nazwisko_plan_lekcji' %}
  {% set dni = [
    ('Poniedziałek', 'poniedzialek'),
    ('Wtorek', 'wtorek'),
    ('Środa', 'sroda'),
    ('Czwartek', 'czwartek'),
    ('Piątek', 'piatek')
  ] %}

  {% for nazwa, klucz in dni %}
  ### {{ nazwa }}
  {% set lekcje = state_attr(encja, klucz) %}
  {% if lekcje %}
    | Godz. | Przedmiot | Nauczyciel | Sala |
    |---|---|---|---|
    {% for l in lekcje %}
    | {{ l.godzina }} | **{{ l.przedmiot }}** | {{ l.nauczyciel }} | {{ l.sala }} |
    {% endfor %}
  {% else %}
    *Brak lekcji*
  {% endif %}
  
  {% endfor %}
```

### Wykres średniej z przedmiotu (Gauge)
```yaml
type: gauge
entity: sensor.librus_srednia_matematyka
name: "Matematyka - średnia"
min: 1
max: 6
severity:
  green: 4.5
  yellow: 3
  red: 0
```

## 🔔 Automatyzacje powiadomień na telefon

Integracja wysyła zdarzenia Home Assistant gdy pojawi się nowa wiadomość lub ocena.
Zdarzenia są wykrywane przy każdym odświeżeniu (co 2h). Pierwsze uruchomienie tylko zapamiętuje stan — **nie wysyła duplikatów**.

> **Test bez czekania:** Idź do **Developer Tools → Events**, Event type: `librus_apix_nowa_wiadomosc`, Event data jak poniżej i kliknij **Fire Event**.

### 📬 Powiadomienie o nowej wiadomości

Zdarzenie: `librus_apix_nowa_wiadomosc`  
Dostępne dane: `nadawca`, `temat`, `data`, `ma_zalacznik`

> **Uwaga:** Treść wiadomości nie jest pobierana celowo — aby nie oznaczać wiadomości jako przeczytanych w Librusie.

```yaml
automation:
  - alias: "Librus - nowa wiadomosc"
    trigger:
      - platform: event
        event_type: librus_apix_nowa_wiadomosc
    action:
      - service: notify.mobile_app_NAZWA_TWOJEGO_TELEFONU
        data:
          title: "📬 Librus: nowa wiadomość"
          message: >-
            {% set msg = state_attr('sensor.librus_IMIE_NAZWISKO_wiadomosci', 'wiadomosci')
               | selectattr('nieprzeczytana', 'equalto', true) | list | first | default({}) %}
            Od: {{ msg.nadawca | default('nieznany') }}
            Temat: {{ msg.temat | default('brak') }}
```

> **Uwaga:** Zamień `sensor.librus_IMIE_NAZWISKO_wiadomosci` na nazwę swojego sensora widoczną w Developer Tools → States.

### 📝 Powiadomienie o nowej ocenie

Zdarzenie: `librus_apix_nowa_ocena`  
Dostępne dane: `przedmiot`, `ocena`, `data`, `kategoria`, `nauczyciel`

```yaml
automation:
  - alias: "Librus - nowa ocena"
    trigger:
      platform: event
      event_type: librus_apix_nowa_ocena
    action:
      - service: notify.mobile_app_NAZWA_TWOJEGO_TELEFONU
        data:
          title: "🎓 Librus: nowa ocena {{ trigger.event.data.ocena }}"
          message: >-
            {{ trigger.event.data.przedmiot }}
            Ocena: {{ trigger.event.data.ocena }}
            Kategoria: {{ trigger.event.data.kategoria }}
            Nauczyciel: {{ trigger.event.data.nauczyciel }}
```

> **Gdzie znaleźć nazwę telefonu?** HA → Settings → Devices & Services → Mobile App → nazwa urządzenia (np. `notify.mobile_app_samsung_galaxy_s24`)



## 📝 Logi

Aby włączyć szczegółowe logi, dodaj do `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.librus_apix: debug
```

## ⚠️ Bezpieczeństwo

- **Nie udostępniaj swoich danych logowania!**  
- Dane są przechowywane lokalnie w Home Assistant
- Komunikacja z Librus odbywa się przez bezpieczne API
- Hasła są zaszyfrowane w konfiguracji

## 🐛 Zgłaszanie błędów

Jeśli znajdziesz błąd:

1. Włącz logi debug (patrz wyżej)
2. Skopiuj logi z błędem
3. Utwórz issue na GitHub z:
   - Opisem problemu
   - Krokami do reprodukcji
   - Logami (usuń dane osobowe!)

## 📄 Licencja

MIT License - patrz [LICENSE](LICENSE)

## 🤝 Wkład

Pull requesty są mile widziane! Sprawdź [CONTRIBUTING.md](CONTRIBUTING.md)

### 🙏 Podziękowania

Specjalne podziękowania dla **KB** za wsparcie i pomoc w rozwoju projektu.

## 👨‍💻 Autor

Stworzono na bazie biblioteki [librus-apix](https://github.com/RustySnek/librus-apix)

---

**⭐ Jeśli podoba Ci się projekt, zostaw gwiazdkę na GitHub!**

## ☕ Wesprzyj projekt

Jeśli integracja jest dla Ciebie przydatna, możesz postawić kawę 😊

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/LukMaverick)