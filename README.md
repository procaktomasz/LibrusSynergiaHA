# 🎓 Librus APIX Integration for Home Assistant

Integracja Home Assistant z systemem Librus Synergia, umożliwiająca monitorowanie ocen, wiadomości, frekwencji i innych danych szkolnych. 
W najnowszej wersji wprowadziliśmy także wsparcie dla **Sztucznej Inteligencji** do analizy i podsumowywania wyników!

## ✨ Funkcje i Nowości (v3.0)

- 🤖 **Tygodniowe Podsumowanie AI (NOWOŚĆ)** - generowanie inteligentnych raportów z postępów (osobno dla rodzica i ucznia).
- 🧠 **Adaptacyjne odświeżanie i Cache (NOWOŚĆ)** - inteligentne odpytywanie Librusa (rzadziej w nocy) i odporność na awarie dziennika.
- 🎮 **Nauka i To-Do (NOWOŚĆ)** - interaktywna lista "Przygotowanie do lekcji" przypominająca o sprawdzianach (gamifikacja).
- 📬 **Pobieranie treści wiadomości (NOWOŚĆ)** - nowa usługa `get_message` i pełna kontrola nad statusem "przeczytane".
- 🚨 **Uwagi o zachowaniu (NOWOŚĆ)** - nowy czujnik monitorujący uwagi pozytywne i negatywne.
- ⚡ **Zdarzenia / Events (NOWOŚĆ)** - automatyzacje oparte na eventach (np. `librus_apix_nowa_ocena`).
- 📊 **Monitoring ocen** - wszystkie oceny ze wszystkich przedmiotów
- 📈 **Statystyki** - średnie ocen, liczba ocen, trend
- 📅 **Kalendarze** - wbudowany plan lekcji (z obsługą zastępstw!) i terminarz w HA
- ✅ **Zadania domowe** - wsparcie dla systemowych list To-Do
- 📢 **Ogłoszenia** - odczyt szkolnej tablicy ogłoszeń
- 👨‍🎓 **Frekwencja** - monitorowanie spóźnień i nieobecności

## 🚀 Sensory

Integracja tworzy następujące sensory:

| Sensor | Opis | Wartość |
|--------|------|---------|
| `sensor.librus_uczen` | Informacje o uczniu (klasa, wychowawca, szkoła) | imię i nazwisko |
| `sensor.librus_szczesliwy_numerek` | Szczęśliwy numerek dnia | numer |
| `sensor.librus_oceny` | Wszystkie oceny bieżącego semestru | liczba ocen |
| `sensor.librus_srednia_ocen` | **Globalna średnia** ze wszystkich przedmiotów | float (wykres 📈) |
| `sensor.librus_wiadomosci` | Ostatnie wiadomości (domyślnie 10, konfigurowalne) | liczba nieprzeczytanych |
| `sensor.librus_uwagi` | (NOWOŚĆ) Uwagi o zachowaniu z podziałem na typy | liczba uwag |
| `sensor.librus_<przedmiot>` | Oceny z danego przedmiotu (np. `sensor.librus_matematyka`) | lista ocen: "4, 3+, 5" |
| `sensor.librus_srednia_<przedmiot>` | **Średnia** z danego przedmiotu | float (wykres 📈) |
| `sensor.librus_plan_lekcji` | Plan lekcji na pełne 7 dni z rozbiciem na dni tygodnia | - |
| `sensor.librus_frekwencja` | Lista nieobecności i spóźnień, rozbicie oraz **frekwencja w %** | liczba nieobecności |
| `sensor.librus_tematy_lekcji` | **Tematy zrealizowanych lekcji** z ostatnich 7 dni | liczba lekcji dzisiaj |
| `sensor.librus_ogloszenia` | Najnowsze ogłoszenia | liczba ogłoszeń |
| `sensor.librus_ai_summary_rodzic` | (NOWOŚĆ) Inteligentny raport dla rodzica | Pełny tekst raportu |
| `sensor.librus_ai_summary_uczen` | (NOWOŚĆ) Inteligentny raport motywujący dla ucznia | Pełny tekst raportu |
| `calendar.*_calendar_timetable` | Wbudowany kalendarz lekcji ucznia | wydarzenia |
| `calendar.*_calendar_schedule` | Wbudowany kalendarz sprawdzianów i wydarzeń | wydarzenia |
| `todo.*_todo_zadania_domowe_to_do` | Systemowa lista zadań domowych z terminami oddania | lista zadań |
| `todo.*_todo_nauka_to_do` | (NOWOŚĆ) Systemowa lista przygotowań do sprawdzianów | przypomnienia |
| `binary_sensor.*_nauka_odrobiona` | (NOWOŚĆ) Czujnik informujący, czy uczeń odrobił naukę | ON / OFF |
| `button.*_generuj_podsumowanie_ai` | (NOWOŚĆ) Przycisk generujący raport AI | - |
| `switch.*_automatyczne_podsumowanie_ai`| (NOWOŚĆ) Przełącznik automatycznego raportowania AI | - |

