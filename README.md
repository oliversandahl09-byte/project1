# YouTube Shorts-agent

En AI-agent som gör YouTube Shorts från början till slut: idé, manus, röst, stockfilm,
redigering, titel- och thumbnailvarianter, beskrivning, taggar och uppladdning.

```
brief.md / ditt uppdrag ─► plan (nisch, antal, stil) ─► idéer ─► manus ─► röst ─► stockfilm ─► redigering ─► 3 titlar/thumbnails ─► metadata ─► uppladdning (privat)
              ▲                                                                                        │
     style_guide.md + learnings.md + historik ◄──────────────── (steg 2: analytics) ◄──────────────────┘
```

## Status

| Steg | Klart |
|---|---|
| 1. En video från brief till privat uppladdning, godkännandeläge | ✅ |
| 2. Upp till 3 nischer, fritt uppdrag ("gör 3 videos om X i stil Y"), målgrupp 13–20 | ✅ |
| 3. Analytics (visningstid, retention, hook-retention, CTR om API:t ger det) → `learnings.md` → uppdaterad `style_guide.md` | ✅ |
| 4. Schemaläggning (publiceringstider, kö, `auto` för cron) | ✅ |

## Moduler

| Fil | Gör |
|---|---|
| `ytagent/brief.py` | Läser `brief.md` (målgrupp, upp till 3 nischer, inställningar) |
| `ytagent/planner.py` | Tolkar ditt uppdrag (antal, nisch, stil) eller roterar mellan nischerna |
| `ytagent/style.py` | Skapar/uppdaterar `style_guide.md` (kanalens smak) |
| `ytagent/ideas.py` | Unika idéer, undviker allt som redan gjorts |
| `ytagent/script.py` | Manus: hook (första sekunderna), body, call to action, sökord för film |
| `ytagent/voice.py` | Text-to-speech (OpenAI eller ElevenLabs), en ljudfil per segment |
| `ytagent/media.py` | Stockfilm från Pixabay och/eller Pexels (fritt licensierat), foto som reserv |
| `ytagent/editor.py` | ffmpeg: 1080×1920, undertexter, textöverlägg, musik, ljudnivå (−14 LUFS) |
| `ytagent/thumbnail.py` | 3 titel+thumbnail-varianter, Claude tittar på bilderna och väljer bäst |
| `ytagent/metadata.py` | Beskrivning, taggar, källor, krediter, AI-markering |
| `ytagent/youtube.py` | OAuth, uppladdning, thumbnail, publicera/schemalägg |
| `ytagent/pipeline.py` | Kör allt; en misslyckad video stoppar inte resten |
| `ytagent/history.py` | Minne över allt som gjorts + spärr mot för lika manus |
| `ytagent/analytics.py` | Hämtar statistik via YouTube Data API + YouTube Analytics API |
| `ytagent/learn.py` | Drar lärdomar → `learnings.md`, uppdaterar `style_guide.md` |
| `ytagent/scheduler.py` | Nästa lediga publiceringstid, hur många videos kön behöver |

Allt sparas i `output/<datum>_<namn>/` (manus, ljud, film, thumbnails, val och motivering).
Loggar hamnar i `logs/agent.log`.

## Installation

Kräver Python 3.10+ och ffmpeg.

```bash
# ffmpeg: macOS: brew install ffmpeg | Ubuntu: sudo apt install ffmpeg | Windows: winget install ffmpeg
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # fyll sedan i nycklarna
```

Valfritt: lägg ett fett typsnitt (t.ex. Inter Bold från Google Fonts, fri licens) i `assets/fonts/`
och musik du har rätt till i `assets/music/`.

## Nycklar (.env)

