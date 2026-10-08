# Gotowy panel Librus

Panel (dashboard) do Home Assistant korzystający ze wszystkich sensorów integracji. Nie trzeba niczego pisać – wystarczy wkleić.

**Strona główna „Szkoła”** – dla każdego ucznia: klasa i wychowawca, średnia, szczęśliwy numerek, nieprzeczytane wiadomości, zadania domowe, uwagi (👍/⚠️), frekwencja w %, plan na najbliższy dzień szkolny (▶ trwająca lekcja, ❌ odwołane, 🔄 zastępstwa, *dodatkowe* – zajęcia dodatkowe DZD, np. lekcja „zerowa” 7:10), najbliższe 14 dni z terminarza (🔴 sprawdzian, 🟠 kartkówka, 🏖️ dzień wolny) i ostatnie oceny.

**Podwidok ucznia** (przycisk „Wszystkie szczegóły”) – duży kalendarz, wszystkie oceny z kolorami, opisami i średnimi, wykres średniej, zadania domowe, wiadomości, ogłoszenia, uwagi, tematy lekcji z 7 dni (z nieobecnościami przy lekcjach), terminarz na 60 dni i plan tygodnia.

## Wymagania
- integracja Librus Synergia (ta),
- karty **Mushroom** z HACS (HACS → Frontend → „Mushroom”).
- opcjonalnie (sekcja „Dojazd”): integracja **Polish Public Transport Card** z HACS.

## Instalacja – wariant 1: gotowy plik (jeden uczeń)
1. Otwórz [`panel_jeden_uczen.yaml`](panel_jeden_uczen.yaml) i zamień wszystkie `jan_kowalski` oraz `jan-kowalski` na swojego ucznia, a `Jan` na jego imię.
   Prefiks to imię i nazwisko z nazwy urządzenia „Librus - Anna Nowak” → `anna_nowak` (małe litery, bez polskich znaków, spacje → `_`). Sprawdzisz go w **Narzędzia deweloperskie → Stany**, np. `sensor.librus_anna_nowak_oceny`.
2. **Ustawienia → Panele → Dodaj panel → Nowy panel od zera**, adres (URL): `szkola-librus`.
3. Otwórz panel → ✏️ (Edytuj) → ⋮ → **Edytor kodu źródłowego** → wklej całość → **Zapisz**.

## Instalacja – wariant 2: generator (dowolna liczba uczniów)
1. W [`generuj_panel.py`](generuj_panel.py) wpisz uczniów w `UCZNIOWIE` – imię i nazwisko tak jak w nazwie urządzenia („Librus - Jan Kowalski” → `"Jan Kowalski"`); generator sam utworzy nazwy encji.
2. `python3 generuj_panel.py > panel.yaml`
3. Jak w wariancie 1, punkty 2–3 (wklej `panel.yaml`).

Inny adres panelu? Zmień `PANEL` w generatorze (lub w gotowym pliku zamień `/szkola-librus/`).

## Opcjonalnie: dojazd do szkoły
Na górze `generuj_panel.py` jest sekcja „Dojazd” – domyślnie pusta (panel jej nie pokazuje). Można w niej ustawić:

- **Autobus miejski** – integracja [Polish Public Transport Card](https://github.com/toczke/polish-public-transport-card) (HACS). Dodaj w niej **dwa przystanki: przy domu i przy szkole**, a ich sensory wpisz w `PRZYSTANEK_DOM` i `PRZYSTANEK_SZKOLA` (opcjonalnie `LINIA`, np. `"123"`). Panel pokaże najbliższe odjazdy z obu przystanków.
- **Autobus szkolny (gimbus)** – jako zwykły rozkład w `AUTOBUS_SZKOLNY` (nazwa kursu, do szkoły / do domu, godzina przy domu, godzina przy szkole). Panel podpowie każdemu uczniowi kurs rano i powrót na najbliższy dzień szkolny – według pierwszej i ostatniej lekcji (z pominięciem odwołanych), a jeśli autobusu szkolnego po lekcjach nie ma, najbliższy odjazd `LINIA` spod szkoły. Minione kursy są przekreślone, a zajęcia przed pierwszym kursem (np. lekcja „zerowa”) dostają informację 🚗.

## Przykładowe automatyzacje
Zdarzenia integracji (nowa ocena, wiadomość, uwaga, nieobecność…) i przykłady powiadomień są opisane w głównym [README](../../README.md#-automatyzacje-powiadomień-na-telefon). Poniżej dodatkowo: wyciszanie telefonu ucznia w czasie lekcji (np. w związku z zakazem używania telefonów w szkole).

**1. Czujnik „w szkole”** – pomocnik szablonu (Ustawienia → Urządzenia i usługi → Pomocnicy → Utwórz → Szablon → Czujnik binarny), stan:
```jinja
{% set d = (state_attr('sensor.librus_jan_kowalski_plan_lekcji','kolejne_7_dni') or [])
   | selectattr('data','eq',now().strftime('%Y-%m-%d')) | list %}
{% set l = (d[0].lekcje if d else []) | rejectattr('odwolana','eq',true)
   | selectattr('godzina_od','match','[0-9]') | list %}
{% if l %}{% set t = now().strftime('%H:%M') %}
{% set start = (strptime(l[0].godzina_od,'%H:%M') - timedelta(minutes=30)).strftime('%H:%M') %}
{% set end = (strptime(l[-1].godzina_do,'%H:%M') + timedelta(minutes=10)).strftime('%H:%M') %}
{{ start <= t < end }}{% else %}false{% endif %}
```
Włączony od 30 min przed pierwszymi zajęciami (także dodatkowymi) do 10 min po ostatnich; odwołane lekcje są pomijane.

**2. Wyciszanie telefonu** – wymaga aplikacji Home Assistant na telefonie ucznia (Android) z dostępem do trybu „Nie przeszkadzać” i włączonym czujnikiem *Ringer mode*:
```yaml
alias: "Szkoła - wyciszanie telefonu Jana"
triggers:
  - trigger: state
    entity_id: binary_sensor.jan_w_szkole
    from: "off"
    to: "on"
    id: cisza
  - trigger: state
    entity_id: binary_sensor.jan_w_szkole
    from: "on"
    to: "off"
    id: dzwiek
actions:
  - action: notify.mobile_app_TELEFON_JANA
    data:
      message: command_ringer_mode
      data:
        command: "{{ 'silent' if trigger.id == 'cisza' else 'normal' }}"
        priority: high   # dociera także do uśpionego telefonu
        ttl: 0
```
Stan czujnika *Ringer mode* telefonu (`silent` / `normal`) pozwala sprawdzić, czy polecenie dotarło – np. powiadomić rodzica, jeśli po kilku minutach telefon nie potwierdzi wyciszenia.

## Dopasowanie
Każda sekcja to zwykłe karty (`markdown`, `mushroom-template-card`, `calendar`, `todo-list`…) – po wklejeniu można je przesuwać i zmieniać rozmiar w edytorze panelu. Szablony są odporne na brak danych (np. konto bez uwag czy bez ocen), więc karta nie znika z błędem.