Sensory średnich mają `state_class: measurement` — HA automatycznie rysuje dla nich wykres historyczny po kliknięciu w encję.

### 📚 Moduł Nauki i Zadań (To-Do)

Integracja dostarcza interaktywne listy zadań (To-Do) połączone z kalendarzem Librusa, pozwalające na tworzenie automatyzacji opartych na gamifikacji (np. blokada konsoli, dopóki sprawdziany nie zostaną "odklikane").

1. **Zadania domowe (`todo.librus_[uczen]_zadania_domowe_to_do`)** – Automatycznie synchronizowana, podglądowa lista bieżących zadań nadanych przez nauczycieli w systemie. (Z powodu ograniczeń API Librusa, jest tylko do odczytu).
2. **Przygotowanie do lekcji (`todo.librus_[uczen]_przygotowanie_do_lekcji_to_do`)** – *[NOWOŚĆ]* Interaktywna lista wyzwań. Integracja automatycznie generuje i dodaje przypomnienia o nauce do każdego zbliżającego się w Terminarzu sprawdzianu, kartkówki czy klasówki. W Opcjach integracji sam ustalasz, na ile dni przed sprawdzianem przypomnienie ma trafić na listę. Uczeń może samodzielnie wykreślić ten punkt jako zrobiony bezpośrednio w interfejsie HA (stan zapisuje się na stałe).

🎮 **Wskazówka:** Do dyspozycji masz ukrytą encję `binary_sensor.librus_[uczen]_nauka_odrobiona`. Przyjmuje ona stan `WŁĄCZONY (on)` tylko wtedy, gdy na interaktywnej liście przygotowań do lekcji nie zalegają żadne nieodkliknięte sprawdziany z nadchodzących dni. 
To najprostsza metoda na stworzenie w Home Assistant warunku blokującego dostęp do sprzętu rozrywkowego!

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
3. Podaj swoje dane logowania do Librus Synergia.
4. Kliknij **"Prześlij"**

*(Aby włączyć Podsumowania AI, po zainstalowaniu kliknij "Konfiguruj" na karcie integracji i zaznacz odpowiednie opcje).*

### ⚠️ Ważne: Optymalizacja bazy danych (Recorder)
Niektóre sensory przechowują potężne struktury JSON. Zaleca się wykluczenie ich z zapisu do historii w pliku `configuration.yaml`:

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.librus_*_plan_lekcji
      - sensor.librus_*_wiadomosci
      - sensor.librus_*_terminarz
      - sensor.librus_*_zadania
      - sensor.librus_*_ogloszenia
      - sensor.librus_*_oceny
      - sensor.librus_*_tematy_lekcji
      - sensor.librus_*_frekwencja