| Tjänst | Var | Kostnad (ungefär) |
|---|---|---|
| Claude | https://console.anthropic.com → API Keys | några kronor per Short. Sätt `CLAUDE_EFFORT=medium` för att spara |
| OpenAI TTS (standard) | https://platform.openai.com/api-keys | mycket billigt, under en krona per Short |
| ElevenLabs (bättre röst) | https://elevenlabs.io → Profile → API key, välj röst-ID i Voice Library | Starter-planen räcker till ca 40 Shorts/mån |
| Pixabay (filmklipp) | Skapa konto på https://pixabay.com, gå sedan till https://pixabay.com/api/docs/ där din nyckel står | gratis |
| Pexels (valfritt) | https://www.pexels.com/api/ (delar inte ut nya nycklar just nu) | gratis |

Rekommendation inom 200–500 kr/mån: börja med OpenAI TTS (rösten `onyx` eller `sage`).
Byt till ElevenLabs med `TTS_PROVIDER=elevenlabs` om du vill ha en mer mänsklig berättarröst.

## Google Cloud och YouTube-inloggning, steg för steg

1. Gå till https://console.cloud.google.com och logga in med kontot som äger YouTube-kanalen.
2. Skapa projekt: projektväljaren högst upp → **New project** → namn t.ex. `shorts-agent` → **Create**.
3. Aktivera API:er: **APIs & Services → Library**, sök upp och klicka **Enable** på
   - **YouTube Data API v3**
   - **YouTube Analytics API** (behövs i steg 2)
4. Inloggningsskärm: **APIs & Services → OAuth consent screen** (heter ibland *Google Auth Platform*).
   - User type: **External**. Appnamn och din e-post.
   - Under **Audience / Test users**: lägg till din egen Gmail-adress.
5. Skapa nyckel: **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type: **Desktop app** → **Create** → **Download JSON**.
   - Spara filen som `secrets/client_secret.json` i projektet.
6. Logga in:
   ```bash
   python -m ytagent auth
   ```
   Webbläsaren öppnas. Välj kanalen. Får du "Google hasn't verified this app" → **Advanced → Go to … (unsafe)**,
   det är din egen app. Inloggningen sparas i `secrets/token.json`.
7. Undvik att inloggningen går ut efter 7 dagar: så länge appen står i läget *Testing* går den ut varje vecka.
   Gå till **OAuth consent screen → Publish app** (läge *In production*). För eget bruk behöver du inte gå igenom Googles verifiering.

### Viktigt: YouTubes granskning (audit)

Videor som laddas upp via API från ett nytt, ogranskat Google Cloud-projekt **låses som privata** av YouTube.
Det passar godkännandeläget bra (du tittar först), men för att kunna publicera offentligt måste projektet
granskas: sök på "YouTube API Services Audit and Quota Extension Form" och ansök. Beskriv ärligt att verktyget
laddar upp egna, unika videos till din egen kanal med manuell granskning. Det tar ofta några veckor.

Standardkvoten är 10 000 enheter per dag. En uppladdning kostar mycket av den (historiskt ca 1 600 enheter),
så räkna med några uppladdningar per dag tills kvoten höjs.

## Användning

### Säg vad du vill ha

```bash
python -m ytagent run "gör 3 videos om rymden i mystisk stil"     # fritt uppdrag, svenska går bra
python -m ytagent run --niche "deep ocean" --count 2              # en nisch från brief.md
python -m ytagent run                                             # agenten roterar mellan nischerna i brief.md
python -m ytagent run "2 videos om hajar" --no-upload             # bara rendera, titta i output/ först
```

Nischerna är inte låsta. Skriv upp till 3 under `## Niches` i `brief.md` (agenten växlar mellan dem),
eller skippa dem helt och skriv vad du vill i kommandot. Målgruppen (13–20 år) och tonen står i `brief.md`.

### Godkänn och schemalägg

**Godkänn före publicering** är på som standard (`APPROVAL_REQUIRED=true`): videon laddas upp som privat och
länken till YouTube Studio skrivs ut. Titta, och sedan:

```bash
python -m ytagent list                       # allt agenten gjort, status, statistik
python -m ytagent approve VIDEO_ID           # schemaläggs på nästa lediga tid
python -m ytagent approve VIDEO_ID --now     # publicera direkt
python -m ytagent schedule                   # visa schemat och nästa lediga tider
```

