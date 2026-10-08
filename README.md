# Orchard — Kersenboomgaard Adviseur

Een agentic AI-adviseur voor maximale opbrengst uit een kersenboomgaard: dezelfde architectuur als het [Auto Pilot](https://github.com/TextMiningUM/AutoPilot)-project (zie daar de Captain/Chief Engineer-domeinen), maar toegepast op kersenteelt in plaats van scheepvaart.

Voor de volledige werkafspraken (local-vs-cloud split, two-track datamodel, codeer-/testregels) zie [.github/copilot-instructions.md](.github/copilot-instructions.md) — dat bestand is het gezaghebbende regelboek. Dit README is slechts de kaart: wat bestaat er, en waar lees je meer.

## Ontwerp

[design_cherry_orchard_advisor.md](design_cherry_orchard_advisor.md) is de centrale spec: functioneel (Deel A), technisch (Deel B), data-inventaris (Deel C), mapstructuur (Deel D), roadmap (Deel E), open vragen (Deel F).

## Status

| Fase | Status |
|---|---|
| Ontwerp (functioneel + technisch) | Klaar |
| Walking skeleton (deterministische kern: chill-hours, GDD, nachtvorst, suzukii, scheurrisico + Streamlit-app) | Klaar, getest |
| Historische logboeken (2013–2026) ge-OCR'd naar database | Klaar — blijft lokaal, zie hieronder |
| Qwen3-8B live op cloud-GPU-pod (deterministische tools blijven leidend, LLM alleen voor open vragen) | Klaar |
| Publieke read-only demo via HTTPS | Klaar |
| Fase 2 — Track 1-kennisbank verzamelen (WUR/USDA/Ctgb/EU) | Loopt (7 documenten) |
| Chatbot: RAG + reranking + ReACT tool-calling + zichtbare CoT | Klaar |
| Patroonherkenning (automatische patroondetectie in het logboek) | Klaar |
| Fase 3-8 — RAG/KG/PG verder, trainingsdata, SFT/DPO-training, beslislaag, missielaag | Nog te doen |

## Eigen bedrijfsgegevens blijven lokaal

De map `Data/Data Log Books/` (ruwe scans) en de daaruit gebouwde `Data/Orchard/OrchardLogbooks/orchard_logbook.db` bevatten **echte bedrijfsgegevens van één specifieke boomgaard** (welke middelen, wanneer, hoeveel). Die zijn bewust buiten deze git-repo gehouden (`.gitignore`) en blijven alleen lokaal/op de eigen cloud-pod staan. De publiek ontsloten demo toont alleen de Track 1-kennisbank en een alleen-lezen chat; de verificatie-pagina voor logboeken is daar uitgeschakeld.

## Lokaal draaien

```powershell
.venv\Scripts\Activate.ps1
streamlit run app/Home.py
```

## Tests

```
pytest tests -q
```