```

## 📊 Przykładowe karty Lovelace

### NOWOŚĆ: Karta Tygodniowego Podsumowania AI
```yaml
type: custom:stack-in-card
cards:
  - type: custom:mushroom-title-card
    title: 🤖 Podsumowanie Tygodnia (AI)
    subtitle: Co słychać w szkole?
  - type: markdown
    content: >
      {% set profil = 'imie_nazwisko' %}
      {% set encja = 'sensor.librus_' ~ profil ~ '_ai_summary_rodzic' %}
      {% set raport = state_attr(encja, 'pełny_tekst') %}
      
      {% if raport %}
        {{ raport }}
      {% else %}
        Asystent AI jeszcze nie wygenerował raportu. Naciśnij przycisk odświeżania!
      {% endif %}
  - type: button
    tap_action:
      action: toggle
    entity: button.librus_imie_nazwisko_generuj_podsumowanie_ai
    name: Generuj nowe podsumowanie
    icon: mdi:robot-excited
```

### NOWOŚĆ: Karta Uwag o Zachowaniu
```yaml
type: markdown
title: 🚨 Uwagi o Zachowaniu
content: |
  {% set profil = 'imie_nazwisko' %}
  {% set encja = 'sensor.librus_' ~ profil ~ '_uwagi' %}
  {% set uwagi = state_attr(encja, 'lista_uwag') %}

  {% if uwagi == none %}
  ⚠️ Błąd: Nie znaleziono encji.
  {% elif uwagi | length > 0 %}
  {% for u in uwagi %}
  **{{ u.data }}** ({{ u.nauczyciel }}) 
  > {% if u.typ == 'Positive' %}🟢{% elif u.typ == 'Negative' %}🔴{% else %}⚪{% endif %} **{{ u.kategoria }}**
  > {{ u.tresc | replace('\n', ' ') }}
  
  {% endfor %}
  {% else %}
  ✅ Dziecko jest aniołem - brak uwag w dzienniku!
  {% endif %}
```

### Karta ocen i średnich

> **WAŻNE:** Pamiętaj, aby we wszystkich poniższych nazwach zmienić `imie_nazwisko` na poprawne dane z Twoich encji!

```yaml
type: entities
title: "📚 Oceny Librus"
entities:
  - entity: sensor.librus_imie_nazwisko_srednia_ocen
    name: "Globalna średnia"
  - entity: sensor.librus_imie_nazwisko_oceny
    name: "Liczba ocen"
  - entity: sensor.librus_imie_nazwisko_szczesliwy_numerek
    name: "Szczęśliwy numerek"
```

### Dynamiczna karta wszystkich ocen (Markdown)

Ta karta automatycznie wylistuje wszystkie przedmioty, pokaże ich średnie oraz ciąg wystawionych ocen, naśladując wygląd tabeli prosto ze strony Librusa.

```yaml
type: markdown
title: "Oceny"
content: |
  {% set profil = 'imie_nazwisko' %}
  
  {% set encja_oceny = 'sensor.librus_' ~ profil ~ '_oceny' %}
  {% set encja_srednia = 'sensor.librus_' ~ profil ~ '_srednia_ocen' %}
  
  | Przedmiot | Wszystkie Oceny | Średnia |
  | :--- | :--- | :---: |
  {%- set przedmioty = state_attr(encja_oceny, 'oceny_wg_przedmiotu') %}
  {%- set srednie = state_attr(encja_srednia, 'srednie_wg_przedmiotow') %}
  {%- if przedmioty %}
    {%- for nazwa, oceny in przedmioty.items() %}
  | **{{ nazwa }}** | {% for o in oceny %}{{ o.ocena }}{% if not loop.last %}, {% endif %}{% endfor %} | **{{ srednie.get(nazwa, '-') if srednie else '-' }}** |
    {%- endfor %}
  {%- else %}
  | Brak danych dla wpisanego profilu | - | - |
  {%- endif %}
