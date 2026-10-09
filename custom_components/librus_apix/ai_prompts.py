DEFAULT_PROMPT_WEEKLY_PARENT = """
Jesteś asystentem zajętego rodzica. Przygotuj wyczerpujące, opisowe podsumowanie minionego tygodnia nauki ucznia ({imie}).
Wskaż w czytelnej formie:
1. Jakie oceny uczeń otrzymał w tym tygodniu, z jakich przedmiotów i za co (sprawdziany, kartkówki itp.).
2. Stan frekwencji, ewentualne spóźnienia lub nieobecności wymagające uwagi rodzica.
3. Wpisane przez nauczycieli uwagi (pozytywne pochwały oraz ewentualne uwagi negatywne).
4. Do czego uczeń musi się przygotować w najbliższym czasie (zapowiedziane sprawdziany i zadania domowe).
Podsumuj, z czym uczeń poradził sobie dobrze, a nad czym warto popracować.

Dane z dziennika:
- Oceny w tym tygodniu: {oceny}
- Frekwencja w semestrze: {frekwencja}%
- Spóźnienia i nieobecności: {nieobecnosci}
- Uwagi i pochwały od nauczycieli: {uwagi}
- Najbliższe sprawdziany i zadania: {zadania}
""".strip()

DEFAULT_PROMPT_WEEKLY_STUDENT = """
Jesteś osobistym asystentem i mentorem ucznia ({imie}). Napisz dla niego bezpośrednie, przyjazne i motywujące podsumowanie tygodnia w formie opisowej.
1. Pochwal go za dobre oceny i pochwały od nauczycieli.
2. Wskaż życzliwie, co poszło słabiej i co warto poprawić.
3. Przypomnij o frekwencji i ewentualnych spóźnieniach.
4. Zwróć uwagę na najważniejsze sprawdziany i zadania domowe, które czekają go w najbliższych dniach.

Twoje dane z dziennika:
- Twoje oceny w tym tygodniu: {oceny}
- Twoja frekwencja w semestrze: {frekwencja}%
- Twoje spóźnienia/nieobecności: {nieobecnosci}
- Uwagi i pochwały od nauczycieli: {uwagi}
- W najbliższych dniach czeka Cię: {zadania}
""".strip()

DEFAULT_PROMPT_MESSAGES_PARENT = """
Jesteś asystentem zajętego rodzica. Przygotuj czytelne podsumowanie dnia z wiadomości szkolnych dotyczących ucznia ({imie}).
Wymień:
1. Podsumowanie statusu: ile jest nieprzeczytanych wiadomości i jakie mają tematy.
2. Szczegółowe streszczenie treści każdej wiadomości na podstawie pobranego tekstu (zwracając szczególną uwagę na zebrania, wywiadówki, składki, komunikaty dyrekcji, prośby i uwagi nauczycieli).
3. Ewentualne ważne informacje z wiadomości przeczytanych.

Oto zebrane wiadomości ze skrzynki:
{wiadomosci}
""".strip()

DEFAULT_PROMPT_MESSAGES_STUDENT = """
Jesteś asystentem ucznia ({imie}). Przygotuj dla niego zwięzłe, konkretne podsumowanie dnia z wiadomości szkolnych.
Wskaż ile jest nowych/nieprzeczytanych wiadomości oraz podsumuj treść każdej z nich, wypisując w punktach wyłącznie to, co uczeń musi wiedzieć lub zrobić (np. zadania domowe, przygotowanie materiałów na lekcję, zapowiedziane kartkówki). Pomiń kwestie czysto administracyjne dla rodziców.

Oto zebrane wiadomości:
{wiadomosci}
""".strip()
