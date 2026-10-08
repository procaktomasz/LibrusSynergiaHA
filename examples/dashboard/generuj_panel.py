"""Generator panelu Librus dla Home Assistant (integracja LibrusSynergiaHA).

1. Wpisz uczniów w UCZNIOWIE – imię i nazwisko dokładnie tak, jak w nazwie
   urządzenia w HA ("Librus - Jan Kowalski" -> "Jan Kowalski").
2. Uruchom:  python3 generuj_panel.py > panel.yaml
3. W HA: Ustawienia -> Panele -> Dodaj panel -> "Nowy panel od zera",
   adres (URL) jak w PANEL poniżej. Otwórz panel -> ołówek (Edytuj) -> ⋮ ->
   "Edytor kodu źródłowego" -> wklej zawartość panel.yaml -> Zapisz.

Wymaga kart Mushroom (HACS -> Frontend -> "Mushroom").
"""
import json
import sys
import unicodedata

# Uczniowie są podawani interaktywnie podczas działania skryptu
UCZNIOWIE = []
PANEL = "szkola-librus"  # adres (URL) panelu w HA, np. /szkola-librus

# --- Opcjonalnie: sekcja "Dojazd" (puste = sekcji nie ma) --------------------
# Autobus miejski: integracja "Polish Public Transport Card" (HACS, @toczke).
# Dodaj w niej dwa przystanki - przy domu i przy szkole - i wpisz ich sensory.
PRZYSTANEK_DOM = ""     # np. "sensor.przystanek_dom_odjazdy"
PRZYSTANEK_SZKOLA = ""  # np. "sensor.przystanek_szkola_odjazdy"
LINIA = ""              # np. "123" - tylko ta linia ("" = wszystkie)
# Autobus szkolny (gimbus) jako zwykły rozkład - panel podpowie kurs na
# najbliższy dzień każdego ucznia (według pierwszej i ostatniej lekcji).
AUTOBUS_SZKOLNY = [
    # (nazwa kursu, True = do szkoły / False = do domu, godzina przy domu, godzina przy szkole)
    # ("Poranny", True, "07:25", "07:35"),
    # ("Powrót I", False, "13:15", "13:00"),
    # ("Powrót II", False, "14:45", "14:30"),
]


def prefiks(imie_nazwisko):
    """Prefiks encji tak, jak tworzy go HA: "Jan Kowalski" -> "librus_jan_kowalski"."""
    t = imie_nazwisko.lower().replace("ł", "l")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    slug = "".join(c if c.isalnum() else "_" for c in t)
    return "librus_" + "_".join(x for x in slug.split("_") if x)


KOL = "{% set kol = {'6':'#2e7d32','5':'#43a047','4':'#7cb342','3':'#f9a825','2':'#ef6c00','1':'#c62828'} %}"

def plan_next(p):
    return f"""{{% set p = 'sensor.{p}_' %}}
{{% set dni = state_attr(p ~ 'plan_lekcji', 'kolejne_7_dni') or [] %}}
{{% set today = now().strftime('%Y-%m-%d') %}}{{% set hm = now().strftime('%H:%M') %}}
{{% set ns = namespace(d=none) %}}
{{% for d in dni if ns.d is none and d.lekcje | length > 0 %}}{{% if d.data > today or (d.data == today and hm < (d.lekcje | map(attribute='godzina_do') | select('match', '[0-9]') | list | last | default('00:00'))) %}}{{% set ns.d = d %}}{{% endif %}}{{% endfor %}}
{{% if ns.d is none %}}Brak lekcji w najbliższych dniach 🎉{{% else %}}{{% set d = ns.d %}}
{{% set jutro = (now() + timedelta(days=1)).strftime('%Y-%m-%d') %}}
### {{{{ 'Dziś' if d.data == today else ('Jutro' if d.data == jutro else d.dzien_tygodnia) }}}} · {{{{ d.lekcje[0].godzina_od }}}}–{{{{ d.lekcje[-1].godzina_do }}}}
| | Godz. | Przedmiot | Sala |
|---|---|---|---|
{{% for l in d.lekcje %}}{{% set teraz = d.data == today and l.godzina_od <= hm < l.godzina_do %}}{{% set ev = (l.get('zdarzenie') or '') | lower %}}| {{{{ '▶' if teraz else (l.numer if l.numer is not none else 0) }}}} | {{{{ l.godzina_od }}}} | {{% if l.get('odwolana') %}}~~{{{{ l.przedmiot }}}}~~ ❌{{% elif l.get('zastepstwo') %}}**{{{{ l.przedmiot }}}}** 🔄{{% else %}}**{{{{ l.przedmiot }}}}**{{% endif %}}{{% if l.get('dzd') %}} <small>*dodatkowe*</small>{{% endif %}}{{% if 'sprawdzian' in ev %}} 🔴{{% elif 'kartk' in ev %}} 🟠{{% elif ev %}} 🔵{{% endif %}} | {{{{ (l.get('sala') or '') | replace('s. ','') }}}} |
{{% endfor %}}{{% endif %}}"""