```

> **Wskazówka:** Domyślnie Home Assistant dopasowuje szerokość tabel w kartach Markdown do ich zawartości tekstu. Aby zmusić tabelę do zajęcia pełnej szerokości, użyj popularnego dodatku **card-mod**:
> ```yaml
> card_mod:
>   style:
>     ha-markdown $: |
>       table { width: 100% !important; }
> ```

### Karta wiadomości (Markdown - Dynamiczna)

Ta karta automatycznie dostosowuje się do ilości wiadomości i nie wyświetla pustych wierszy!

```yaml
type: markdown
title: 📬 Wiadomości Librus
content: |
  {% set profil = 'imie_nazwisko' %}
  {% set encja = 'sensor.librus_' ~ profil ~ '_wiadomosci' %}
  {% set msgs = state_attr(encja, 'wiadomosci') %}

  {% if msgs == none %}
  ⚠️ **Błąd:** Nie znaleziono encji `{{ encja }}`.
  {% else %}
  {% set nieprzeczytane = state_attr(encja, 'liczba_nieprzeczytanych') | default(0) %}
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
  {% endif %}
  {% endif %}
```

### Karta wiadomości (Markdown - Pełna treść)

> **WAŻNE:** Aby poniższa karta działała poprawnie, musisz włączyć opcję *"Pobieraj pełną treść wiadomości"* w ustawieniach integracji.

```yaml
type: markdown
title: ✉️ Wiadomości Librus (Z treścią)
content: |
  {% set profil = 'imie_nazwisko' %}
  {% set encja = 'sensor.librus_' ~ profil ~ '_wiadomosci' %}
  {% set msgs = state_attr(encja, 'wiadomosci') %}

  {% if msgs == none %}
  ❌ **Błąd:** Nie znaleziono encji `{{ encja }}`.
  {% else %}
  {% set nieprzeczytane = state_attr(encja, 'liczba_nieprzeczytanych') | default(0) %}
  **Status:** {% if nieprzeczytane > 0 %}🔴 {{ nieprzeczytane }} nieprzeczytanych{% else %}🟢 Wszystkie przeczytane{% endif %}

  ***
  {% if msgs %}
  {% for m in msgs %}
  {% if m.temat != 'Brak' %}
  **{{ m.data }}** | {{ m.nadawca }}
  > {% if m.nieprzeczytana %}🔴{% else %}⚫{% endif %} **{{ m.temat }}** {% if m.ma_zalacznik %}📎{% endif %}
  > 
  > {{ m.tresc | default('Brak pobranej treści') }}

  <br>
  {% endif %}
  {% endfor %}
  {% endif %}
  {% endif %}
```

### Karta terminarza (wszystkie zdarzenia)

```yaml
type: markdown
title: 📅 Terminarz
content: |
  {% set profil = 'imie_nazwisko' %}
  {% set encja = 'sensor.librus_' ~ profil ~ '_terminarz' %}
  {% set zdarzenia = state_attr(encja, 'zdarzenia') %}

  {% if zdarzenia == none %}
  ⚠️ **Błąd:** Nie znaleziono encji `{{ encja }}`.
  {% elif zdarzenia | length > 0 %}
  | Data | Dzień | Typ | Przedmiot | Opis |
  |------|-------|-----|-----------|------|
  {% for z in zdarzenia %} | **{{ z.data }}** | {{ z.tydzien }} | {{ z.tytul }} | {{ z.przedmiot }} | {{ z.szczegoly.get('Opis', '') | replace('\n', '<br>') if z.szczegoly.get('Opis', 'unknown') != 'unknown' else '' }} |
  {% endfor %}
  {% else %} 
  Brak nadchodzących zdarzeń. 
  {% endif %}
