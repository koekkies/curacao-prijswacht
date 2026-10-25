# Curaçao prijswacht

Haalt met [Scrapling](https://github.com/D4Vinci/Scrapling) alle vluchten Amsterdam → Curaçao op
Google Flights op (KLM, TUI, Corendon en anderen) voor een gekozen datum, met speling in dagen.

- `scan.py` doet het werk en schrijft `results/latest.json`.
- `.github/workflows/scan.yml` draait het in GitHub Actions. Claude start de workflow elk uur
  met de datum die je op de prijzenpagina hebt ingesteld, en zet de uitkomst op die pagina.

Handmatig starten: tabblad **Actions** → **Prijzen ophalen** → **Run workflow**.