Publiceringstider styrs i `brief.md` (`publish_times`, `timezone`, `max_per_day`). Standard är 16:00 och 19:30
(efter skolan och på kvällen), en video per dag. Har du fler tider än videos per dag växlar agenten mellan dem
så att statistiken kan visa vilken tid som funkar bäst.

Med `APPROVAL_REQUIRED=false` schemaläggs varje video direkt på nästa lediga tid (kräver godkänd audit, se ovan).

### Inlärning

```bash
python -m ytagent analyze
```

Hämtar statistik för videos som varit ute 2–60 dagar: visningar, genomsnittlig andel sedd, visningstid,
retention efter 3 och 5 sekunder (fångade hooken?), retention i slutet, delningar, prenumeranter och CTR
om YouTube ger ut det via API:t för din kanal (för Shorts är retention viktigare än CTR). När minst 3 videos har
statistik skriver Claude `learnings.md` (vad funkar, vad funkar inte, per nisch, experiment att testa) och
uppdaterar `style_guide.md`. Allt detta läses in inför nästa video.

### Helt automatiskt (cron)

`auto` gör allt i rätt ordning: hämtar statistik, uppdaterar lärdomar (högst var 3:e dag), försöker igen med
uppladdningar som misslyckats (t.ex. slut på kvot) och gör nya videos tills kön räcker `buffer_days` dagar framåt.
Videos som väntar på ditt godkännande räknas in i kön, så den gör inte mer än du hinner titta på.

```bash
# macOS/Linux: crontab -e, kör varje dag 09:05
5 9 * * * cd /sökväg/till/project1 && .venv/bin/python -m ytagent auto >> logs/cron.log 2>&1
```

Windows: Schemaläggaren (Task Scheduler) → Skapa grundläggande uppgift → Dagligen → Starta program:
`C:\sökväg\till\project1\.venv\Scripts\python.exe`, argument `-m ytagent auto`, starta i `C:\sökväg\till\project1`.

### Om något går fel

- Varje video körs för sig: om en misslyckas loggas felet i `logs/agent.log` och nästa fortsätter.
- Misslyckad uppladdning (t.ex. kvot slut): videon sparas som `rendered`. Kör `python -m ytagent upload` (eller vänta på `auto`).

## YouTubes regler och upphovsrätt

- **Unikt innehåll**: idéer och manus får se allt som gjorts tidigare, och ett manus som liknar en tidigare video
  för mycket stoppas automatiskt. Varje video ska svara på en egen fråga med eget värde.
- **Material**: bara Pixabay/Pexels (fri licens, krediteras ändå i beskrivningen, säker sökning på) och musik du själv lagt i `assets/music/`.
- **AI-markering**: med `AI_DISCLOSURE=true` sätts YouTubes flagga för syntetiskt innehåll (`containsSyntheticMedia`)
  och beskrivningen får en rad om AI-röst. YouTube kräver markering för realistiskt AI-innehåll; för en AI-berättarröst
  är det inte alltid ett krav, men öppenhet skadar inte.
- **Fakta**: manuset listar källor som hamnar i beskrivningen. Granska dem i godkännandeläget.
- **Ung publik**: innehållet hålls åldersanpassat (inga farliga utmaningar m.m.). Videorna markeras som
  *inte gjorda för barn* (`made_for_kids: false`), vilket stämmer för 13–20 år. Riktar du dig till barn under 13
  måste du ändra till `true` (då stängs kommentarer och vissa funktioner av YouTube).

## Kända begränsningar

- Egen thumbnail kräver verifierad kanal (telefonverifiering i YouTube). Misslyckas det fortsätter uppladdningen ändå.
  För Shorts visar YouTube ofta en bildruta ur videon i Shorts-flödet; den egna thumbnailen syns främst i sök och på kanalsidan.