```

### Karta sprawdzianów i klasówek (bez dni wolnych)

```yaml
type: markdown
title: 📝 Sprawdziany i klasówki
content: |
  {% set profil = 'imie_nazwisko' %}
  {% set encja = 'sensor.librus_' ~ profil ~ '_terminarz' %}
  {% set zdarzenia = state_attr(encja, 'zdarzenia') %}

  {% if zdarzenia == none %}
  ⚠️ **Błąd:** Nie znaleziono encji `{{ encja }}`.
  {% else %}
  {% set typy_testow = ['Sprawdzian', 'Kartkówka', 'Klasówka', 'Praca klasowa'] %}
  {% set sprawdziany = zdarzenia | selectattr('tytul', 'in', typy_testow) | list %} 

  {% if sprawdziany | length > 0 %}
  | Data | Dzień | Typ | Przedmiot | Opis |
  |------|-------|-----|-----------|------|
  {% for z in sprawdziany %} | **{{ z.data }}** | {{ z.tydzien }} | {{ z.tytul }} | {{ z.przedmiot }} | {{ z.szczegoly.get('Opis', '') | replace('\n', '<br>') if z.szczegoly.get('Opis', 'unknown') != 'unknown' else '' }} |
  {% endfor %}
  {% else %} 
  Brak nadchodzących sprawdzianów. 
  {% endif %}
  {% endif %}
```

### Karta natywnego Kalendarza (Home Assistant)

Zamiast budować tabele markdown dla planu lekcji i sprawdzianów, możesz użyć systemowej karty kalendarza!
```yaml
type: calendar
title: 📅 Szkoła - Plan i Terminarz
entities:
  - calendar.librus_imie_nazwisko_plan_lekcji_kalendarz
  - calendar.librus_imie_nazwisko_terminarz_kalendarz
initial_view: dayGridMonth
```

### Karta Zadań Domowych (To-Do List)

Wyświetl natywną listę kontrolną prac domowych prosto z Librusa!
```yaml
type: todo-list
entity: todo.librus_imie_nazwisko_zadania_domowe_to_do
title: ✅ Prace domowe
```

### Karta ogłoszeń szkolnych (Markdown)

```yaml
type: markdown
title: 📢 Szkolne Aktualności
content: |
  {% set profil = 'imie_nazwisko' %}
  {% set encja_ogl = 'sensor.librus_' ~ profil ~ '_ogloszenia' %}
  {% set ogl = state_attr(encja_ogl, 'lista_ogloszen') %}

  {% if ogl == none %}
  ⚠️ **Błąd:** Nie znaleziono encji.
  {% else %}
  {% if ogl | length > 0 %}
  {% for o in ogl %}
  - **{{ o.data }} ({{ o.nadawca }})**: {{ o.tytul }} - {{ o.opis }}
  {% endfor %}
  {% else %}
  Brak nowych ogłoszeń.
  {% endif %}
  {% endif %}
```

### Karta statystyk frekwencji (Markdown)

```yaml
type: markdown
title: 📊 Statystyki Frekwencji
content: |
  {% set profil = 'imie_nazwisko' %}
  {% set encja_frek = 'sensor.librus_' ~ profil ~ '_frekwencja' %}

  {% if states(encja_frek) in ['unavailable', 'unknown'] %}
  ⚠️ **Błąd:** Nie znaleziono encji.
  {% else %}
  - **Frekwencja w semestrze:** {{ state_attr(encja_frek, 'frekwencja_procent') | default('-', true) }}%
  - **Spóźnienia:** {{ state_attr(encja_frek, 'liczba_spoznien') | default(0) }}
  - **Nieobecności:** {{ state_attr(encja_frek, 'liczba_nieobecnosci') | default(0) }}
    (nieusprawiedliwione: {{ state_attr(encja_frek, 'liczba_nieusprawiedliwionych') | default(0) }},
    usprawiedliwione: {{ state_attr(encja_frek, 'liczba_usprawiedliwionych') | default(0) }})
  {% endif %}
```

### Karta tematów lekcji (Markdown)

```yaml
type: markdown
title: 📖 Tematy lekcji
content: |
  {% set profil = 'imie_nazwisko' %}
  {% set lekcje = state_attr('sensor.librus_' ~ profil ~ '_tematy_lekcji', 'lekcje') %}
  {% if lekcje == none %}
  ⚠️ **Błąd:** Nie znaleziono encji.
  {% else %}
  {% for dzien, lista in lekcje | groupby('data') | reverse %}
  #### {{ dzien }}
  {% for l in lista %}
  `{{ l.numer }}` **{{ l.przedmiot }}**{{ ' 🔄 ' ~ l.zastepca if l.zastepstwo }}{{ ' ❗' ~ l.obecnosc if l.obecnosc in ['nb', 'u', 'sp'] }} – {{ l.temat | replace('\n', ' ') }}<br>
  {% endfor %}
  {% else %}
  Brak zrealizowanych lekcji w ostatnich 7 dniach.
  {% endfor %}
  {% endif %}