def terminarz(p, days, only_tests=False):
    flt = "{% if 'sprawdzian' in t or 'klasówka' in t or 'kartk' in t %}" if only_tests else "{% if true %}"
    return f"""{{% set zd = state_attr('sensor.{p}_terminarz','zdarzenia') or [] %}}
{{% set ns = namespace(n=0) %}}
{{% for z in zd | rejectattr('tytul','search','^(Nauczyciel:|Zastępstwo)') | sort(attribute='data') if z.get('rodzaj', '') not in ['nieobecnosc_nauczyciela','zastepstwo','przesuniecie','odwolanie'] %}}{{% set dd = (strptime(z.data,'%Y-%m-%d').date() - now().date()).days %}}{{% set t = z.tytul | lower %}}{{% if 0 <= dd <= {days} %}}{flt}{{% set ns.n = ns.n + 1 %}}{{% set opis = z.szczegoly.Opis if z.szczegoly is mapping and z.szczegoly.Opis is defined and z.szczegoly.Opis != 'unknown' else '' %}}
{{{{ {{'sprawdzian':'🔴','kartkowka':'🟠','dzien_wolny':'🏖️','wydarzenie':'🔵'}}.get(z.get('rodzaj', '')) or ('🔴' if 'sprawdzian' in t or 'klasówka' in t else ('🟠' if 'kartk' in t else ('🔵' if 'wydarzenie' in t else '📅'))) }}}} **{{{{ z.tydzien[:3] | lower }}}} {{{{ z.data[8:10] }}}}.{{{{ z.data[5:7] }}}}** <small>{{{{ 'dziś' if dd == 0 else ('jutro' if dd == 1 else 'za ' ~ dd ~ ' dni') }}}}</small> · **{{{{ z.przedmiot if z.przedmiot and z.przedmiot != 'unknown' else '' }}}}** {{{{ z.tytul }}}}{{% if opis %}}<br><small>{{{{ opis | replace('\\n', ' ') | truncate(120) }}}}</small>{{% endif %}}
{{% endif %}}{{% endif %}}{{% endfor %}}{{% if ns.n == 0 %}}Nic w ciągu {days} dni ✅{{% endif %}}"""

def ostatnie_oceny(p, n=6):
    return f"""{{% set o = state_attr('sensor.{p}_oceny','oceny_wg_przedmiotu') or {{}} %}}
{{% set ns = namespace(l=[]) %}}
{{% for prz, lst in o.items() %}}{{% for g in lst %}}{{% set ns.l = ns.l + [{{'p': prz, 'o': g.ocena, 'd': g.data, 'k': g.kategoria, 'n': g.jest_nowa, 'op': g.get('opis', '')}}] %}}{{% endfor %}}{{% endfor %}}
{KOL}
{{% for g in (ns.l | sort(attribute='d', reverse=true))[:{n}] %}}<font color="{{{{ kol.get(g.o[:1], '#9e9e9e') }}}}"><b>{{{{ g.o }}}}</b></font> **{{{{ g.p }}}}**{{% if g.op %}} – {{{{ g.op }}}}{{% endif %}} <small>{{{{ g.k }}}} · {{{{ g.d[8:10] }}}}.{{{{ g.d[5:7] }}}}</small>{{{{ ' 🆕' if g.n }}}}<br>
{{% else %}}Brak ocen w tym semestrze.{{% endfor %}}"""