- Undertexternas timing räknas från textlängd per segment, inte exakta ordtider. Ser bra ut i lugnt tempo.

---

# Fyndagent: kläder på Vinted, Depop och Grailed

Skriv vad du letar efter med egna ord. Agenten gör om det till sökord, söker på alla tre sajterna,
räknar om priser till kronor, sållar bort det som är för dyrt och låter Claude läsa annonserna
(och titta på bilderna) och ranka vad som faktiskt matchar, med en kort motivering.

```
din önskan ─► Claude: sökplan (sökord, storlek, maxpris, märke, krav) ─► Vinted + Depop + Grailed
          ─► pris i SEK, dubbletter bort ─► Claude rankar 0–10 med bilder ─► lista + HTML-sida med bilder
```

```bash
python -m fyndagent search "svart Carhartt Detroit-jacka, stl M, max 900 kr"
python -m fyndagent search "vintage Levis 501 W32 L32, ljus tvätt" --platforms vinted,depop
python -m fyndagent search "Arc'teryx Beta LT herr L" --max-price 2500 --limit 5
python -m fyndagent search "stone island tröja" --no-ai      # utan Claude: bara sökordet, ingen ranking
```

Varje sökning sparar `output/fynd/<datum>_<sökning>.html` (kort med bild, pris, poäng, motivering och länk)
och samma sak som `.json`. Öppna HTML-filen i webbläsaren.

### Bevakningar

Lägg till `--watch` så sparas sökningen. Kör sedan `check` när du vill (eller via cron) så visas bara
annonser som inte fanns förra gången. Annonser som redan bedömts skickas inte till Claude igen.

```bash
python -m fyndagent search "Salomon XT-6 stl 43, max 1200 kr" --watch
python -m fyndagent check            # alla bevakningar, bara nya annonser
python -m fyndagent watches          # lista
python -m fyndagent unwatch 2        # ta bort
# cron, var tredje timme: 0 */3 * * * cd /sökväg/till/project1 && .venv/bin/python -m fyndagent check >> logs/fynd.log 2>&1
```

### Inställningar (.env)

Behöver bara `ANTHROPIC_API_KEY` (samma som YouTube-agenten). Valfritt: `FYND_CURRENCY`, `VINTED_DOMAIN`
(t.ex. `www.vinted.de`), `DEPOP_COUNTRY`, `FYND_IMAGES=false` för att spara pengar, och växelkurserna
`FX_USD`/`FX_EUR`/`FX_GBP` (Grailed visar priser i USD). En sökning kostar ungefär en krona med bilder,
mindre med `--no-images` eller `CLAUDE_EFFORT=medium`.

### Bra att veta

- **Inga officiella API:er.** Vinted, Depop och Grailed har inga öppna sök-API:er, så agenten använder samma
  JSON-anrop som deras egna webbsidor gör. De kan ändras eller blockeras utan förvarning. Om en sajt slutar
  fungera skrivs det ut och de andra söks ändå. Använd det för eget bruk och sök i lugn takt
  (agenten väntar mellan anropen); automatiserad hämtning kan stå i strid med sajternas villkor.
- **Grailed** söker via Algolia med en publik söknyckel. Om Grailed ger HTTP 403: öppna grailed.com i Chrome,
  F12 → Network, sök på något, klicka på anropet till `algolia.net` och kopiera `x-algolia-api-key`
  till `GRAILED_ALGOLIA_KEY` i `.env`.
- **Priser** är annonspriset utan frakt och köparskydd. Grailed-priser räknas om med en ungefärlig kurs.
- Agenten köper eller kontaktar aldrig säljare, den hittar och rankar bara. Kolla äkthet själv innan du köper,
  Claude flaggar misstänkta kopior men kan inte garantera något.

## Tester

```bash
python -m pytest -q
```

Testerna kör hela flödet med låtsas-Claude, -röst och -film, men riktig ffmpeg-redigering och riktiga thumbnails.
Fyndagentens tester använder låtsas-svar från sajterna och kör utan nätverk.
