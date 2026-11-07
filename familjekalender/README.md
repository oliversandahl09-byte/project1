# Familjekalender

En enkel app för familjen som samlar allt på ett ställe:

- **Lagens kalendrar** från laget.se och förbundens/seriernas matchkalendrar (iCal/webcal-länkar). Hämtas om automatiskt var tredje timme.
- **Arbetsschema**: lägg in pass (t.ex. Dag, Kväll, Natt) genom att trycka på dagarna i en månadskalender. Rullande scheman (t.ex. 3-veckorsschema) kan kopieras framåt.
- **Vyer**: *Kommande* (lista vecka för vecka) och *Månad*. Filtrera på person.
- **Prenumerera i mobilen**: hela familjens kalender (eller en persons) som iCal-länk till iPhone/Google Kalender.
- Fungerar i mobilen – öppna sidan och välj *Lägg till på hemskärmen* så ser den ut som en app.

## Starta

Kräver Python 3.10+.

```bash
cd project1
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r familjekalender/requirements.txt
python -m familjekalender
```

Terminalen visar två adresser:

```
På den här datorn:  http://localhost:8080
På mobilen (samma wifi):  http://192.168.1.23:8080
```

Datan sparas i `familjekalender/data/familjekalender.db` (ingår inte i git).

## Kom igång

1. **Inställningar → Familjen**: lägg till alla, varje person får en färg.
2. **Inställningar → Kalendrar**: klistra in prenumerationslänken till lagets kalender och välj vems den är.
   - *laget.se*: lagets sida → *Kalender* → *Prenumerera / Exportera* (iCal). Kopiera länken.
   - *Förbund/serier*: leta efter *Prenumerera*, *Lägg till i kalender*, *iCal* eller en kalenderikon på lagets/seriens matchsida.
   - Har du bara en `.ics`-fil går den att ladda upp.
3. **Schema**: välj din fru, tryck *Lägg till vanliga pass* (eller skapa egna passtyper), välj ett pass och tryck på dagarna.
   Pass som slutar efter midnatt (natt) hanteras automatiskt. Under månaden visas antal pass och timmar.

## Inställningar (miljövariabler)

| Variabel | Standard | Betydelse |
|---|---|---|
| `FAMILJEKALENDER_LOSENORD` | (inget) | Kräver lösenord (valfritt användarnamn). Prenumerationslänkar kan använda `?nyckel=<lösenord>`. Sätt detta om appen nås utanför hemnätet. |
| `FAMILJEKALENDER_DB` | `familjekalender/data/familjekalender.db` | Var databasen sparas |
| `FAMILJEKALENDER_UPPDATERA_TIMMAR` | `3` | Hur ofta prenumererade kalendrar hämtas om |

Port: `python -m familjekalender --port 8090`.

## Tester

```bash
python -m pytest familjekalender/tests
```

## Uppbyggnad

| Fil | Gör |
|---|---|
| `app.py` | Flask-server och JSON-API |
| `ical_sources.py` | Hämtar och tolkar iCal (webcal, tidszoner, återkommande händelser, inställda matcher) |
| `store.py` | Arbetspass (nattpass, rullande schema) och sammanslagning av alla händelser |
| `export.py` | Familjens kalender som iCal-flöde |
| `static/` | Webbappen (HTML/CSS/JS, inga byggsteg) |

## Idéer för nästa steg

- Fler personers arbetsschema (fungerar redan – varje person kan ha egna passtyper)
- Egna händelser direkt i appen (tandläkare, kalas)
- Påminnelser / "vem kör?" för skjutsar
- Driftsätta på en Raspberry Pi eller i molnet så att den alltid är igång