```

### Karta pełnego Planu Lekcji (7 dni) na własnym szablonie Markdown

> **WAŻNE:** Zastępstwa są automatycznie oznaczane w tabeli czytelną strzałką (np. `stara lekcja ➔ nowa lekcja`).

```yaml
type: markdown
title: 📚 Plan Lekcji na cały tydzień
content: |
  {% set profil = 'imie_nazwisko' %}
  {% set encja = 'sensor.librus_' ~ profil ~ '_plan_lekcji' %}
  {% set dni = state_attr(encja, 'kolejne_7_dni') %}
  
  {% if dni == none %}
  ⚠️ **Błąd:** Nie znaleziono encji.
  {% else %}
  {% for dzien in dni %}
  {% set lekcje = dzien.lekcje %}
  {% if lekcje | length > 0 %}
  ### {{ dzien.dzien_tygodnia }} ({{ dzien.data }}) - Zajęcia od {{ lekcje[0].godzina_od }} do {{ lekcje[-1].godzina_do }}
  | Godz. | Przedmiot | Nauczyciel i Sala |
  |---|---|---|
  {% for l in lekcje %} | {{ l.godzina_od }}-{{ l.godzina_do }} | {% if l.get('odwolana') %}~~{{ l.przedmiot }}~~{% elif l.get('zastepstwo') %}**<font color="#3366cc">{{ l.przedmiot }}</font>**{% elif l.get('zdarzenie') == 'Sprawdzian' %}**<font color="#cc0000ff">{{ l.przedmiot }}</font>**{% elif l.get('zdarzenie') == 'Kartkówka' %}**<font color="#cc9600ff">{{ l.przedmiot }}</font>**{% else %}**{{ l.przedmiot }}**{% endif %} | {{ l.nauczyciel_i_sala }} |
  {% endfor %}
  {% else %}
  ### {{ dzien.dzien_tygodnia }} ({{ dzien.data }})
  *Brak lekcji*
  {% endif %}
  {% endfor %}
  {% endif %}
```

### Wykres średniej z przedmiotu (Gauge)

```yaml
type: gauge
entity: sensor.librus_imie_nazwisko_srednia_matematyka
name: "Matematyka - średnia"
min: 1
max: 6
severity:
  green: 4.5
  yellow: 3
  red: 0
```

## 🔔 Zdarzenia (Events) i Powiadomienia na telefon

Integracja od wersji 3.0 wysyła automatyczne zdarzenia (Events), kiedy wykryje nowości (bez generowania duplikatów).

### 📝 Powiadomienie o nowej ocenie
Zdarzenie: `librus_apix_nowa_ocena`  
Dostępne dane: `uczen`, `przedmiot`, `ocena`, `data`, `kategoria`, `nauczyciel`

```yaml
automation:
  - alias: "Librus - Nowa Ocena"
    trigger:
      - platform: event
        event_type: librus_apix_nowa_ocena
    action:
      - service: notify.notify
        data:
          title: "🎓 {{ trigger.event.data.uczen }} - nowa ocena {{ trigger.event.data.ocena }}"
          message: >-
            {{ trigger.event.data.przedmiot }}
            Ocena: {{ trigger.event.data.ocena }}
            Kategoria: {{ trigger.event.data.kategoria }}
            Nauczyciel: {{ trigger.event.data.nauczyciel }}