def tabela_ocen(p):
    return f"""{{% set o = state_attr('sensor.{p}_oceny','oceny_wg_przedmiotu') or {{}} %}}{{% set sr = state_attr('sensor.{p}_srednia_ocen','srednie_wg_przedmiotow') or {{}} %}}
{KOL}
| Przedmiot | Oceny | Średnia |
|:---|:---|---:|
{{% for prz in o.keys() | sort %}}{{% set s = sr.get(prz) %}}| **{{{{ prz }}}}** | {{% for g in o[prz] %}}<font color="{{{{ kol.get(g.ocena[:1], '#9e9e9e') }}}}"><b>{{{{ g.ocena }}}}</b></font>{{% if g.get('opis') %}}<small> ({{{{ g.opis }}}})</small>{{% endif %}}{{{{ ' ' }}}}{{% endfor %}}| {{% if s is number %}}<font color="{{{{ '#43a047' if s >= 4.5 else ('#7cb342' if s >= 3.75 else ('#f9a825' if s >= 2.75 else '#c62828')) }}}}"><b>{{{{ '%.2f' | format(s) }}}}</b></font>{{% else %}}–{{% endif %}} |
{{% endfor %}}"""

def plan_tygodnia(p):
    return f"""{{% set dni = state_attr('sensor.{p}_plan_lekcji', 'kolejne_7_dni') or [] %}}
{{% for d in dni if d.lekcje | length > 0 %}}
#### {{{{ d.dzien_tygodnia }}}} {{{{ d.data[8:10] }}}}.{{{{ d.data[5:7] }}}} <small>· {{{{ d.lekcje[0].godzina_od }}}}–{{{{ d.lekcje[-1].godzina_do }}}}</small>
{{% for l in d.lekcje %}}{{% set ev = (l.get('zdarzenie') or '') | lower %}}`{{{{ l.godzina_od }}}}` {{% if l.get('odwolana') %}}~~{{{{ l.przedmiot }}}}~~ ❌{{% elif l.get('zastepstwo') %}}**{{{{ l.przedmiot }}}}** 🔄{{% else %}}{{{{ l.przedmiot }}}}{{% endif %}}{{% if l.get('dzd') %}} <small>*dodatkowe*</small>{{% endif %}}{{% if 'sprawdzian' in ev %}} 🔴{{% elif 'kartk' in ev %}} 🟠{{% elif ev %}} 🔵{{% endif %}} <small>{{{{ (l.get('sala') or '') | replace('s. ','') }}}}</small><br>
{{% endfor %}}
{{% else %}}Brak lekcji w najbliższym tygodniu.{{% endfor %}}"""

def tematy_lekcji(p):
    return f"""{{% set lekcje = state_attr('sensor.{p}_tematy_lekcji', 'lekcje') or [] %}}
{{% for dzien, lista in lekcje | groupby('data') | reverse %}}
#### {{{{ lista[0].dzien_tygodnia }}}} {{{{ dzien[8:10] }}}}.{{{{ dzien[5:7] }}}}
{{% for l in lista %}}`{{{{ l.numer if l.numer is not none else '–' }}}}` **{{{{ l.przedmiot }}}}**{{% if l.zastepstwo %}} 🔄 <small>{{{{ l.zastepca }}}}</small>{{% endif %}}{{% if l.obecnosc in ['nb', 'u', 'sp', 'zw'] %}} ❗**{{{{ l.obecnosc }}}}**{{% endif %}} – {{{{ l.temat | replace('\\n', ' ') }}}}<br>
{{% endfor %}}
{{% else %}}Brak zrealizowanych lekcji w ostatnich 7 dniach.{{% endfor %}}"""

def wiadomosci(p):
    return f"""{{% set m = state_attr('sensor.{p}_wiadomosci','wiadomosci') or [] %}}
{{% for x in m if x.temat and x.temat != 'Brak' %}}{{{{ '🔴' if x.nieprzeczytana else '⚪' }}}} **{{{{ x.temat | trim }}}}**{{{{ ' 📎' if x.ma_zalacznik }}}}<br><small>{{{{ x.nadawca.split(' (')[0] }}}} · {{{{ x.data[8:10] }}}}.{{{{ x.data[5:7] }}}} {{{{ x.data[11:16] }}}}</small>{{% if x.tresc %}}<details><summary>Treść</summary>{{{{ x.tresc }}}}</details>{{% endif %}}

{{% else %}}Brak wiadomości.{{% endfor %}}"""

