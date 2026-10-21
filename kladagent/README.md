# Klädagenten

En hemsida där du beskriver vad du vill ha, eller skickar bilder på outfits du gillar, och en
AI-agent letar upp matchande second hand-plagg på **Vinted**, **Depop** och **Grailed**.

```
din text / outfitbilder ─► Claude tolkar stilen ─► söker på sajterna (webbsökning) ─► läser annonserna ─► bästa fynden + sökländar
```

## Starta

```bash
pip install -r requirements.txt
cp .env.example .env        # fyll i ANTHROPIC_API_KEY
python -m kladagent
```

Öppna sedan **http://127.0.0.1:5000** i webbläsaren.

## Så använder du den

- **Skriv exakt vad du vill ha:** "Brun Carhartt Detroit-jacka, storlek M, max 900 kr".
- **Eller skicka bilder:** klicka på bildikonen, dra in bilder eller klistra in (Ctrl/Cmd+V).
  Agenten känner igen plaggen, färger, passform och stil och letar liknande. Upp till 5 bilder.
- **Kombinera:** en bild + "fast i svart och billigare".
- **Fortsätt prata:** agenten minns sökningen, så du kan skriva "mer oversized", "bara Grailed" osv.
- **Filter:** välj sajter, maxpris, storlek och dam/herr.

Varje svar visar:
1. vad agenten förstod att du letar efter,
2. annonser den hittat (sajt, pris, storlek, skick och varför de matchar),
3. färdiga sökländar till Vinted, Depop och Grailed för varje sökord, så du alltid kan fortsätta leta själv.

En sökning tar ungefär 30 sekunder till ett par minuter.

## Hur det fungerar

| Fil | Gör |
|---|---|
| `app.py` | Flask-servern: sidan och `POST /api/search` (text, bilder, filter, tidigare meddelanden) |
| `agent.py` | Claude med webbsökning och webbhämtning begränsad till sajternas domäner; rapporterar via verktyget `report_results` |
| `platforms.py` | Domäner, söklänkar per sajt och kontroll av att en länk hör till rätt sajt |
| `models.py` | Datamodeller för förfrågan och resultat |
| `templates/`, `static/` | Själva hemsidan (chatt, bilduppladdning, resultatkort) |

Agenten visar bara annonslänkar som faktiskt dök upp i sökresultaten (inga påhittade länkar).
Om en sajt blockerar sökningen eller inget hittas får du ändå söklänkarna.

## Begränsningar

- Sajterna har inget öppet API, så agenten använder webbsökning. Den hittar det sökmotorer har
  indexerat, vilket inte alltid är de allra senaste annonserna. Därför finns söklänkarna.
- Annonser kan hinna säljas. Pris visas som annonsen angav det (Depop/Grailed ofta i £/$).
- Varje sökning kostar några cent till någon krona i Claude-API (mer med `KLAD_EFFORT=high`).
