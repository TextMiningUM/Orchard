# Orchard — Project Guidelines

Orchard ("Kersenboomgaard Adviseur") is a single-domain agentic AI advisor for maximizing yield in a sweet-cherry orchard, built as a sister project to Auto Pilot (`../Auto Pilot`) and reusing its architecture/conventions wherever they fit a one-domain project. The authoritative current-state spec is [design_cherry_orchard_advisor.md](../design_cherry_orchard_advisor.md) (Deel A functional, Deel B technical, Deel C data inventory, Deel D folder structure, Deel E roadmap, Deel F open questions) — keep it up to date as phases complete, don't duplicate its content here.

## Core conventions (ported from Auto Pilot, one domain only: "Orchard")

- `core.paths.AgentPaths.orchard()` is the single source of truth for every path (`Data/Orchard/...`, `_models/Orchard/...`). Never hardcode paths elsewhere — extend `AgentPaths` instead.
- **Deterministic-core-first discipline**: the LLM (Qwen3-8B) never computes doses/thresholds itself. All risk/threshold calculations (chill hours, GDD, frost risk, spotted-wing-drosophila risk, rain-crack risk) live in `pipeline/orchard_phenology_spec.py` as pure, cited functions — explicitly labeled "illustrative placeholder" vs "real, cited" until Track 1 data backs them. When adding a new rule, follow that same pattern (pure function + docstring citation + explicit confidence label), don't let the LLM freelance a number.
- **Two-track data model** (mirrors Auto Pilot, scoped to this one domain):
  - **Track 1 — Rules & knowledge**: WUR, USDA, Ctgb, EU legislation, NFO/Actua Steenfruit. Acquired via `pipeline/ingest/build_orchard_corpus.py` into `Data/Orchard/OrchardKnowledge/` with `manifest.json` provenance (url, sha256, licence, acquired/blocked status). Re-running the script is idempotent (skips files already on disk) — extend the `SOURCES` registry rather than writing a new one-off script per source.
  - **Track 2 — Episodic**: the teler's own historical logbooks (2013–2026, handwritten, OCR/vision-transcribed), in `Data/Orchard/OrchardLogbooks/orchard_logbook.db` (SQLite: pages/entries/toepassingen). Built via `pipeline/ingest/build_logbook_database.py`, which refuses to overwrite human-verified rows without `--force`.
  - Both tracks are meant to feed the same eventual SFT/DPO fine-tune of Qwen3-8B, same as Auto Pilot's Captain/Chief Engineer — kept in separate files/tables so each competency stays traceable.

## Proprietary data: never push the teler's own business records

`Data/Data Log Books/` (raw scans), `Data/Orchard/OrchardLogbooks/orchard_logbook.db` (+ `_transcripts/`, `_raw_page_images/`), and `Data/Orchard/orchard_settings.json` (real farm address/coordinates) are **real, identifying business data about one specific farm** — which products, when, how much, exactly where. They are gitignored and must stay local-only (and local-only on the cloud pod's filesystem too, never re-exposed). Don't add scripts or app pages that copy this data into anything world-readable (the public cloud deployment already has its write-capable verification page disabled for this reason — see below). Track 1 knowledge-base documents (government/university publications) do not have this restriction and are tracked in git.

## Local vs cloud: two environments, different jobs

| | Local (laptop) | Cloud (LeafCloud GPU pod `orchard-v2`) |
|---|---|---|
| OS | Windows | Ubuntu |
| GPU | none required | NVIDIA A30, 24 GB VRAM |
| Workspace | `C:\Users\jcsch\Documents\Python\Orchard` | `/home/ubuntu/Orchard` (check actual remote path before assuming) |
| Python env | `.venv` (project-local, Python 3.13) | `.venv` (project-local, Python 3.13 via `uv`) — keep package-equivalent with local; data-pipeline packages only locally, full ML stack (torch/transformers/peft/trl/bitsandbytes) only needed on the pod |
| SSH | n/a | host/key/user are kept in the local-only `.env` (`ORCHARD_CLOUD_SSH_HOST/KEY/USER`), never committed |
| What runs here | Full Streamlit app for day-to-day use, data pipeline (corpus acquisition, logbook OCR/DB build), tests | Qwen3-8B inference server (`cloud/qwen_inference_server.py`, **port 8811**, localhost-only bind — never 8801, that port is already used by an Auto Pilot SSH tunnel on this same laptop), the read-only public mirror of the Streamlit app (nginx + Let's Encrypt HTTPS on `45-135-57-59.sslip.io`, systemd services `orchard-streamlit` + `orchard-qwen`), and later all actual QLoRA fine-tuning |

Never launch real model training on the pod's public-facing systemd services without checking the write-capable Verifieren page stays disabled (`app/pages/_6_Logboek_Verifieren.py.disabled` on the pod — rename, don't delete, to keep it discoverable). The public deployment is **read-only by design**: its DB file is `chmod 444` and the only interactive page is the Q&A chat (Track 1, deterministic tools + Qwen fallback with explicit hallucination warnings).

## Streamlit gotchas learned the hard way (don't rediscover these)

- Filenames/folders starting with `_` are skipped by Streamlit's page auto-discovery — this is the supported way to disable a page without deleting it.
- `st.dataframe()`: plain Python `round(x, n)` is **not** sufficient to control displayed decimals — use `st.column_config.NumberColumn(format="%.1f")` per column (or `.format({...})` when passing a pandas `Styler`).
- `use_container_width` is deprecated — use `width="stretch"` / `width="content"`.
- `st.dialog` works (Streamlit ≥1.65 confirmed) for the shared weather popup (`app/orchard_common.py::render_weather_dialog_button`) used by both `4_Logboek.py` and `6_Logboek_Verifieren.py` — extend that shared function rather than duplicating the dialog.
- `streamlit.testing.v1.AppTest` paths are resolved relative to the **calling script's location**, not cwd — a common source of false "file not found" failures in tests.

## External data sources: lessons already paid for

- **Geocoding**: Open-Meteo's geocoder only resolves place/city names, not full street addresses — `pipeline/orchard_tools.geocode_address()` uses OpenStreetMap Nominatim first (needs a descriptive `User-Agent`, informal ~1 req/sec limit), Open-Meteo as fallback.
- **Open-Meteo Archive/Forecast API**: confirmed working daily params are `temperature_2m_max/min`, `precipitation_sum`, `windspeed_10m_max`, `winddirection_10m_dominant`, `sunshine_duration` (seconds — divide by 3600 for hours), `et0_fao_evapotranspiration`.
- **WUR edepot.wur.nl** blocks bare/HEAD requests with 403 — needs a GET with a realistic browser `User-Agent`.
- **Ctgb bulk-export** (`ctgb.blob.core.windows.net/...xls`) is DNS-dead and `toelatingen.ctgb.nl` is a 403'd JS SPA — `check_ctgb_toelating()` stays a documented `NotImplementedError` stub, don't silently fake data for it.
- **EU 2018/848 EUR-Lex page**: the base CELEX HTML page fetched so far looks like mostly RDF/ELI metadata, not confirmed readable Dutch legal text — flagged as unresolved in the design doc's Deel F, needs re-checking before Track 1 chunking/RAG assumes it's usable.

## Tests

```
pytest tests -q
```
Add an `AppTest` smoke check for any new/changed Streamlit page alongside unit tests for any new pipeline function — this project has consistently caught regressions this way (e.g. the dashboard's weather-period slider, the shared weather dialog).