def ogloszenia(p):
    return f"""{{% for a in state_attr('sensor.{p}_ogloszenia','lista_ogloszen') or [] %}}<details><summary><b>{{{{ a.tytul }}}}</b> <small>· {{{{ a.data[8:10] }}}}.{{{{ a.data[5:7] }}}} · {{{{ a.nadawca }}}}</small></summary>

{{{{ a.opis }}}}
</details>
{{% else %}}Brak ogłoszeń.{{% endfor %}}"""

def md(content):
    return {"type": "markdown", "content": content}

def heading(text, icon=None, style="subtitle"):
    h = {"type": "heading", "heading": text, "heading_style": style}
    if icon: h["icon"] = icon
    return h

def tpl(primary, secondary, icon, color, tap=None, cols=6):
    c = {"type": "custom:mushroom-template-card", "primary": primary, "secondary": secondary,
         "icon": icon, "icon_color": color, "color": color, "grid_options": {"columns": cols}}
    c["tap_action"] = tap or {"action": "none"}
    return c

def uwagi(p):
    return f"""{{% set u = state_attr('sensor.{p}_uwagi','uwagi') or [] %}}{{% set ik = {{'pozytywna':'👍','negatywna':'⚠️','neutralna':'ℹ️'}} %}}
{{% for x in u %}}{{{{ ik.get(x.rodzaj, 'ℹ️') }}}} **{{{{ x.data[8:10] }}}}.{{{{ x.data[5:7] }}}}** <small>{{{{ x.rodzaj }}}}{{{{ ' · ' ~ x.nauczyciel if x.nauczyciel }}}}</small><br>{{{{ x.tresc }}}}

{{% else %}}Brak uwag ✅{{% endfor %}}"""

def kid_overview(p, name, icon):
    s = f"sensor.{p}_"
    detail = {"action": "navigate", "navigation_path": f"/{PANEL}/{p.replace('_','-')}"}
    sec = {"type": "grid", "cards": [
        heading(name, icon, "title"),
        tpl(f"{{{{ states('{s}informacje_o_uczniu') }}}}",
            f"kl. {{{{ state_attr('{s}informacje_o_uczniu','klasa') }}}} · wych. {{{{ state_attr('{s}informacje_o_uczniu','wychowawca') }}}}",
            "mdi:account-school", "blue", detail, 12),
        tpl(f"{{{{ states('{s}srednia_ocen') }}}}", "Średnia ocen", "mdi:chart-line",
            f"{{% set v = states('{s}srednia_ocen') | float(0) %}}{{{{ 'green' if v >= 4.5 else ('light-green' if v >= 3.75 else ('amber' if v >= 2.75 else ('red' if v > 0 else 'grey'))) }}}}",
            detail),
        tpl(f"{{{{ states('{s}szczesliwy_numerek') }}}}",
            f"{{{{ '🍀 To mój numer!' if states('{s}szczesliwy_numerek') | int(0) == state_attr('{s}informacje_o_uczniu','numer_w_klasie') | int(-1) else 'Szczęśliwy numerek (mój: ' ~ state_attr('{s}informacje_o_uczniu','numer_w_klasie') ~ ')' }}}}",
            "mdi:clover",
            f"{{{{ 'green' if states('{s}szczesliwy_numerek') | int(0) == state_attr('{s}informacje_o_uczniu','numer_w_klasie') | int(-1) else 'grey' }}}}"),
        tpl(f"{{{{ state_attr('{s}wiadomosci','liczba_nieprzeczytanych') | int(0) }}}}", "Nieprzeczytane wiadomości", "mdi:email",
            f"{{{{ 'red' if state_attr('{s}wiadomosci','liczba_nieprzeczytanych') | int(0) > 0 else 'grey' }}}}", detail),
        tpl(f"{{{{ states('todo.{p}_zadania_domowe_to_do') }}}}", "Zadania domowe", "mdi:notebook-edit",
            f"{{{{ 'orange' if states('todo.{p}_zadania_domowe_to_do') | int(0) > 0 else 'grey' }}}}",
            {"action": "more-info", "entity": f"todo.{p}_zadania_domowe_to_do"}),
        tpl(f"{{{{ states('{s}uwagi') }}}}",
            f"Uwagi · 👍 {{{{ state_attr('{s}uwagi','liczba_pozytywnych') | int(0) }}}} ⚠️ {{{{ state_attr('{s}uwagi','liczba_negatywnych') | int(0) }}}}",
            "mdi:account-alert",
            f"{{% set u = state_attr('{s}uwagi','uwagi') or [] %}}{{% set neg = u | selectattr('rodzaj','eq','negatywna') | selectattr('data','ge',(now() - timedelta(days=14)).strftime('%Y-%m-%d')) | list %}}{{{{ 'red' if neg else ('green' if u | selectattr('rodzaj','eq','pozytywna') | list else 'grey') }}}}",
            detail),
        tpl(f"{{{{ state_attr('{s}frekwencja','frekwencja_procent') | default('–', true) }}}}%",
            f"Frekwencja · nb: {{{{ state_attr('{s}frekwencja','liczba_nieusprawiedliwionych') | int(0) }}}} · sp: {{{{ state_attr('{s}frekwencja','liczba_spoznien') | int(0) }}}}",
            "mdi:account-check",
            f"{{% set v = state_attr('{s}frekwencja','frekwencja_procent') %}}{{{{ 'grey' if v is none else ('green' if v >= 95 else ('amber' if v >= 85 else 'red')) }}}}",
            detail),
        heading("Plan lekcji", "mdi:timetable"),
        md(plan_next(p)),
        heading("Najbliższe 14 dni", "mdi:calendar-alert"),
        md(terminarz(p, 14)),
        heading("Ostatnie oceny", "mdi:star-circle"),
        md(ostatnie_oceny(p)),
        {"type": "button", "name": "Wszystkie szczegóły", "icon": "mdi:arrow-right-circle", "show_state": False,
         "tap_action": detail, "grid_options": {"columns": 12, "rows": 1}, "icon_height": "24px"},
    ]}
    return sec

