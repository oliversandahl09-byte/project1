# Channel brief

<!-- Agenten läser hela filen. Skriv fritt (svenska eller engelska går bra).
     - Lägg upp till 3 nischer under "Niches", var och en som en "### Rubrik".
       Du kan också lämna dem tomma och i stället säga vad du vill direkt:
       python -m ytagent run "gör 3 videos om rymden i mystisk stil"
     - Avsnittet "Settings" läses av koden: behåll formatet "- nyckel: värde". -->

## Audience
Teens and young adults, roughly 13-20, watching Shorts on their phone between other videos.
They decide in 1-2 seconds whether to keep watching. They hate being talked down to and love
"wait, what?" moments, relatable examples (school, friends, games, social media) and facts they can share.
Content must be appropriate for teenagers.

## Tone
Calm, confident narrator with wonder in the voice. Smart but never academic or preachy.
Short sentences. No fake hype ("insane", "you won't believe").

## Niches

### Deep ocean
EXAMPLE, replace or delete: Surprising facts about the deep sea and the creatures that live there.

## Avoid
Fearmongering, unverified claims, dangerous challenges, politics, anything not suitable for teens.

## Settings
- videos_per_run: 1
- max_videos_per_run: 5
- target_length_seconds: 40
- words_per_second: 2.6
- language: English
- format: shorts
- youtube_category_id: 28
- made_for_kids: false
- timezone: Europe/Stockholm
- publish_times: 16:00, 19:30
- max_per_day: 1
- buffer_days: 3