```

### 📬 Powiadomienie o nowej wiadomości
Zdarzenie: `librus_apix_nowa_wiadomosc`  
Dostępne dane: `uczen`, `nadawca`, `temat`, `data`, `ma_zalacznik`

```yaml
automation:
  - alias: "Librus - nowa wiadomosc"
    trigger:
      - platform: event
        event_type: librus_apix_nowa_wiadomosc
    action:
      - service: notify.notify
        data:
          title: "📬 Librus: nowa wiadomość"
          message: >-
            Dotyczy: {{ trigger.event.data.uczen | default('Dziecko') }}
            Od: {{ trigger.event.data.nadawca | default('nieznany') }}
            Temat: {{ trigger.event.data.temat | default('brak') }}
```

## Zaawansowane: Harmonogram odpytywania Librusa

Domyślnie integracja odświeża się adaptacyjnie, ale nadal możesz wyłączyć wewnętrzny system i wymusić odpytywanie z własnych automatyzacji HA. Wyłącz "Włącz odpytywanie w poszukiwaniu aktualizacji" w opcjach integracji, a następnie dodaj:

```yaml
alias: "Librus - Dynamiczne Odpytywanie"
description: "Odpytuje API Librusa co 1 godzinę, tylko w dni robocze od 8 do 20."
mode: single
trigger:
  - platform: time_pattern
    hours: "/1"
condition:
  - condition: time
    after: "08:00:00"
    before: "20:00:00"
    weekday:
      - mon
      - tue
      - wed
      - thu
      - fri
action:
  - service: homeassistant.update_entity
    target:
      entity_id: sensor.librus_twoje_dane_ogloszenia
```

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

## 🐛 Zgłaszanie błędów
Jeśli znajdziesz błąd, włącz logi debug, skopiuj logi z błędem i utwórz issue na GitHub.

## 📄 Licencja
MIT License - patrz [LICENSE](LICENSE)

## 📝 Historia Zmian

### v3.0 (Najnowsza)
- 🤖 Integracja AI (Profile dla rodzica i ucznia).
- 🧠 Adaptacyjny Cache zapobiegający problemom z 500 Internal Server Error od Librusa w godzinach porannych.
- 🎮 Lista wyzwań i nauki (To-Do) wspierająca gamifikację dla uczniów oraz czujnik binarny "Nauka Odrobiona".
- 🚨 Czujnik Uwag o Zachowaniu.
- 📬 Nowa usługa `get_message` i pełna kontrola przeczytanych wiadomości.
- ⚡ Szybkie zdarzenia (Events) dla powiadomień bez skomplikowanych template'ów w HA.

### v2.2.8 (i wcześniejsze poprawki 2.2.x)
- **Inteligentna fuzja planu lekcji z terminarzem** - Algorytm automatycznie dopasowuje sprawdziany w planie lekcji.
- **Zabezpieczenie przed błędem SQLite 16KB w Home Assistant**.
- **Wyodrębnienie pól Nauczyciel i Sala** ułatwiające niestandardowe budowanie kart.
- **Poprawa parsowania przedmiotów z myślnikami** oraz liczne mniejsze poprawki optymalizacyjne.

## 👨‍💻 Autorzy i podziękowania

Ten projekt to niezależna gałąź oryginalnej integracji, której twórcą jest **[LukMaverick](https://github.com/LukMaverick/LibrusSynergiaHA)**. Pragnę gorąco podziękować pierwotnemu autorowi za stworzenie solidnego fundamentu integracji!

Projekt w warstwie komunikacyjnej korzysta z biblioteki [librus-apix](https://github.com/RustySnek/librus-apix) autorstwa RustySnek. Wersja 3.0 przygotowana przez społeczność HA!

Specjalne podziękowania dla **KB**, **@km4lin**, **@Yauhenda**, **@jarecki**, **@sgurgul**, **@ebabaj**, **@Lucaspog** oraz **@morbiasz** za gigantyczny wkład w rozwój, zrzuty kodu, poprawki oraz świetne pomysły, bez których ta integracja by dzisiaj nie istniała!

---

**⭐ Jeśli podoba Ci się projekt, zostaw gwiazdkę na GitHub!**