def kid_subview(p, name, icon):
    s = f"sensor.{p}_"
    return {
        "type": "sections", "max_columns": 3, "title": f"Librus · {name}", "path": p.replace("_", "-"),
        "icon": icon, "subview": True, "back_path": f"/{PANEL}/szkola",
        "sections": [
            {"type": "grid", "column_span": 3, "cards": [
                heading("Kalendarz", "mdi:calendar", "title"),
                {"type": "calendar", "initial_view": "dayGridMonth", "grid_options": {"columns": 36, "rows": 8},
                 "entities": [f"calendar.{p}_terminarz_kalendarz", f"calendar.{p}_plan_lekcji_kalendarz"]},
            ]},
            {"type": "grid", "cards": [
                heading("Oceny", "mdi:star-circle", "title"),
                {"type": "gauge", "entity": f"{s}srednia_ocen", "name": "Średnia", "min": 1, "max": 6,
                 "needle": True, "severity": {"red": 1, "yellow": 2.75, "green": 4.5}, "grid_options": {"columns": 6, "rows": 3}},
                {"type": "tile", "entity": f"{s}frekwencja", "name": "Nieobecności", "icon": "mdi:account-cancel",
                 "grid_options": {"columns": 6, "rows": 1}},
                {"type": "markdown", "content": f"Frekwencja: **{{{{ state_attr('{s}frekwencja','frekwencja_procent') | default('–', true) }}}}%**<br>Spóźnienia: **{{{{ state_attr('{s}frekwencja','liczba_spoznien') | int(0) }}}}** · nb: **{{{{ state_attr('{s}frekwencja','liczba_nieusprawiedliwionych') | int(0) }}}}** · u: **{{{{ state_attr('{s}frekwencja','liczba_usprawiedliwionych') | int(0) }}}}**", "grid_options": {"columns": 6, "rows": 2}},
                md(tabela_ocen(p)),
                {"type": "history-graph", "title": "Średnia w czasie", "hours_to_show": 720,
                 "entities": [{"entity": f"{s}srednia_ocen", "name": "Średnia"}]},
                heading("Zadania domowe", "mdi:notebook-edit", "title"),
                {"type": "todo-list", "entity": f"todo.{p}_zadania_domowe_to_do", "hide_create": True},
                heading("Wiadomości", "mdi:email"),
                md(wiadomosci(p)),
                heading("Ogłoszenia", "mdi:bullhorn"),
                md(ogloszenia(p)),
                {"type": "tile", "entity": f"button.{p}_odswiez_dane", "name": "Odśwież dane z Librusa",
                 "icon": "mdi:refresh", "tap_action": {"action": "perform-action", "perform_action": "button.press",
                                                        "target": {"entity_id": f"button.{p}_odswiez_dane"}}},
            ]},
            {"type": "grid", "cards": [
                heading("Uwagi", "mdi:account-alert", "title"),
                md(uwagi(p)),
                heading("Tematy lekcji (7 dni)", "mdi:book-open-page-variant", "title"),
                md(tematy_lekcji(p)),
            ]},
            {"type": "grid", "cards": [
                heading("Sprawdziany i terminarz", "mdi:calendar-alert", "title"),
                md(terminarz(p, 60)),
                heading("Plan tygodnia", "mdi:timetable"),
                md(plan_tygodnia(p)),
            ]},
        ],
    }

