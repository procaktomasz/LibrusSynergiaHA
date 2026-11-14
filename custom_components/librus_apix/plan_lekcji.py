"""Plan lekcji z Librusa z obsługą wpisów przekreślonych (Issue #59).

Odpowiednik `librus_apix.timetable.get_timetable`, z jedną różnicą: przy
przesunięciu lekcji komórka planu zawiera dwa wpisy - przeniesiony stąd,
owinięty w `<s>`, i przeniesiony tutaj, bez `<s>`. Biblioteka skleja oba
w "Matematyka / Historia" i bierze podpowiedź z pierwszego `<a>`, więc
przedmiot i opis zmiany dotyczą lekcji, której już nie ma.

Tutaj liczą się tylko wpisy nieprzekreślone, każdy z własną podpowiedzią.
Gdy w komórce są wyłącznie wpisy przekreślone (lekcja przeniesiona stąd
i nic w zamian), zostają one, a `Period.skreslony` = True - po tym
`async_get_timetable` odróżnia odwołanie od lekcji przeniesionej tutaj.
"""
from datetime import datetime, timedelta
from typing import List

from bs4 import BeautifulSoup
from librus_apix.exceptions import DateError, ParseError
from librus_apix.helpers import no_access_check
from librus_apix.timetable import Period


def _podpowiedz(wpis):
    """`<a>` z podpowiedzią stojące tuż przed wpisem (albo przed jego `<s>`)."""
    element = wpis.parent if wpis.parent is not None and wpis.parent.name == "s" else wpis
    poprzedni = element.find_previous_sibling()
    if poprzedni is not None and poprzedni.name == "a":
        return poprzedni
    return None


def _info(lesson, wybrane) -> dict:
    """Opis zmiany jak w bibliotece, ale z podpowiedzi wybranych wpisów."""
    info = {}
    for wpis in wybrane:
        a_href = _podpowiedz(wpis)
        tooltip = a_href.select_one("div.center.plan-lekcji-info") if a_href is not None else None
        if tooltip is None:
            continue
        attr_dict = {}
        for attr in (
            a_href.attrs.get("title", "")
            .replace("<b>", "")
            .replace("</b>", "")
            .replace("\xa0", " ")
            .split("<br>")
        ):
            if len(attr.strip()) > 2 and ": " in attr:
                key, value = attr.split(": ", 1)
                attr_dict[key] = value
        info.setdefault(tooltip.text.strip(), {
            "teacher_swap": attr_dict.get("Nauczyciel", ""),
            "subject_swap": attr_dict.get("Przedmiot", ""),
            "classroom_swap": attr_dict.get("Sala", ""),
            "date_added": attr_dict.get("Data dodania", ""),
        })
    # etykieta bez podpowiedzi (np. samo "odwołane") - jak w bibliotece
    for tooltip in lesson.select("div.center.plan-lekcji-info"):
        if tooltip.find_parent("a") is None:
            info.setdefault(tooltip.text.strip(), "")
    return info


def get_timetable(client, monday_date: datetime) -> List[List[Period]]:
    """Plan na tydzień od poniedziałku `monday_date` (7 dni, lista lekcji na dzień)."""
    if monday_date.strftime("%A") != "Monday":
        raise DateError("You must input a Monday date.")
    sunday = monday_date + timedelta(days=6)
    week = f"{monday_date.strftime('%Y-%m-%d')}_{sunday.strftime('%Y-%m-%d')}"
    post = client.post(client.TIMETABLE_URL, data={"tydzien": week})
    soup = no_access_check(BeautifulSoup(post.text, "lxml"))
    periods = soup.select("table.decorated.plan-lekcji > tr.line1")
    if len(periods) < 1:
        raise ParseError("Error in parsing timetable.")
    recess = soup.select("table.decorated.plan-lekcji > tr.line0")

    timetable: List[List[Period]] = []
    for weekday in range(7):
        timetable.append([])
        for period in range(len(periods)):
            recess_from, recess_to = None, None
            if period <= len(recess) - 1:
                center = recess[period].select_one("td.center")
                if center is None:
                    raise ParseError("Error while parsing timetable (center)")
                recess_from, recess_to = [
                    x.strip()
                    for x in center.text.replace("&nbsp;", "").strip().split("-", 1)
                ]
            lesson = periods[period].select(
                'td[id="timetableEntryBox"][class="line1"]'
            )[weekday]
            td_center = periods[period].select_one('td[class="center"]')
            if td_center is None:
                raise ParseError("Error while parsing lesson_number of period")
            lesson_number = int(td_center.text)

            wpisy = lesson.select("div.text")
            aktualne = [w for w in wpisy if w.find_parent("s") is None]
            wybrane = aktualne or wpisy
            skreslony = bool(wpisy) and not aktualne

            subjects, teachers = [], []
            for wpis in wybrane:
                sub = wpis.select_one("b")
                if sub is not None:
                    subjects.append(sub.text.strip())
                tc = (
                    wpis.text.replace("\xa0", " ")
                    .replace("\n", "")
                    .replace("&nbsp", "")
                    .split("-")
                )
                if len(tc) >= 2:
                    teachers.append("-".join(tc[1:]).strip())

            date, date_from, date_to = [
                val for key, val in lesson.attrs.items() if key.startswith("data")
            ]
            p = Period(
                " / ".join(subjects),
                " / ".join(teachers),
                date,
                date_from,
                date_to,
                datetime.strptime(date, "%Y-%m-%d").strftime("%A"),
                _info(lesson, wybrane),
                lesson_number,
                recess_from,
                recess_to,
            )
            p.skreslony = skreslony
            timetable[weekday].append(p)
    return timetable
