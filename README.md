# Daily Briefing

Persönlicher Morgen-Podcast, täglich gegen 06:00 (Europe/Berlin) automatisch gebaut.

Pipeline: RSS-Feeds (`config/sources.yaml`) → Gemini Lauf 1 (clustern, bewerten) → Volltexte → Gemini Lauf 2 (Sprechskript) → edge-tts → MP3 als Release-Asset → `docs/feed-<slug>.xml` über GitHub Pages.

Redaktionslinie: `config/editorial.md`. Prompts: `prompts/`. Aussprache: `config/pronunciation.yaml`.

Setup: Secret `GEMINI_API_KEY`, Variable `FEED_SLUG`, Pages-Quelle "GitHub Actions". Lokal: `.env` mit `GEMINI_API_KEY`, dann `python src/fetch.py && python src/edit.py && python src/enrich.py && python src/script.py && python src/tts.py`.

Nur für den privaten Gebrauch. Die Folgen sind KI-Zusammenfassungen öffentlicher Nachrichten.