def autobus_szkolny():
    kursy = ",\n ".join(
        f"{{'n':'{n}','do':{'true' if do else 'false'},'dom':'{dom}','szk':'{szk}'}}"
        for n, do, dom, szk in AUTOBUS_SZKOLNY)
    dzieci = ", ".join(f"('{prefiks(u)}','{n}')" for u, n, _ in UCZNIOWIE)
    linia = ""
    if PRZYSTANEK_SZKOLA and LINIA:
        linia = (f"{{% set ns2 = namespace(t='') %}}{{% for b in (state_attr('{PRZYSTANEK_SZKOLA}','departures') or []) "
                 f"if ns2.t == '' and b.route == '{LINIA}' and b.estimated_time[:10] == d.data and b.estimated_time[11:16] >= do_ %}}"
                 f"{{% set ns2.t = b.estimated_time[11:16] %}}{{% endfor %}}{{% if ns2.t %}} · 🚍 {LINIA} o **{{{{ ns2.t }}}}**{{% endif %}}")
    return f"""{{% set kursy = [
 {kursy}] %}}
{{% set dzieci = [{dzieci}] %}}""" + r"""
{% set today = now().strftime('%Y-%m-%d') %}{% set hm = now().strftime('%H:%M') %}
{% set jutro = (now() + timedelta(days=1)).strftime('%Y-%m-%d') %}
{% for p, imie in dzieci if state_attr('sensor.' ~ p ~ '_plan_lekcji','kolejne_7_dni') is not none %}
{% set ns = namespace(d=none) %}
{% for d in state_attr('sensor.' ~ p ~ '_plan_lekcji','kolejne_7_dni') if ns.d is none and d.lekcje | length > 0 %}{% if d.data > today or (d.data == today and hm < (d.lekcje | map(attribute='godzina_do') | select('match', '[0-9]') | list | last | default('00:00'))) %}{% set ns.d = d %}{% endif %}{% endfor %}
{% if ns.d is not none %}{% set d = ns.d %}{% set na = namespace(a=[]) %}{% for l in d.lekcje if not l.get('odwolana') %}{% set na.a = na.a + [l] %}{% endfor %}{% set akt = na.a if na.a else d.lekcje %}{% set od = akt[0].godzina_od %}{% set do_ = akt[-1].godzina_do %}
{% set r = kursy | selectattr('do') | selectattr('szk','le',od) | list %}{% set w = kursy | rejectattr('do') | selectattr('szk','ge',do_) | list %}
**{{ imie }}** · {{ 'dziś' if d.data == today else ('jutro' if d.data == jutro else d.dzien_tygodnia | lower) }} ({{ od }}–{{ do_ }})<br>
🌅 {% if r %}**{{ r[-1].dom }}** spod domu → szkoła {{ r[-1].szk }}{% else %}**brak kursu** – zajęcia od {{ od }} 🚗{% endif %}<br>
🏠 {% if w %}**{{ w[0].szk }}** ze szkoły → dom {{ w[0].dom }}{% else %}brak kursu po {{ do_ }}{% endif %}""" + linia + r"""

{% endif %}{% endfor %}
---
{% set wd = now().weekday() < 5 %}
| Kurs | Dom | Szkoła |
|:---|:---:|:---:|
{% for k in kursy %}{% set t = k.dom if k['do'] else k.szk %}{% set minal = not wd or t < hm %}| {{ '~~' if minal }}{{ '🌅' if k['do'] else '🏠' }} {{ k.n }}{{ '~~' if minal }} | {{ '**' ~ k.dom ~ '**' if k['do'] else k.dom }} | {{ k.szk if k['do'] else '**' ~ k.szk ~ '**' }} |
{% endfor %}"""


def dojazd():
    """Sekcja "Dojazd" - tylko gdy coś skonfigurowano powyżej."""
    karty = []
    przystanek = lambda e: {"type": "custom:polish-transport-card", "max_departures": 5, "view_mode": "mixed",
                            "entities": [dict({"entity": e}, **({"filter_routes": [LINIA]} if LINIA else {}))]}
    if PRZYSTANEK_DOM:
        karty += [heading("Do szkoły · przystanek przy domu", "mdi:school"), przystanek(PRZYSTANEK_DOM)]
    if PRZYSTANEK_SZKOLA:
        karty += [heading("Do domu · przystanek przy szkole", "mdi:home"), przystanek(PRZYSTANEK_SZKOLA)]
    if AUTOBUS_SZKOLNY:
        karty += [heading("Autobus szkolny", "mdi:bus-side"), md(autobus_szkolny())]
    if not karty:
        return []
    return [{"type": "grid", "cards": [heading("Dojazd", "mdi:bus-school", "title")] + karty}]


def overview():
    return {
        "type": "sections", "max_columns": 3, "title": "Szkoła", "path": "szkola", "icon": "mdi:school",
        "header": {"card": {"type": "markdown", "text_only": True,
                            "content": "# 🎒 Szkoła\n{% set d = ['poniedziałek','wtorek','środa','czwartek','piątek','sobota','niedziela'] %}{{ d[now().weekday()] | capitalize }}, {{ now().strftime('%d.%m.%Y') }}"}},
        "sections": [kid_overview(prefiks(u), n, i) for u, n, i in UCZNIOWIE] + dojazd(),
    }


if __name__ == "__main__":
    print("="*50)
    print("🎓 Generator Dashboardu dla Librus Synergia HA 🎓")
    print("="*50)
    
    uczniowie_lista = []
    
    while True:
        try:
            liczba_str = input("\\nIlu uczniów chcesz dodać do panelu? (np. 1, 2): ").strip()
            liczba = int(liczba_str)
            if liczba > 0:
                break
            print("Wpisz liczbę większą od zera.")
        except ValueError:
            print("To nie jest prawidłowa liczba.")
            
    for i in range(liczba):
        print(f"\\n--- Uczeń {i+1} ---")
        imie_nazwisko = input('Podaj pełne Imię i Nazwisko (dokładnie jak w encjach HA, np. "Jan Kowalski"): ').strip()
        krotka_nazwa = input('Podaj krótkie Imię (do wyświetlania w nagłówkach, np. "Jan"): ').strip()
        
        plec = input('Płeć (c - chłopiec, d - dziewczynka) [Domyślnie: c]: ').strip().lower()
        ikona = "mdi:face-woman" if plec == "d" else "mdi:face-man"
        
        uczniowie_lista.append((imie_nazwisko, krotka_nazwa, ikona))

    # Zastąp globalną zmienną UCZNIOWIE naszą listą
    UCZNIOWIE = uczniowie_lista
    
    panel = {"title": "Szkoła", "views": [overview()] + [kid_subview(prefiks(u), n, i) for u, n, i in UCZNIOWIE]}
    
    # Tworzenie nazwy pliku
    imiona_plik = "_".join([n for _, n, _ in UCZNIOWIE])
    nazwa_pliku = f"panel_{imiona_plik}.yaml"
    
    import os
    with open(nazwa_pliku, 'w', encoding='utf-8') as f:
        json.dump(panel, f, ensure_ascii=False, indent=2)
        f.write("\\n")
        
    print("\\n" + "="*50)
    print(f"✅ Sukces! Wygenerowano kod do pliku: {nazwa_pliku}")
    print("Otwórz ten plik, skopiuj całą jego zawartość")
    print("i wklej do edytora kodu źródłowego na czystym panelu w HA.")
    print("="*50 + "\\n")
    
    input("Naciśnij klawisz Enter, aby zakończyć...")

