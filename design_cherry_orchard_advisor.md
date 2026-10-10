# Ontwerp: Kersenboomgaard Adviseur (Cherry Orchard Advisor) — Track 1 (Orchard domain)

**Status (2026-10-09): ONTWERP + GROTENDEELS GEÏMPLEMENTEERDE WALKING SKELETON.** Dit document is
begonnen als zuiver ontwerp (Deel A-F, 2026-10-08) vóórdat er één regel implementatiecode was
geschreven — analoog aan hoe `design_captain_missions.md` en `design_chief_engineer.md` in het
Auto Pilot-project zijn opgezet (zie `C:\Users\jcsch\Documents\Python\Auto Pilot`). Sindsdien is een
aanzienlijk deel van Fase 0-3 van de roadmap ([Deel E](#deel-e)) daadwerkelijk gebouwd, getest en
gedeployed (lokaal + een publieke cloud-demo, zie [G.1](#sec-g1) voor de recente wijziging naar
niet-langer-read-only) — zie **[Deel G — Implementatiestatus](#deel-g)**
voor het volledige, chronologische verslag van wat er werkelijk staat, inclusief architectuurkeuzes
die afweken van dit oorspronkelijke ontwerp (met name: **Qwen3-8B in plaats van Mistral** als
basismodel, zie [B.7](#sec-b7) en [G.4](#sec-g4)). Deel A-F blijven de oorspronkelijke ontwerptekst,
bijgewerkt in-place waar de werkelijke implementatie ervan afweek of iets concreets invulde — Deel G
is de aparte "hoe zijn we hier gekomen"-laag erbovenop, zelfde conventie als Auto Pilot's eigen
design-docs (`design_captain_missions.md` §14-17 is het equivalent daar). Dit is bewust het eerste
domein-ontwerp van het Orchard-project; latere domeinen (bijv. een appel- of perenboomgaard) zouden
dezelfde pijplijn met een ander `domain=`-argument moeten hergebruiken, precies zoals VHF/OOW/
Captain/Chief Engineer in Auto Pilot één pijplijn delen.

Bronnen voor dit ontwerp:
- `Docs/Training an Orchard Agentic Chatbot with Real-World Data - Master project 20260322.pdf` (het
  oorspronkelijke project-idee/scriptie-opdracht — leidend voor scope en onderzoeksvragen)
- `Docs/Harnessing Artificial Intelligence for Agricultural Transformation 20260713.pdf` (World Bank
  rapport — bredere context/motivatie voor AI in landbouw)
- `Data/Data Log Books/jaar 2013.pdf` t/m `jaar 2026.pdf` (14 jaar handgeschreven logboeken, gescand —
  tekstextractie leverde aanvankelijk geen tekst op: dit zijn beeld-PDF's die OCR/multimodale
  verwerking nodig hebben, exact zoals het project-document voorspelt — **inmiddels opgelost, zie
  [C.1](#sec-c1)/[G.3](#sec-g3)**)
- `Data/Data Log Books/Actua steenfruit #6` en `#7` (2026) — vakbladartikelen van **StonefruitConsult**
  (samenwerking Delphy, Caf, Fruitconsult, gevestigd op Agro Business Park, Wageningen) met actueel
  geschreven teeltadvies per moment in het seizoen (koude-uren, bloei, snoei, bespuitingen, bestuiving)
- De architectuur en designconventies van `Auto Pilot/design_captain_missions.md` en
  `Auto Pilot/design_chief_engineer.md` (Captain = missie-niveau beslisser; Chief Engineer =
  deterministische conditie-/onderhoudslaag + RAG/KG/PG malfunction-chatbot) — dit ontwerp hergebruikt
  dezelfde architectuurprincipes, niet de maritieme inhoud.

## Inhoudsopgave

- [0. Kernidee en terminologie](#sec-0)
- [Deel A — Functioneel ontwerp](#deel-a)
  - [A.1 Probleemstelling](#sec-a1)
  - [A.2 Doelgroep en gebruikscontext](#sec-a2)
  - [A.3 Kernbelofte: de juiste ingreep op het juiste moment](#sec-a3)
  - [A.4 De teeltkalender als ruggengraat](#sec-a4)
  - [A.5 Persona's / rollen (naar analogie van Captain/OOW/Chief Engineer)](#sec-a5)
  - [A.6 Interactievormen](#sec-a6)
  - [A.7 Use cases (volledig uitgewerkt)](#sec-a7)
  - [A.8 Niet-doelen / afbakening](#sec-a8)
  - [A.9 Risico's, aansprakelijkheid en guardrails (functioneel)](#sec-a9)
- [Deel B — Technisch ontwerp](#deel-b)
  - [B.1 Architectuurprincipe: deterministische kern + LLM alleen voor taal/redenering](#sec-b1)
  - [B.2 Lagenmodel (mirror van Chief Engineer's Part A/B-split)](#sec-b2)
  - [B.3 Twee-tracks datamodel](#sec-b3)
  - [B.4 Geheugen: RAG + KG + PG + episodisch logboek](#sec-b4)
  - [B.5 Tools (agentic function calls)](#sec-b5)
  - [B.6 Procedure-/beslissingsregister per teeltfase (shield + mandatory duties)](#sec-b6)
  - [B.7 Model & training (Qwen3-8B, SFT → DPO → Reflection)](#sec-b7)
  - [B.8 Lokaal vs. cloud, `AgentPaths`-conventie, folderstructuur](#sec-b8)
  - [B.9 Streamlit-UI (mirror van Engine Room / Captain Mission dashboards)](#sec-b9)
  - [B.10 Evaluatieplan](#sec-b10)
  - [B.11 Guardrails (technisch)](#sec-b11)
- [Deel C — Data-inventarisatie](#deel-c)
  - [C.1 Reeds aanwezig (eigen data)](#sec-c1)
  - [C.2 Nederlandse / Wageningen-bronnen (open data)](#sec-c2)
  - [C.3 Internationale bronnen (USDA en anderen)](#sec-c3)
  - [C.4 Tool-APIs: weer, neerslag, bodem (geverifieerd, direct bruikbaar)](#sec-c4)
  - [C.5 Juridische/regelgeving-bronnen](#sec-c5)
  - [C.6 Vertaalstrategie EN→NL](#sec-c6)
  - [C.7 Gat-analyse — wat ontbreekt nog](#sec-c7)
- [Deel D — Mapstructuur `Data/Orchard/` (gerealiseerd)](#deel-d)
- [Deel E — Roadmap: walking skeleton eerst](#deel-e)
- [Deel F — Open vragen](#deel-f)
- [Deel G — Implementatiestatus (chronologisch verslag van wat werkelijk gebouwd is)](#deel-g)
  - [G.1 Lokale + cloud-infrastructuur](#sec-g1)
  - [G.2 Walking skeleton: deterministische kern + Streamlit-app](#sec-g2)
  - [G.3 Logboek-OCR en -database (Track 2)](#sec-g3)
  - [G.4 Qwen3-8B live op de cloud-pod (Fase 1)](#sec-g4)
  - [G.5 Track 1-kennisbank verzamelen (Fase 2)](#sec-g5)
  - [G.6 RAG + reranking + ReACT-agent + zichtbare CoT (Fase 3 — "Vraag de Adviseur")](#sec-g6)
  - [G.7 Patroonherkenning: meerjaren-trends](#sec-g7)
  - [G.8 Seizoenswaarschuwingen en preventieve weer-naar-ziekte-signalen](#sec-g8)
  - [G.9 Gebruik van Middelen](#sec-g9)
  - [G.10 Bibliotheek, Help en overige UI-afwerking](#sec-g10)
  - [G.11 Test- en kwaliteitsstatus](#sec-g11)
  - [G.12 Belangrijkste geleerde lessen / bugs opgelost](#sec-g12)
  - [G.13 Git/GitHub en synchronisatie](#sec-g13)
  - [G.14 Chat-UX: feedback/grounding, gespreksgeheugen en bewaarde chats](#sec-g14)
  - [G.15 Boomgaard-instellingen verhuisd naar een eigen "Instellingen"-pagina](#sec-g15)
  - [G.16 Fase 4: gerichte kennisbank-uitbreiding (10 praktijkproblemen) + retrieval-afstelling](#sec-g16)
  - [G.17 PDF-parseerfix (PyMuPDF) + automatische RAG-chunk-kwaliteitscontrole](#sec-g17)
  - [G.18 RAG-chunker vervangen door Auto Pilot's sectie/topic-boundary-aanpak + 200-probleem-kennisbank](#sec-g18)
  - [G.19 Logboek-scans niet zichtbaar op de pod: absoluut pad gefixt + Verifiëren-pagina heractiveerd](#sec-g19)
  - [G.20 Menu-volgorde herschikt naar logische groepering](#sec-g20)
  - [G.21 Inference-snelheid: migratie naar vLLM (AWQ), streaming, adaptieve thinking-budget](#sec-g21)
  - [G.22 Gouden eval-set + meetharnas (retrieval hit@k, grounding, latency) en de eerste baseline](#sec-g22)
  - [G.23 Documenten → gestructureerde JSON → chunk-definitie in de JSON (Auto Pilot's OOW/VHF-aanpak)](#sec-g23)
  - [G.24 Chunk-kwaliteitscontrole (QC) als poort voor RAG/KG/PG + knop "Controleer RAG Chunks"](#sec-g24)
  - [G.25 RAG herbouwd uit de gestructureerde JSON: bge-m3, geen reranker](#sec-g25)
  - [G.26 Procedure: hoe we RAG bouwen en QC doen, en de Code Library](#sec-g26)
  - [G.27 KG, PG, OAC, logboek-RAG, trainingsdata, antwoord-eval en analyse (2026-10-10)](#sec-g27)
  - [G.28 Meetbetrouwbaarheid, held-out set, reward, rejection sampling en SFT-rondes (2026-10-10)](#sec-g28)
  - [G.29 Waterbalans: dag-tot-dag delta neerslag minus verdamping, te droog of te nat (2026-10-10)](#sec-g29)
  - [G.30 Logboek-kalender: "wat deed ik rond deze tijd?" en wat het logboek over de nazorg zegt (2026-10-10)](#sec-g30)
  - [G.31 Middel opzoeken: Ctgb-voorschrift (open API) + eigen logboek + agentic tool, multi-hop-ontwerp (2026-10-10)](#sec-g31)
- [Deel H — Aanbevelingen voor de teler: wat meten en vastleggen vanaf 2027](#deel-h) *(los te lezen; bedoeld om aan de teler te geven)*
  - [H.0 Waarom dit nodig is](#sec-h0) · [H.1 Vijf spelregels](#sec-h1) · [H.2 De korte lijst (begin hier)](#sec-h2) · [H.3 Volledig overzicht per onderwerp](#sec-h3)
  - [H.4 Camera's](#sec-h4) · [H.5 Jaarkalender 2027](#sec-h5) · [H.6 Wat de adviseur met elke meting doet](#sec-h6) · [H.7 Starterspakket](#sec-h7) · [H.8 Wat wij bouwen om dit te ontvangen](#sec-h8)
- [Deel I — Plan voor seizoen 2027: fases, beslismomenten, bouwlijst, succescriteria en risico's](#deel-i)
  - [I.0 Doel](#sec-i0) · [I.1 Beginstand](#sec-i1) · [I.2 Besluiten vóór 1 december](#sec-i2) · [I.3 Tijdlijn per fase](#sec-i3) · [I.4 Bouwlijst](#sec-i4) · [I.5 Succescriteria](#sec-i5) · [I.6 Risico's](#sec-i6) · [I.7 Bewust niet](#sec-i7) · [I.8 Eerstvolgende stappen](#sec-i8)

---

<a id="sec-0"></a>
## 0. Kernidee en terminologie

We bouwen een **domeinspecifieke agentic adviseur voor de zoete-kersenteelt** (*Prunus avium*), die op
elk moment in het seizoen kan vertellen: *wat is er nu aan de hand in de boomgaard, en wat is de beste
volgende ingreep, gegeven weer, bodem, fenologie, historie en wet- en regelgeving*. Het doel is
**maximale opbrengst en kwaliteit binnen de grenzen van (steeds strenger wordende) biologische/
geïntegreerde teelt-regelgeving** — niet maximale opbrengst tegen elke prijs.

Net als in Auto Pilot geldt hier een harde architectuurkeuze (zie [B.1](#sec-b1)): het LLM is er niet om
zelf te "beslissen of 20°C en wind-NO een reden is om te sproeien" — dat is een deterministische
berekening (koude-uren, degree-days, vorstrisico, regenkans). Het LLM legt uit, redeneert over
afwegingen, doorzoekt de kennisbank, en formuleert het advies in natuurlijke, vakkundige taal — precies
de rolverdeling die `chief_engineer_agent_spec.py` al hanteert ("deterministic condition layer, LLM only
for explanation").

| Begrip | Betekenis in dit project |
|---|---|
| **Teler** | De eindgebruiker — de mens die de boomgaard runt en het advies krijgt/goedkeurt. Analoog aan de "Captain" die eindverantwoordelijk blijft. |
| **Teeltadviseur-agent** | De hoofdagent / orchestrator — mirror van de Captain-laag in Auto Pilot. |
| **Specialisten** | Sub-agents/deterministische modules per vakgebied (gewasbescherming, bemesting/bodem, weer/irrigatie, oogst/kwaliteit) — mirror van OOW/Chief Engineer als "sub-officieren". |
| **Fenologische fase** | Rust, knopzwelling, bloei, vruchtzetting, celdeling, kleuring/rijping, oogst, nazorg/herstel — de "missie-fases" van een kersenseizoen. |
| **Brown envelope / event** | Onverwachte gebeurtenis die ingrijpen vereist: laat-voorjaarsvorst, hagelbui vlak voor oogst, plotselinge regen tijdens bloei (bestuivingsrisico), Drosophila suzukii-uitbraak, resistente schimmelstam, etc. — rechtstreeks analoog aan Captain's "brown envelopes" (§4 van `design_captain_missions.md`). |

---

<a id="deel-a"></a>
# Deel A — Functioneel ontwerp

<a id="sec-a1"></a>
## A.1 Probleemstelling

1. **Kennisverlies**: ervaren tuinders gaan met pensioen; decennia aan "welke ingreep werkte wanneer"
   staat alleen in handgeschreven logboeken (zie `Data/Data Log Books/jaar 2013-2026.pdf`, in totaal
   ca. 14 seizoenen).
2. **Toenemende complexiteit**: verplichte omschakeling naar biologische/geïntegreerde
   gewasbescherming (EU 2018/848, Green Deal-doelstellingen) terwijl economisch resultaat (opbrengst,
   kwaliteit, barstgevoeligheid) overeind moet blijven.
3. **Tijdskritische beslissingen**: veel ingrepen hebben een smal tijdvenster (bijv. wortelsnoei
   "uiterlijk twee weken vóór de bloei", eerste bespuiting "ruim voordat de eerste bloemen opengaan",
   zie het voorbeeld in [C.1](#sec-c1)) — een gemiste dag kan het effect van een ingreep tenietdoen of
   averechts maken.
4. **Algemene LLM's zijn hier ongeschikt**: generiek advies hallucineert doseringen, kent de lokale
   boomgaard niet, en kan onbedoeld een niet-toegelaten middel aanraden — in de landbouw met reële
   juridische en economische consequenties (zie ook het masterproject-document, sectie "The Limitation
   of General-Purpose AI").

<a id="sec-a2"></a>
## A.2 Doelgroep en gebruikscontext

- **Primair**: de kersenteler zelf (en evt. bedrijfsopvolgers/personeel), die dagelijks/wekelijks een
  praktische vraag heeft ("moet ik nu wortelsnoeien gezien de regen van komende week?", "is dit de
  juiste timing voor de eerste minerale-oliebespuiting?").
- **Secundair (latere fase, zie masterproject-doc "democratiseren")**: andere steenfruittelers die
  via een gedeeld platform van hetzelfde systeem gebruik gaan maken — een "data flywheel" over
  meerdere bedrijven heen. **Voor dit eerste ontwerp beperken we de scope expliciet tot één
  boomgaard/bedrijf** (de eigen logboeken); multi-tenant/multi-bedrijf is een latere fase.
- **Gebruikscontext**: zowel op kantoor (planning, vooruitkijken) als **in het veld** (telefoon/tablet,
  vraag stellen staand tussen de bomen, bijv. bij constatering van een plaag).

<a id="sec-a3"></a>
## A.3 Kernbelofte: de juiste ingreep op het juiste moment

Het systeem combineert vier soorten informatie om tot één concreet advies te komen — dit is het
hart van het product:

```
[Fenologische status]  +  [Actuele/voorspelde omgeving]  +  [Historie & kennis]  +  [Regelgeving]
      (koude-uren,           (weer, neerslag, bodem-         (eigen logboeken,       (Ctgb-toelating,
    ontwikkelingsstadium)      vocht, temperatuur)           WUR/Actua Steenfruit,     EU-bio-regels,
                                                              USDA historisch)         doseringslimieten)
                                        │
                                        ▼
                         Gevalideerd, uitlegbaar, citeerbaar advies
                    ("Doe X, vóór datum Y, omdat Z — bron: <citatie>")
```

Dit is exact de "cost()/regret()"-achtige deterministische-kern-eerst-filosofie van Captain/Chief
Engineer, toegepast op fenologie/gewasbescherming in plaats van op scheepsmissies.

<a id="sec-a4"></a>
## A.4 De teeltkalender als ruggengraat

In plaats van Captain's "waypoints langs een route" is de ruggengraat hier de **fenologische
jaarcyclus** van de kersenboom. Elke fase heeft een eigen set beslissingen, risico's en
tijdsvensters (bronnen: Actua Steenfruit #6/#7 2026, WUR-kennisbank, en de logboek-voorbeelden uit
het masterproject-document):

| Fase | Periode (NL, indicatief) | Typische beslissingen in deze fase | Typisch risico ("brown envelope") |
|---|---|---|---|
| **Rust / koude-accumulatie** | nov–feb | koude-uren bijhouden t.o.v. rasvereiste (bijv. Kordia ≈1400 u); winterbemesting/bodemanalyse plannen | te zachte winter → onvoldoende koude-uren → onregelmatige bloei |
| **Knopzwelling / ontwaken** | half feb–maart | eerste bespuiting (minerale olie tegen spint/luis-eieren), wortelsnoei (bij te sterke groei, "uiterlijk 2 weken vóór bloei"), inzagen/boomevenwicht herstellen | te vroege bespuiting bij vorst → gewasverbranding |
| **Bloei** | eind maart–april | bestuivers regelen (≥5 bijenvolken/ha + hommels/metselbijen), géén gewasbeschermingsmiddel schadelijk voor bestuivers, vorstbewaking (nachtvorst tijdens bloei = directe oogstderving) | nachtvorst tijdens bloei; regen/kou → slechte bestuiving; bijensterfte |
| **Vruchtzetting / celdeling** | april–mei | voedingsbespuitingen (bijv. ureum, borium, kalifosfaat zoals in logboek-voorbeeld), dunnen indien nodig, taludcontrole gewasbescherming (Suzuki-fruitvlieg-monitoring start) | hagel; late vorst; onbalans in boom (takken/harttakken kraken) |
| **Groei / rijping** | mei–juni(–juli, ras-afhankelijk) | irrigatie-/vochtsturing (barstgevoeligheid bij regen vlak voor oogst!), gewasbescherming tegen Drosophila suzukii o.b.v. degree-day-model, overkapping/regenkappen beslissingen | regen vlak vóór oogst → vruchtbarsten; kersenvlieg-uitbraak |
| **Oogst** | juni–augustus (ras-afhankelijk) | oogsttiming o.b.v. brix/kleur/weersvoorspelling, arbeidsplanning, logistiek | regen/hagel net voor/tijdens oogst; hitte → kwaliteitsverlies |
| **Nazorg / herstel** | aug–okt | zomersnoei, bodemherstel/bemesting na oogst, ziektepreventie (bacterievuur/Pseudomonas), voorbereiding volgende winterrust | te late zomersnoei → wondinfectie bij regen |

Deze tabel wordt in de techniek de basis voor het **procedure-/beslissingsregister** ([B.6](#sec-b6)),
net zoals Captain's `PROCEDURE_LIBRARY` één entry per event-type heeft.

<a id="sec-a5"></a>
## A.5 Persona's / rollen

Mirror van Auto Pilot's "Captain (orchestrator) + OOW/Chief Engineer (specialisten)"-opzet, hier
toegepast op de boomgaard:

| Rol | Analoog aan (Auto Pilot) | Verantwoordelijkheid |
|---|---|---|
| **Teler** | Captain (mens, eindverantwoordelijk) | Stelt vragen, geeft seizoensdoelen op ("max. opbrengst Kordia dit jaar"), keurt ingrepen goed |
| **Teeltadviseur-agent** (orchestrator) | Captain-agent | Houdt seizoensoverzicht bij, bepaalt prioriteit tussen concurrerende adviezen, communiceert in natuurlijke taal |
| **Gewasbeschermingsspecialist** | Chief Engineer (Part A: conditiebewaking) | Monitort plaagdruk (Drosophila suzukii-model, schimmeldruk o.b.v. blad-nat-uren), toetst elk voorstel aan Ctgb-toelating |
| **Bemestings- & bodemspecialist** | Chief Engineer (Part A, ander subsysteem) | Volgt bodem-pH, EC, vochtgehalte, nutriëntenstatus; adviseert bemestingsmoment/-middel |
| **Weer- & fenologiespecialist** | OOW (voortdurende monitoring/navigatie) | Berekent koude-uren, growing-degree-days, vorst-/regenrisico, bloeivoorspelling |
| **Oogst- & kwaliteitsspecialist** | — (nieuw, geen directe analogie) | Voorspelt optimaal oogstmoment o.b.v. brix/kleur-curve + weersvoorspelling |
| **Kennis-/Compliance-specialist (Critic Agent)** | Chief Engineer's Part B (RAG+KG+PG) + Captain's "shield" | Doorzoekt wetgeving/Ctgb/WUR-kennisbank; blokkeert/herschrijft adviezen die niet-toegelaten middelen, overdosering, of niet-biologische methoden bevatten |

Net als bij Chief Engineer ("niet één model voor alles") is de verwachting dat de
Gewasbeschermings-, Bemestings- en Weerspecialisten **grotendeels deterministische code** zijn (zie
[B.1](#sec-b1)), en dat er uiteindelijk één fijngetuned Mistral-model is dat de rol van
Teeltadviseur + Compliance-uitleg speelt, gevoed door de outputs van de deterministische
specialisten als tool-resultaten — exact zoals Captain één getraind model is dat Chief Engineer's
deterministische `compute_engine_status()`-achtige functies als tools aanroept.

<a id="sec-a6"></a>
## A.6 Interactievormen

1. **Chat / vraag-antwoord** (primair, mirror van VHF/Chief Engineer's chatbot-interface): teler stelt
   een vrije-tekstvraag, agent antwoordt met advies + onderbouwing + bronverwijzing.
2. **Proactieve waarschuwingen/alerts** (mirror van Captain's "brown envelope" monitors): het systeem
   draait continu monitors (vorstrisico vannacht tijdens bloei, regen binnen 24u vóór oogst,
   kersenvlieg-drempelwaarde overschreden) en **duwt** een melding naar de teler zonder dat erom
   gevraagd is.
3. **Dashboard** (mirror van Engine Room/Captain Mission-pagina's, zie [B.9](#sec-b9)): overzicht van
   actuele fenologische status, koude-uren-teller, komende verplichte acties, open waarschuwingen.
4. **Logboek-invoer** (nieuw t.o.v. Auto Pilot): de teler kan een uitgevoerde ingreep terugmelden
   ("vandaag Signum gespoten, 0.25 kg"), wat het episodische geheugen bijwerkt én een trainings-rij
   oplevert voor de volgende fine-tune-ronde (de "data flywheel" uit het masterproject-document).

<a id="sec-a7"></a>
## A.7 Use cases (volledig uitgewerkt)

### UC-1 — Directe vraag met context
> *Teler: "Het is eind mei, lichte regen, en er is risico op vruchtrot. Wat deden we vorig jaar?"*

Agent-stappen (ReAct-stijl, mirror van Captain's `ask_captain()`-patroon):
1. Roep `lookup_logbook(periode="eind mei", onderwerp="vruchtrot")` aan → vindt logboekregel("24-05,
   lichte regen, Signum toegepast voor vruchtrot").
2. Roep `check_ctgb_toelating(middel="Signum", gewas="kers")` aan → nog toegelaten? dosering ok?
3. Roep `get_weather(now, +3 dagen)` aan → bevestigt actuele regenkans.
4. Genereer antwoord: *"Historisch werd op 24 mei bij lichte regen Signum (0,25 kg) toegepast in
   combinatie met Total Leaf-mix ter voorkoming van vruchtrot (Botrytis). Signum is nog toegelaten
   voor kers bij de huidige dosering (bron: Ctgb, datum). Gezien de huidige regenverwachting
   (bron: weer-tool) is dit ook nu een geschikt moment."*

### UC-2 — Proactieve vorstwaarschuwing tijdens bloei
Monitor detecteert (via `get_weather`) een voorspelde minimumtemperatuur onder de kritieke
bloei-vorstgrens de komende nacht. Systeem stuurt ongevraagd een melding met aanbevolen
tegenmaatregelen (vorstberegening, rookpotten, etc. — afhankelijk van wat de boomgaard feitelijk
heeft) en logt de gebeurtenis als "brown envelope"-event voor latere evaluatie.

### UC-3 — Timing van wortelsnoei
> *Teler: "Moet ik deze week wortelsnoeien?"*
Agent combineert: (a) fenologische status (hoe ver vóór bloei zijn we — harde regel: "uiterlijk twee
weken vóór de bloei", zie Actua Steenfruit #6), (b) bodemvocht/weer (droog weer nodig), (c) groeikracht
van de boom (indien gelogd) om te bepalen of wortelsnoei agronomisch nodig is. Antwoord bevat een
concrete ja/nee met motivatie en einddatum-waarschuwing.

### UC-4 — Bespuitingsplanning met kersenvlieg-model
Specialist "Gewasbescherming" berekent degree-day-accumulatie voor Drosophila suzukii (SIMKEF-achtig
model, zie [C.3](#sec-c3)) uit uurtemperaturen (Open-Meteo/KNMI) en waarschuwt wanneer de
risicodrempel voor eiafzet nadert, met een voorstel voor het eerstvolgende toegelaten middel/moment.

### UC-5 — Oogsttiming-advies
Rond de verwachte oogstdatum combineert de Oogstspecialist een eenvoudige brix/kleur-curve
(indien gemeten/gelogd) met de regenverwachting de komende dagen, om barstschade te voorkomen
("plan de oogst vóór donderdag; vanaf vrijdag wordt >15mm regen voorspeld, wat het barstrisico bij dit
rijpingsstadium significant verhoogt").

### UC-6 — Compliance-check / Critic-agent
Teler: *"Kan ik een dubbele dosis gebruiken om tijd te besparen?"* → Compliance-specialist blokkeert
het voorstel hard (analoog aan Captain's "shield": "nooit de door de Chief Engineer vastgestelde
veilige snelheid overschrijden") met verwijzing naar de wettelijke maximumdosering uit de
Ctgb-databank, en biedt een compliant alternatief.

<a id="sec-a8"></a>
## A.8 Niet-doelen / afbakening (v1)

- **Geen** financieel/markt-advies (prijsvoorspelling, verkoopstrategie) — puur agronomisch/
  teelttechnisch.
- **Geen** juridisch bindend advies; het systeem citeert regelgeving maar vervangt geen formele
  Ctgb-raadpleging of erkend adviseur bij twijfel.
- **Geen** automatische actuatie (het systeem spuit/besproeit niet zelf — het *adviseert*; de teler
  voert uit). Eventuele IoT-actuatie is expliciet toekomstwerk (masterproject-doc noemt dit zelf als
  "Future Expansions").
- **Geen** multi-bedrijf/multi-tenant in v1 — dat is een latere "data flywheel"-fase.
- **Geen** beeldherkenning/foto-diagnose in v1 (wordt wel als tool-uitbreiding voorzien, zie
  [B.5](#sec-b5) en [C.7](#sec-c7)) — de bestaande logboeken zijn immers zelf al gescande
  beeld-PDF's die OCR nodig hebben, dus multimodale verwerking is sowieso nodig voor data-inname, maar
  live pest-foto-diagnose in het veld is een latere uitbreiding.

<a id="sec-a9"></a>
## A.9 Risico's, aansprakelijkheid en guardrails (functioneel)

- **Hallucinatierisico bij doseringen/middelnamen** → nooit vrij genereren; middel + dosering + gewas
  moet altijd via de Ctgb-tool geverifieerd worden vóór het advies getoond wordt (harde regel, zie
  [B.11](#sec-b11)).
- **Verouderde toelatingen** → Ctgb-toelatingen vervallen/veranderen; elk advies toont een
  ophaaldatum ("geldig per <datum>, raadpleeg Ctgb voor actuele status") — zelfde disclaimer-stijl als
  StonefruitConsult zelf hanteert in Actua Steenfruit.
  - rechtstreeks disclaimer-voorbeeld uit de bron: *"StonefruitConsult is niet aansprakelijk voor
    schade die ontstaat door het uitvoeren van een advies wanneer dit schadelijk gevolg op dit moment
    nog niet bekend was."* — dit ontwerp neemt een vergelijkbare disclaimer over voor elk gegenereerd
    advies.
- **Bestuiverveiligheid** → elk gewasbeschermingsvoorstel tijdens de bloeiperiode wordt getoetst op
  bijenveiligheid (een hard "nooit"-criterium, mirror van Captain's shields).
- **Eindverantwoordelijkheid blijft bij de teler** — het systeem presenteert advies + onderbouwing,
  geen onomkeerbare acties.

---

<a id="deel-b"></a>
# Deel B — Technisch ontwerp

<a id="sec-b1"></a>
## B.1 Architectuurprincipe: deterministische kern + LLM alleen voor taal/redenering

Rechtstreeks overgenomen uit `chief_engineer_agent_spec.py`'s eigen docstring-principe: *"Pure stdlib,
dependency-free dataclasses + deterministic functions ... a single source of truth for condition
evaluation / RUL estimation / maintenance recommendation, importable by BOTH the live interface AND any
future training-data generator, so the two never drift out of sync."*

Voor Orchard betekent dit:

- **Fenologie-/risicoberekeningen zijn pure functies**, geen LLM-output: koude-uren-accumulatie,
  growing-degree-days, vorst-risicoscore, Drosophila suzukii-degree-day-model, barst-risico-index
  (regen × rijpingsstadium). Dit is de orchard-equivalent van `compute_engine_status()`.
- **Elke "harde grens" (shield) is code, niet een LLM-instructie**: max. dosering uit Ctgb, verbod
  tijdens bloei op bij-onveilige middelen, wettelijke wachttijd vóór oogst. Een LLM die "vergeet" een
  instructie te volgen is een bekend faalmodus; een harde Python-check kan dat niet vergeten.
- **Het LLM (Mistral, fine-tuned) doet**: natuurlijke-taal-begrip van de vraag, oproepen van de juiste
  tool(s) in de juiste volgorde (ReAct), samenvatten/verklaren van deterministische uitkomsten,
  citeren van RAG-bronnen, en — na DPO — het *prioriteren* van biologisch/duurzaam advies boven
  chemisch-zwaar advies bij gelijke effectiviteit (exact de RLHF/DPO-casus uit het
  masterproject-document: "Answer A chemisch (rejected) vs Answer B organisch (preferred)").

Net als bij Captain/Chief Engineer geldt: **nooit** laten we het LLM zelf een dosering of
toelatingsstatus "verzinnen" — dat is altijd een tool-call naar een deterministische/geverifieerde
bron.

<a id="sec-b2"></a>
## B.2 Lagenmodel (mirror van Chief Engineer's Part A/B-split)

| Laag | Chief Engineer-equivalent | Orchard-invulling |
|---|---|---|
| **Part A — Deterministische conditiebewaking** | `chief_engineer_agent_spec.py` (ConditionLimit/ConditionVerdict/MaintenanceRecommendation) | `orchard_phenology_spec.py` (toekomstig bestand): `PhenologyLimit` / `PhenologyVerdict` / `ActionRecommendation` — koude-uren, GDD, vochtstress, plaagdruk-drempels, elk met `source_citation` (WUR/Ctgb/USDA/Actua Steenfruit) |
| **Part B — RAG+KG+PG kennis-/malfunction-chatbot** | `chief_engineer_memory.py` (hybrid dense+concept-graph+PG retrieval over manuals + known-issues traces) | `orchard_memory.py` (toekomstig bestand): hybride retrieval over (1) wetgeving/Ctgb, (2) WUR/Actua Steenfruit-vakliteratuur, (3) eigen logboeken 2013–2026 als episodische "known-issues"-traces |
| **Fix-it / beslissingslaag** | `chief_engineer_decision.py` + `FAULT_MODES`/`ToolSpec`-registry | `orchard_decision.py` (toekomstig): `RISK_MODES`-registry (vorst, barst, plaagdruk, nutriëntentekort) × `ActionSpec`-registry (ingrepen: bespuiten, snoeien, irrigeren, dunnen) |
| **Missielaag (seizoen)** | `chief_engineer_mission.py` (meerdere events, resource-schaarste, reward-functie) | `orchard_season.py` (toekomstig): één seizoen = een opeenvolging van fenologische fases + brown-envelope-events, met een samengestelde reward (opbrengst-proxy, kwaliteit-proxy, compliance-schendingen, duurzaamheids-score) |

<a id="sec-b3"></a>
## B.3 Twee-tracks datamodel

Exacte toepassing van Auto Pilot's kernregel ("every domain's pipeline has two parallel tracks... not
optional extras, both are first-class"):

| | **Track 1 — Regels & Vakkennis** | **Track 2 — Episodisch/conversationeel (eigen boomgaard)** |
|---|---|---|
| **Bronnen** | Ctgb-databank, EU 2018/848 + NL-wetgeving, WUR/Groen Kennisnet-publicaties, Actua Steenfruit-nieuwsbrieven, USDA/CHLA historische (1850–1930) teksten | Eigen logboeken `jaar 2013.pdf`…`jaar 2026.pdf` (OCR/multimodaal te verwerken), toekomstige oogst-/opbrengstregistraties |
| **Eval-data (held-out, NOOIT trainen op)** | `Data/Orchard/Orchard_Eval/orchard_gold_qa.json` — Q&A-paren over regelgeving/agronomie met geverifieerd goed antwoord + bron | `Data/Orchard/Orchard_Eval/orchard_scenarios.json` — realistische seizoens-scenario's (weer+fenologie+historie) met het "gouden" advies |
| **Trainingsdata** | `orchard_sft_rag.jsonl`, `orchard_multihop.jsonl`, `orchard_dpo_pairs.jsonl` (chemisch vs. organisch, zie RLHF-voorbeeld), `orchard_reflection.jsonl` | `orchard_conversations.jsonl` (ruwe dialogen afgeleid van logboekregels) → gemined naar `orchard_logbook_sft_*.jsonl`, `orchard_logbook_multihop.jsonl`, `orchard_logbook_dpo_pairs.jsonl` |
| **Eval-script** | `eval_finetuned.py` (hergebruikt patroon) | `eval_orchard_scenarios.py` (hergebruikt patroon) |

Beide tracks voeden dezelfde QLoRA-fine-tune (SFT → DPO → Reflection), maar blijven in gescheiden
bestanden zodat de bijdrage van elke competentie traceerbaar blijft — zelfde regel als Auto Pilot's
copilot-instructions hanteert.

<a id="sec-b4"></a>
## B.4 Geheugen: RAG + KG + PG + episodisch logboek

Mirror van Chief Engineer's Part B (§4 `design_chief_engineer.md`):

- **RAG (vector-retrieval)**: chunked (semantisch, ~500 woorden, met behoud van complete
  tabel-regels/paragrafen — exact de eis uit het masterproject-document) uit wetgeving,
  WUR-publicaties, Actua Steenfruit-nummers, USDA/CHLA-historische teksten.
- **Neurale reranker** (proprietary, fine-tuned cross-encoder — masterproject-doc noemt expliciet
  ColBERTv2/BGE-Reranker/Cohere Rerank v3 als voorbeeldarchitecturen): getraind op
  [Vraag]+[Beste-antwoord]-paren gemined uit de logboeken (bijv. "Suzuki-fruitvlieg waargenomen" →
  de exacte ingreep die toen succesvol was).
- **KG (kennisgraaf)**: *probleem → oorzaak → ingreep*-graaf, analoog aan Chief Engineer's
  *fault→cause→system→corrective-action*-graaf. Voorbeeld: `vruchtrot (Botrytis) → vochtige
  bloemresten/dichte stand → Signum/koperbespuiting + luchtiger snoei`.
- **PG (procedure-graaf)**: stap-voor-stap-procedures (spuitschema-opbouw, wortelsnoei-procedure,
  inzaag-procedure) — analoog aan Chief Engineer's startup/shutdown/PMS-procedures.
- **Episodisch logboek-geheugen**: elke seizoensinteractie (ingreep + context + — later — uitkomst)
  wordt weggeschreven als nieuwe episodische rij, zodat het systeem na verloop van jaren zelf nieuwe
  "logboekregels" opbouwt — dit sluit de feedback-lus die het masterproject-document noemt
  ("correlate past agronomic actions with actual outcomes").

<a id="sec-b5"></a>
## B.5 Tools (agentic function calls)

Mirror van `captain_tools.py`/`chief_engineer_tools.py`'s `ToolSpec`-registry-patroon: elke tool is een
klein, gedocumenteerd, deterministisch (of extern geverifieerd) stukje functionaliteit dat het LLM via
ReAct kan aanroepen. Voorgesteld register voor v1 (zie [C.4](#sec-c4) voor de onderliggende,
al-geverifieerde API's):

| Tool | Doel | Databron (zie Deel C) |
|---|---|---|
| `get_weather_forecast(lat, lon, dagen)` | Toekomstige temperatuur/neerslag/wind, tot 16 dagen | Open-Meteo Forecast API |
| `get_weather_history(lat, lon, periode)` | Historisch weer (koude-uren-/GDD-berekening, kalibratie) | Open-Meteo Historical API + KNMI Open Data (uurwaarden) |
| `get_rain_nowcast(lat, lon)` | Neerslag komende 2 uur, 5-min-resolutie (spuit-/oogst-raam) | Buienradar `raintext`-endpoint |
| `get_soil_info(lat, lon)` | Bodemtype/vochthoudend vermogen | Bodemdata.nl / BOFEK-bodemkaart |
| `compute_chill_hours(temperatuurreeks, ras)` | Koude-uren-accumulatie t.o.v. rasbehoefte | Deterministische functie, rasdrempels uit WUR/Actua Steenfruit |
| `compute_gdd(temperatuurreeks, basistemp)` | Growing-degree-days voor ontwikkelingsstadium | Deterministische functie |
| `compute_suzukii_risk(temperatuurreeks)` | Drosophila suzukii degree-day-risicoscore | SIMKEF-achtig model (zie [C.3](#sec-c3)) |
| `check_ctgb_toelating(middel, gewas)` | Is middel X toegelaten voor kers, en bij welke dosering? | Ctgb MST Public API / dagelijkse bulk-export |
| `check_eu_bio_regels(middel_of_methode)` | Is X toegestaan binnen EU 2018/848? | EUR-Lex / ELI-link naar Reg. 2018/848 |
| `lookup_logbook(periode, onderwerp)` | Doorzoek eigen historische logboeken | Episodisch RAG-geheugen (eigen data) |
| `lookup_knowledge(vraag)` | Doorzoek WUR/Actua Steenfruit/USDA-kennisbank | RAG+KG+PG (Track 1) |

<a id="sec-b6"></a>
## B.6 Procedure-/beslissingsregister per teeltfase (shield + mandatory duties)

Directe mirror van Captain's `ProcedureEntry`/`PROCEDURE_LIBRARY`-patroon
(`captain_agent_spec.py`): elke fenologische fase (zie [A.4](#sec-a4)) krijgt een entry met
(a) verplichte acties ("mandatory duties", bijv. "log elke bespuiting met middel+dosering+tijdstip —
wettelijk spuitregister-verplicht"), en (b) een harde grens ("shield", bijv. "nooit spuiten binnen de
wettelijke pre-harvest interval" of "nooit een voor bijen schadelijk middel toepassen tijdens
bloei"). Dit register is de orchard-equivalent van Captain's `PROCEDURE_LIBRARY` en wordt — net als
daar — in een apart, puur-Python, geen-LLM-nodig bestand ondergebracht zodra implementatie start.

<a id="sec-b7"></a>
## B.7 Model & training (Qwen3-8B, SFT → DPO → Reflection)

> **Afwijking van het oorspronkelijke ontwerp (2026-10-08, vóór implementatie)**: hieronder stond
> aanvankelijk Mistral als basismodel genoemd ("open-weights, zoals gevraagd"). Bij de daadwerkelijke
> keuze (zie [G.4](#sec-g4)) bleek de cloud-GPU-pod maar 24 GB VRAM te hebben — ruim voldoende voor
> **Qwen3-8B in 4-bit NF4-kwantisatie** (~6 GB), maar krapper voor een vergelijkbaar Mistral-model
> naast de rest van de stack. Omdat Auto Pilot's eigen Chief Engineer/Captain-domeinen al een volledig
> uitgewerkte, beproefde Qwen3-8B-laadroutine hebben (`core/qwen_loader.py`,
> `cloud/qwen_inference_server.py`), is in overleg met de gebruiker gekozen om die route direct te
> hergebruiken (zelfde "nooit een tweede keer het wiel uitvinden"-regel als de rest van dit project)
> in plaats van een nieuwe Mistral-laadroutine te bouwen. De rest van deze sectie (SFT → DPO →
> Reflection-aanpak) blijft ongewijzigd van toepassing, nu met Qwen3-8B in plaats van Mistral.

- **Basismodel**: **Qwen3-8B** (open-weights, 4-bit NF4-kwantisatie, ~6 GB VRAM), rechtstreeks
  overgenomen van Auto Pilot se eigen `core/qwen_loader.py`/`cloud/qwen_inference_server.py` — zie
  boven voor de reden waarom dit Mistral verving. **Update 2026-10-09** ([G.21](#sec-g21)): dit
  geldt nog onveranderd voor de TRAININGSROUTE (`core/qwen_loader.py`, ongewijzigd, nodig voor
  QLoRA's geheugenbesparing tijdens backward-passes) — de INFERENCE-server zelf is gemigreerd naar
  vLLM met AWQ 4-bit-kwantisatie (snelheid/streaming), een apart stuk code
  (`cloud/qwen_inference_server.py`, nu vLLM-gebaseerd) dat de trainingsroute niet raakt.
- **Trainingsketen** (hergebruik van Auto Pilot's `train_sft.py`/`train_dpo.py`/`train_reflection.py`-
  patroon, geparametriseerd met `AUTOPILOT_DOMAIN=Orchard`-achtig mechanisme):
  1. **SFT**: instructie→antwoord-paren uit Track 1 (vakkennis) én Track 2 (logboek-afgeleide
     dialogen) — leert terminologie, toon, en structuur van een "expert agronomist"-persona.
  2. **DPO**: voorkeursparen waarbij biologisch/duurzaam/compliant advies wordt verkozen boven
     chemisch-zwaar/niet-compliant advies bij gelijke effectiviteit — rechtstreeks de RLHF-casus uit
     het masterproject-document.
  3. **Reflection**: zelfcorrectie-training (self-refine-stijl, Madaan et al. 2024) op
     bijna-foute adviezen (bijv. een voorstel dat een net-niet-toegelaten dosering noemt) — leert het
     model zijn eigen voorstel te toetsen vóór het gepresenteerd wordt.
- **Reranker**: apart klein cross-encoder-model, gefinetuned op [vraag]+[beste-antwoord]-paren
  gemined uit de logboeken — aparte trainingsloop, zoals het masterproject-document voorschrijft.
- **Lokaal vs. cloud**: zelfde regel als Auto Pilot — **nooit** echte training lokaal starten; lokaal
  alleen data-pijplijn (chunking, RAG/KG/PG-opbouw, OCR van logboeken, dataset-builders,
  dry-run-verificatie van data-loaders). Echte QLoRA-training/merge/kwantisatie draait op een
  cloud-GPU, zelfde als Auto Pilot's LeafCloud-pod-opzet.

<a id="sec-b8"></a>
## B.8 Lokaal vs. cloud, `AgentPaths`-conventie, folderstructuur

Hergebruik van Auto Pilot's `core/paths.py`-conventie: zodra implementatie start, wordt een
`AgentPaths(domain="Orchard", source_dirname="OrchardKnowledge")`-instantie de enige plek waar paden
worden gedefinieerd — nooit hardcoded paden in losse scripts. Zie [Deel D](#deel-d) voor de concrete
mapstructuur die dit oplevert.

Python-omgeving: **`.venv` met Python 3.13.16** staat in de projectroot
(`C:\Users\jcsch\Documents\Python\Orchard\.venv`), analoog aan Auto Pilot se eigen
project-lokale `.venv`-conventie — zelfde Python-versie ook op de cloud-pod (via `uv`, zie
[G.1](#sec-g1)). Inmiddels geïnstalleerd: `streamlit`, `pandas`, `plotly`, `pytest`, `pdfplumber`,
`beautifulsoup4`, `lxml`, `sentence-transformers` (lokaal, CPU-only — voor RAG/rerank-embeddings),
en op de cloud-pod aanvullend de volledige ML-stack (`torch` cu128, `transformers`, `peft`, `trl`,
`bitsandbytes`, ...) voor Qwen3-8B.

<a id="sec-b9"></a>
## B.9 Streamlit-UI (mirror van Engine Room / Captain Mission dashboards)

Oorspronkelijk voorgestelde pagina's, in dezelfde stijl als `Basic Simulator/app/pages/1_Captain_Mission.py`
en `2_Engine_Room.py` — **inmiddels alle 11 daadwerkelijk gebouwd** (geen emoji in bestandsnamen/labels
meer, zie [G.2](#sec-g2)/[G.10](#sec-g10) voor de reden; de emoji in onderstaande tabel zijn alleen ter
illustratie van het oorspronkelijke ontwerp-idee). Exacte huidige bestandsnamen staan in
[Deel D](#deel-d):

| Pagina | Doel | Mirror van |
|---|---|---|
| **🍒 Boomgaard Dashboard** | Actuele fenologische status, koude-uren-/GDD-teller, komende verplichte acties, open waarschuwingen, + weer-van-afgelopen-periode (aanpasbaar, onderaan) | `2_Engine_Room.py` (conditie-annunciator-paneel) |
| **💬 Vraag de Adviseur** | Chatinterface: deterministische tool-routing eerst, daarna Qwen3-8B met RAG+reranking+ReACT-tool-calling+zichtbare CoT ([G.6](#sec-g6)) | VHF/Chief Engineer chatbot-interfaces |
| **📅 Seizoensplanning** | Fase-overzicht + brown-envelope-eventlog (vorst, hagel, plaagpiek) over het lopende seizoen | `1_Captain_Mission.py` (Mission Briefing/Log) |
| **📖 Logboek & Geschiedenis** | Doorzoekbaar overzicht van 2013–2026 + weer-context-popup per entry | nieuw (geen directe mirror — Orchard-specifiek) |
| **⚠️ Waarschuwingen** | Actieve/voorbije alerts (vorst tijdens bloei, regen vóór oogst, kersenvlieg-drempel) | Captain's "brown envelope" monitors |
| **📈 Patroonherkenning** (toegevoegd 2026-10-09) | Drie lagen: (1) seizoenswaarschuwingen (wijkt het gekozen seizoen tot nu toe af van voorgaande jaren qua weer/plaagdruk/bestuivingsweer?), (2) preventieve weer-naar-ziekte-signalen (lijkt het weer van de laatste dagen op wat vroeger een uitbraak voorafging?), (3) automatisch gerangschikte meerjaren-trendpatronen + een altijd-getoonde teeltkalender — alles met doorklik naar de onderliggende logboekregels. Logica in `pipeline/orchard_patterns.py` + `pipeline/orchard_season_watch.py` + `pipeline/orchard_disease_weather_links.py` (alle drie puur, los getest), UI in `app/pages/7_Patroonherkenning.py` | nieuw (geen directe mirror — Orchard-specifiek; vergelijkbaar in geest met Chief Engineer's `KNOWN_LIMITS`/anomaliedetectie, maar dan over het eigen episodische logboek i.p.v. vaste technische drempels) |
| **📚 Bibliotheek** (toegevoegd 2026-10-08) | Overzicht van en toegang tot de Track 1-kennisbank (download + inline PDF-voorbeeld per document), gevoed door `manifest.json` | nieuw — vergelijkbaar met hoe Chief Engineer's manual-bibliotheek wordt ontsloten, maar dan als eigen pagina i.p.v. alleen RAG-achtergrond |
| **🧪 Gebruik van Middelen** (toegevoegd 2026-10-09) | Telt alle toegepaste middelen op (gecanonicaliseerd + gecategoriseerd: gewasbescherming schimmel/bacterie, insect/mijt, onkruid; meststof/bladvoeding; hulpstof; bestuiving; eerlijk "overig" waar onzeker), per week/maand/kwartaal/jaar, met drill-down per product. Logica in `pipeline/orchard_middelen.py` | nieuw — directe invulling van het wettelijke "spuitregister"-idee uit [B.6](#sec-b6), nu met een bruikbaar overzicht in plaats van alleen ruwe logboekregels |
| **❓ Help** (toegevoegd 2026-10-09) | Gebruikersgerichte documentatie (geen techniek): wat elke pagina doet, hoe je 'm gebruikt, veelgestelde vragen | nieuw — Auto Pilot heeft dit niet apart; hier toegevoegd omdat de eindgebruiker (teler) geen ontwikkelaar is |
| **⚙️ Instellingen** (toegevoegd 2026-10-09) | Locatie (adres zoeken + onthouden), ras, en huidige fenologische fase — voorheen op élke pagina bovenaan de zijbalk, nu hier gecentraliseerd zodat de zijbalk overal leeg/compact is (zie [G.15](#sec-g15)) | nieuw — Auto Pilot heeft geen vergelijkbare pagina (minder per-sessie-configuratie nodig) |

<a id="sec-b10"></a>
## B.10 Evaluatieplan

Hergebruik van het masterproject-document se eigen evaluatieplan, geconcretiseerd:

- **Extractiekwaliteit**: step-boundary F1, actie/argument-accuraatheid op een door een agronoom
  gecontroleerde steekproef van Observation-Action-Consequence-triples uit de logboeken.
- **Taakslagingspercentage**: haalt de agent een macro-doel ("stel een compliant, biologisch
  pre-oogst beschermingsplan op")?
- **Compliance-schendingen**: frequentie van "rode-lijn"-overtredingen (niet-toegelaten middel,
  overdosering, spuiten tijdens te harde wind) — kritieke metric, moet richting 0.
- **Efficiëntie**: aantal onnodige tool-calls / redundante redeneerstappen.
- **Ablaties**: RAG vs. geen RAG; outcome-only SFT vs. DPO-op-volledige-redeneerketen; verschillende
  JSON/graaf-representaties van de EU-regelgeving.
- **Gouden eval-sets**: apart gehouden, nooit gebruikt voor training (zie [B.3](#sec-b3)).

<a id="sec-b11"></a>
## B.11 Guardrails (technisch)

- **Harde tool-verificatieplicht**: een advies dat een middelnaam + dosering bevat mag nooit getoond
  worden zonder een succesvolle `check_ctgb_toelating()`-call in dezelfde beurt (analoog aan Captain's
  "never exceed the Chief-Engineer-declared safe speed"-shield). **Sinds 2026-10-10 bestaat die call echt** (open Ctgb-API, zie [G.31](#sec-g31)):
  de doseringen komen letterlijk als kaart van de API naar de gebruiker en passeren het taalmodel niet.
  - Als dit niet mogelijk is of de tool geeft een onzekere/oude status terug: de agent moet dit expliciet melden, niet negeren.
- **Bestuiver-shield**: tijdens de bloeifase wordt elk voorstel automatisch getoetst tegen een
  bijenveiligheids-vlag.
- **Organic/EU-bio-shield**: indien de teler/het bedrijf voor (delen van) de teelt bio-certificering
  nastreeft, wordt elk voorstel getoetst aan EU 2018/848.
- **Bronvermelding verplicht**: elk advies toont minimaal één citatie (document + datum/versie) —
  zelfde discipline als Chief Engineer's `source_citation`-veld, met expliciet onderscheid tussen
  "real, extracted"-feiten en "illustrative"-aannames (nooit stilzwijgend als harde feit presenteren).
- **Disclaimer**: elk advies draagt een disclaimer-regel in de stijl van StonefruitConsult se eigen
  disclaimer (zie [A.9](#sec-a9)).

---

<a id="deel-c"></a>
# Deel C — Data-inventarisatie

<a id="sec-c1"></a>
## C.1 Reeds aanwezig (eigen data)

| Bron | Locatie | Status |
|---|---|---|
| Handgeschreven logboeken 2013–2026 (14 seizoenen) | `Data/Data Log Books/jaar 2013.pdf` … `jaar 2026.pdf` | **OPGELOST (2026-10-08).** 91 pagina's zijn visueel getranscribeerd (multimodaal, niet klassieke OCR — exact zoals het masterproject-document voorspelde) en geladen in een genormaliseerde SQLite-database: `Data/Orchard/OrchardLogbooks/orchard_logbook.db` (tabellen `pages`/`entries`/`toepassingen`). Resultaat: 487 ingrepen, 1063 middel+dosering-toepassingen, periode 2013-05-08 t/m 2025-11-07, 163 entries (33%) expliciet gemarkeerd `onzeker=true` waar het handschrift niet met zekerheid leesbaar was (nooit stilzwijgend gegokt). Bouwscript: `pipeline/ingest/build_logbook_database.py`; ruwe transcripties in `Data/Orchard/OrchardLogbooks/_transcripts/*.json`. Al gekoppeld aan de Streamlit **📖 Logboek**-pagina (doorzoekbaar op jaar/middel/zekerheid). |
| Overzicht gewasbeschermingslogboek 2013–2025 + 2021–2025 | `Data/Data Log Books/*.msg` (Outlook-berichten) | Aanwezig, nog niet uitgelezen (vereist e-mail-parsing, niet PDF-parsing) |
| Actua Steenfruit vakbladartikelen (StonefruitConsult/Delphy/Caf/Fruitconsult, Wageningen) | `Data/Data Log Books/Actua steenfruit #6 en #7 2026.pdf` | Aanwezig, tekst succesvol geëxtraheerd; zeer bruikbaar als "levend" vakkennis-voorbeeld (koude-uren, snoei-technieken, bespuitingstiming, bestuiving) |
| Masterproject-briefing | `Docs/Training an Orchard Agentic Chatbot...pdf` | Gelezen, dit ontwerp volgt de scope direct |
| World Bank AI-in-landbouw rapport | `Docs/Harnessing Artificial Intelligence for Agricultural Transformation...pdf` | Gelezen (voor bredere motivatie/context; geen kersen-specifieke data) |
| **Track 1-kennisbank (Fase 2+4+5, zie [G.5](#sec-g5)/[G.16](#sec-g16)/[G.18](#sec-g18))** | `Data/Orchard/OrchardKnowledge/<categorie>/*.pdf`/`.html`/`.md` + `manifest.json` | **22 documenten acquired, 3 bewust geblokkeerd-en-gedocumenteerd, 0 failed.** Fase 2: WUR `wur_teelthandleidingen_139993.pdf`, `wur_onderstammenproef_zoete_kers_297528.pdf`; USDA `usda_agriculture_handbook_442_sweet_cherries_1973.pdf` (1973, Engelstalig); `netafim_kersen_buiten_adviesrapport_2021.pdf` (commercieel); `osu_em9267_spotted_wing_drosophila.pdf` (Engelstalig); `biofruitnet_zoete_kers_onderstammen_nl.pdf`. Fase 4 ([G.16](#sec-g16), 2026-10-09): 14 extra Nederlandstalige praktijkbronnen gericht op de 10 meest voorkomende kersenteelt-problemen (Monilia, bacteriekanker/hagelschot, kersenvlieg, zwarte kersenluis, bladvlekkenziekte, vogelschade, vorstberegening, bestuiving/rassenkeuze) — 2 extra BIOFRUITNET-factsheets + 12 HTML-bronnen (WUR/EU-niveau waar mogelijk, anders commerciële/teler-praktijkbronnen, expliciet zo gelabeld). Fase 5 ([G.18](#sec-g18), 2026-10-09): `kersenteelt_100_problemen_jaar_internet_crawl.md` — door de gebruiker zelf samengesteld, 200 genummerde praktijkproblemen met per-probleem bronvermelding, eerste `.md`-brontype in de kennisbank. Geblokkeerd: Ctgb-bulk-export (dode URL), Actua Steenfruit-archief (inlogmuur), pre-1930 USDA-bulletin (geen werkende link), pcfruit.be kennisdatabank (inlogmuur/leeg zonder lidmaatschap, zie [G.16](#sec-g16)). **Bekend, nog open issue**: de eerst-gedownloade EU 2018/848-pagina bleek per ongeluk Engelstalig (zie [Deel F](#deel-f) punt 8) en is expliciet uitgesloten van de RAG-index. |


<a id="sec-c2"></a>
## C.2 Nederlandse / Wageningen-bronnen (open data)

| Bron | Wat | Link |
|---|---|---|
| **Groen Kennisnet** (WUR + partners) | Grootste Nederlandstalige open kennisbank landbouw/tuinbouw; bevat o.a. het kennisdossier **"Fruit 4.0: Precisiefruitteelt van onderzoek naar praktijk"** | groenkennisnet.nl |
| **WUR Research Portal / edepot.wur.nl** | Open-access onderzoeksrapporten, o.a. internationale onderstammenproeven zoete kers (groei, productie, vruchtgrootte, barstgevoeligheid) | research.wur.nl, edepot.wur.nl |
| **StonefruitConsult** (Delphy/Caf/Fruitconsult, Agro Business Park Wageningen) | Periodieke "Actua Steenfruit"-nieuwsbrieven met actueel, gedateerd teeltadvies — al in bezit, maar vermoedelijk ook als doorlopend archief te benaderen/te abonneren | caf.nl / delphy.nl / fruitconsult.com |
| **Ctgb** (College voor de toelating van gewasbeschermingsmiddelen en biociden) | Officiële NL-toelatingendatabank — zie [C.4](#sec-c4) voor de API |
| **Bodemdata.nl / BOFEK-bodemkaart** | Bodemtype/bodemfysische eigenschappen per locatie | zie [C.4](#sec-c4) |
| **KNMI Data Platform** | Officiële meteorologische waarnemingen (historisch, hoge betrouwbaarheid voor kalibratie) | zie [C.4](#sec-c4) |

<a id="sec-c3"></a>
## C.3 Internationale bronnen (USDA en anderen)

| Bron | Wat | Link / vindplaats |
|---|---|---|
| **USDA National Agricultural Library (NAL) Digital Collections** | Historische (pre-1930) landbouwhandboeken, plaagwaarnemingen, pre-pesticide-methodes — "vergeten kennis" die relevant is voor biologische omschakeling (expliciet genoemd in het masterproject-document) | nal.usda.gov |
| **Core Historical Literature of Agriculture (CHLA), Cornell University** | Gedigitaliseerde landbouwteksten 19e–midden-20e eeuw, inclusief pomologie (fruitteelt) | chla.library.cornell.edu |
| **USA National Phenology Network** | Modellen/kaarten voor fenologie (bloei, koude-uren-achtige modellen) — bruikbaar als methodologisch voorbeeld naast de WUR/Actua Steenfruit-regels | usanpn.org/data/maps |
| **SIMKEF-model (Duitsland, gevalideerd EU-breed)** | Degree-day decision-support-model voor *Drosophila suzukii* (kersenvlieg) — voorspelt dagelijkse infestatiekans o.b.v. uurtemperatuur; validatie toonde 54–75% nauwkeurigheid afhankelijk van gewas (kers ca. 54%, ruimte voor verbetering met extra variabelen) | zie publicatie via ScienceDirect/Crop Protection (2024), "SIMKEF – a decision support system to predict the infestation..." |
| **Organic Eprints** | Internationaal open-access archief biologische landbouw-onderzoek | orgprints.org |
| **EUR-Lex** | EU-wetgevingsdatabank, incl. Reg. (EU) 2018/848 (biologische productie) — machine-leesbaar via ELI-link | eur-lex.europa.eu, ELI: `data.europa.eu/eli/reg/2018/848/oj` |

<a id="sec-c4"></a>
## C.4 Tool-APIs: weer, neerslag, bodem (geverifieerd, direct bruikbaar — dit beantwoordt expliciet de wens om zowel verleden als toekomst weer + neerslag via API te kunnen bevragen)

**Implementatiestatus (2026-10-09)**: Open-Meteo Forecast + Historical zijn **volledig geïmplementeerd
en live** (`pipeline/orchard_tools.py`: `get_weather_forecast`, `get_weather_history`,
`get_weather_history_detailed`, `get_weather_window`) en worden door vrijwel elke pagina en elke
detector in dit project gebruikt. Buienradar-nowcast is **geïmplementeerd** (`get_rain_nowcast`).
KNMI Open Data en Bodemdata.nl/BOFEK zijn **nog NIET aangesloten** — `get_soil_info()` blijft een
expliciete `NotImplementedError`-stub (nooit een verzonnen bodemwaarde, zie [B.1](#sec-b1)/[B.11](#sec-b11)).
Eén belangrijke, pas tijdens implementatie ontdekte quirk: **Open-Meteo's Archive-API heeft nog geen
data voor "vandaag" zelf** (pas vanaf gisteren beschikbaar) — zie `latest_available_archive_date()`
in [G.12](#sec-g12).

| API | Dekking | Sleutel nodig? | Gebruik in dit ontwerp |
|---|---|---|---|
| **Open-Meteo Forecast API** (`api.open-meteo.com/v1/forecast`) | Toekomst, tot 16 dagen vooruit; uur- en dagwaarden incl. `precipitation`/`precipitation_sum`, temperatuur, wind | Nee (gratis, tot 10.000 calls/dag niet-commercieel) | **Primaire bron voor `get_weather_forecast`** — vorstwaarschuwing, oogst-/spuitplanning vooruit |
| **Open-Meteo Historical Weather API** (`archive-api.open-meteo.com/v1/archive`) | Verleden, terug tot 1940, uur-/dagwaarden | Nee | **Primaire bron voor `get_weather_history`/`get_weather_history_detailed`** — koude-uren/GDD-berekening, kalibratie tegen logboekjaren 2013–2026, seizoensvergelijking, weer-naar-ziekte-profielen |
| **KNMI Open Data Platform / EDR API** (`developer.dataplatform.knmi.nl`) | Officiële NL-weerstation-waarnemingen (historisch, hoge resolutie) | API-key (gratis aan te vragen) | **Nog niet geïmplementeerd.** Secundaire/autoritatieve bron voor NL-specifieke historische kalibratie (nauwkeuriger per weerstation dan het Open-Meteo-model) |
| **Buienradar `raintext`-endpoint** (`gpsgadget.buienradar.nl/data/raintext`) | Neerslag-nowcasting, 5-min-resolutie, tot 2 uur vooruit | Nee (niet-commercieel, met bronvermelding) | **Geïmplementeerd: `get_rain_nowcast`** — hyperlokale beslissing "kan ik nu nog spuiten voor de bui?" |
| **Bodemdata.nl / BOFEK bodemkaart-API** | Bodemtype/bodemfysische kenmerken per coördinaat | Meestal geen key voor basisgebruik | **Nog niet geïmplementeerd** — `get_soil_info()` is een expliciete stub; bodem-pH/zuurgraad kan daardoor ook nog niet gesignaleerd worden in Patroonherkenning ([G.8](#sec-g8)) |

> **Aanbevolen combinatie**: Open-Meteo als primaire, consistente bron voor zowel verleden (sinds 1940)
> als toekomst (16 dagen) in één simpele, sleutelloze API — ideaal voor de koude-uren-/GDD-/
> Suzukii-risico-berekeningen die lange historische reeksen nodig hebben. KNMI erbij voor
> NL-specifieke validatie/kalibratie. Buienradar specifiek voor de kortetermijn "ga ik nu wel of niet
> het veld in"-beslissing.

<a id="sec-c5"></a>
## C.5 Juridische/regelgeving-bronnen

**Implementatiestatus (bijgewerkt 2026-10-10)**: de **Ctgb-toelatingen zijn nu wél live aangesloten** via de open Ctgb MST public API
(`public.mst.ctgb.nl`, geen abonnement of sleutel nodig; zie [G.31](#sec-g31)) — `check_ctgb_toelating()` is geen stub meer. De oude
Ctgb-bulk-export-URL hieronder blijft **dood** (DNS-fout, 2026-10-08 en 2026-10-10 bevestigd). De overige bronnen zijn niet als live tool
aangesloten. EUR-Lex is wél bevraagd voor Reg. 2018/848 ([C.1](#sec-c1)), maar leverde onbedoeld
Engelstalige tekst op (content-negotiation-probleem, zie [Deel F](#deel-f) punt 8) en is daarom nog
niet in de kennisbank opgenomen.

| Bron | Wat | Link |
|---|---|---|
| **Ctgb MST Public API** | Programmatische toegang tot toegelaten/vervallen middelen, doseringen, gewasindicaties | docs.mstpublicapi.apiary.io, open source API-spec: github.com/trivento/ctgb-mst-public-api |
| **Ctgb dagelijkse bulk-export** | Volledige Excel-export van alle toelatingen (CC-0-licentie, vrij herbruikbaar) | **DOOD (bevestigd 2026-10-08)**: ctgb.blob.core.windows.net/documents/public-authorisations-report.xls resolvet niet meer |
| **data.overheid.nl dataset "Bestrijdingsmiddelendatabank"** | Open-datacatalogus-ingang naar dezelfde Ctgb-data | data.overheid.nl (nog niet geprobeerd als alternatief) |
| **EUR-Lex / ELI** | Reg. (EU) 2018/848 (biologische productie) + overige EU-landbouwrichtlijnen, machine-leesbaar via ELI-links en (beperkt) XML/RDF | eur-lex.europa.eu — **acquired maar Engelstalig gebleken, zie boven** |

<a id="sec-c6"></a>
## C.6 Vertaalstrategie EN→NL

Conform de expliciete wens ("we moeten alles in het NL doen... als er UK data is, dan kunnen we dat
wel gebruiken, maar we moeten het eerst vertalen naar NL voor we het omzetten naar agentic data"):

1. **Brontaal behouden in metadata**: elke geïmporteerde Engelstalige bron (USDA/CHLA, USA-NPN,
   World Bank-rapport) krijgt een `original_language`- en `source_url`-veld in de JSON-structuur,
   zodat de herkomst traceerbaar blijft ook ná vertaling.
2. **Vertaling vóór chunking/embedding**: Engelstalige teksten worden eerst volledig naar het
   Nederlands vertaald (bijv. via een sterk vertaalmodel/LLM-vertaalstap met menselijke/steekproef-
   controle op vaktermen), **daarna pas** semantisch gechunkt en in de RAG-index opgenomen — zodat de
   agent intern consistent in het Nederlands redeneert en citeert.
3. **Vaktermen-consistentie**: een klein, groeiend NL-vaktermen-glossarium (bijv. "chill hours" →
   "koude-uren", "growing degree days" → "graaddagen/groei-eenheden", "spotted wing drosophila" →
   "Suzuki-fruitvlieg/kersenvlieg") wordt bijgehouden zodat vertalingen consistent blijven over alle
   bronnen heen — dit voorkomt dat dezelfde term in de kennisbank op meerdere manieren terugkomt en de
   retrieval verslechtert.
4. **Nederlandstalige bronnen krijgen voorrang** waar beschikbaar (WUR/Groen Kennisnet/Actua
   Steenfruit zijn al Nederlandstalig en vakkundig geschreven) — Engelstalige bronnen vullen vooral
   de historische (USDA/CHLA, 1850–1930) en methodologische (SIMKEF, USA-NPN) gaten op.

<a id="sec-c7"></a>
## C.7 Gat-analyse — wat ontbreekt nog

- ~~OCR/transcriptie van de 14 jaar handgeschreven logboeken~~ — **OPGELOST (2026-10-08)**, zie
  C.1. 91/91 pagina's getranscribeerd en in SQLite geladen. Openstaand vervolgwerk: (a) de 163
  `onzeker`-gemarkeerde entries steekproefsgewijs laten verifiëren door de teler zelf (menselijke
  validatie van de "gouden" transcriptie, conform het masterproject-document se eigen
  evaluatieplan §Extraction Quality); (b) de twee `.msg`-overzichtsbestanden (zie hieronder)
  gebruiken om de transcriptie te kruisvalideren.
- **De twee `.msg`-overzichtsbestanden** (samenvattingen 2013–2025 / 2021–2025) zijn nog niet
  uitgelezen — mogelijk een kant-en-klare, al-gestructureerde samenvatting die het OCR-werk voor een
  deel kan valideren/aanvullen.
- **Rasspecifieke koude-uren-/GDD-drempels**: Actua Steenfruit noemt Kordia (≈1400 u) als voorbeeld;
  een volledige tabel voor alle op het bedrijf geteelde rassen moet nog verzameld worden (WUR/Actua
  Steenfruit-archief doorzoeken op meer rassen).
  - **Actie nodig van de teler**: welke rassen staan er precies, en in welke verhouding?
- **Eigen bodemdata**: BOFEK geeft een landelijke bodemkaart-schatting; voor precisie is eigen
  grondmonster-/pH-/EC-historie van de boomgaard wenselijk (nog niet aangetroffen in de huidige
  datamap).
- **Bijenvolken-/bestuiverregistratie**: geen aparte historische data hierover aangetroffen, maar de
  logboeken zelf blijken wél incidentele bijen/hommel-kasten-notities te bevatten (bv. "2 kasten van
  Nico") — deze zijn in [G.9](#sec-g9) als eigen categorie ("bestuiving") herkend i.p.v. als middel
  meegeteld. Een systematische bestuiver-registratie (hoeveel volken, wiens kasten, wanneer geplaatst)
  ontbreekt nog steeds; nodig voor het bestuiver-shield ([B.11](#sec-b11)).
- **Oogst-/opbrengstcijfers**: het masterproject-document noemt dit expliciet als aparte categorie
  ("Harvest and Yield Records") — nog steeds niet aangetroffen in `Data/`; nodig om advies
  daadwerkelijk aan opbrengst te kunnen koppelen (de kern van "maximale opbrengst" uit de opdracht).
  Dit blijft de belangrijkste blokkerende data-leemte voor een toekomstige DPO-trainingsronde die
  daadwerkelijk op opbrengst optimaliseert in plaats van op "lijkt op wat de teler deed".
  **Wat de teler vanaf 2027 kan vastleggen om dit te dichten: zie [Deel H](#deel-h)** (oogstregistratie, bodem/blad, sensoren, vallen, camera's).
- **Ctgb-toelatingsdata**: de bulk-export-URL is dood (zie [C.5](#sec-c5)), maar de **open Ctgb MST public API** werkt wel
  en is sinds 2026-10-10 aangesloten (`check_ctgb_toelating()`, [G.31](#sec-g31)). Open: de gebruiksaanwijzing-PDF's zelf worden nog niet geparsed (alleen gelinkt).
- **Bodem-pH/zuurgraad**: nog steeds geen echte koppeling (zie [C.4](#sec-c4)) — concreet gemist bij
  de bouw van Patroonherkenning's seizoenswaarschuwingen ([G.8](#sec-g8)), waar "te zure grond" als
  voorbeeld werd genoemd maar NIET gesignaleerd kon worden; `soil_ph_status_note()` toont in de UI
  expliciet dat dit ontbreekt in plaats van iets te verzinnen.
- **Pre-1930 USDA-bulletin** (Farmers' Bulletin 776, "Growing Cherries East of the Rocky Mountains"):
  geen werkende digitale kopie gevonden deze sessie (zie [C.1](#sec-c1)); USDA Agriculture Handbook
  442 (1973) dekt vergelijkbare stof en is wel acquired.
- **Middelnaam-identiteit onzeker voor enkele producten**: bij het bouwen van Gebruik van Middelen
  ([G.9](#sec-g9)) bleven 27 van de 1026 toepassingen (2,6%) bewust ongeclassificeerd ("overig") omdat
  de identiteit van de ruwe naam niet met zekerheid kon worden vastgesteld (met name 13× "Tracor" —
  mogelijk een OCR-variant van het insecticide "Tracer", maar niet met voldoende zekerheid om dat aan
  te nemen). Zie `pipeline/orchard_middelen.py`'s `_ONZEKER_OVERIG` voor de volledige lijst.

---

<a id="deel-d"></a>
# Deel D — Mapstructuur `Data/Orchard/` (gerealiseerd)

Mirror van Auto Pilot's `AgentPaths`-conventie (zie [B.8](#sec-b8)), zoals die bij implementatie
daadwerkelijk is gerealiseerd (`core/paths.py`'s `AgentPaths.orchard()`) — dit is dus niet langer een
voorstel maar de werkelijke mapstructuur op zowel de laptop als de cloud-pod:

```
Orchard/                                    (GitHub: https://github.com/TextMiningUM/Orchard, zie [G.13](#sec-g13))
├── .github/
│   └── copilot-instructions.md            ← werkafspraken/conventies voor dit repo
├── .venv/                                  ← Python 3.13.16 (lokaal); pod heeft eigen .venv via `uv`
├── Docs/                                   (bestaand, gitignored — project-briefings blijven lokaal)
├── Images/                                 (bestaand, gitignored — herkomst onzeker, zie .gitignore)
├── Data/
│   ├── Data Log Books/                    (bestaand, GITIGNORED — eigen bedrijfsgegevens, zie G.13)
│   └── Orchard/                           ← data_root, AgentPaths.orchard()
│       ├── OrchardKnowledge/              ← source_dir: Track 1 (getrackt in git)
│       │   ├── wur_groenkennisnet/        (3 documenten, zie C.1)
│       │   ├── usda_historisch/           (1 document)
│       │   ├── eu_wetgeving/              (1 document, NOG NIET in RAG-index, zie Deel F #8)
│       │   ├── teelt_advies/              (1 document, Netafim)
│       │   ├── suzukii_swd/               (1 document, OSU)
│       │   └── manifest.json              ← provenance (url/sha256/status) voor elk document
│       ├── OrchardLogbooks/               ← GITIGNORED (eigen bedrijfsgegevens)
│       │   ├── orchard_logbook.db         ← SQLite: pages/entries/toepassingen (487/1063 rijen)
│       │   ├── _transcripts/*.json        ← ruwe visuele-transcriptie-tussenresultaten
│       │   └── _raw_page_images/          ← gerenderde scans (91 PNG's)
│       ├── Orchard_JSON/                  ← GITIGNORED, regenereerbaar: gestructureerde Track 1-documenten
│       │   (per-document JSON met chapters/sections/blocks/tables/figures/chunks + qc, zie G.23/G.24;
│       │   gemaakt door build_orchard_json.py + orchard_qc.py; _qc_report.md = laatste QC-rapport)
│       ├── Orchard_Agents_Training/       ← GITIGNORED, regenereerbaar: RAG-index (+ later KG/PG)
│       │   (orchard_rag_chunks.json, orchard_rag_embeddings.npy, orchard_rag_chunk_ids.json;
│       │   ALLEEN chunks met QC-oordeel ok/warn, zie G.24)
│       ├── Orchard_Eval/                  ← held-out gouden set (orchard_gold_qa.json, GETRACKT, zie G.22);
│       │   └── _runs/                     ← GITIGNORED: resultaten van pipeline/run_orchard_eval.py
│       └── orchard_settings.json          ← GITIGNORED: persisted lat/lon/adres (echte boomgaardlocatie)
├── _models/
│   ├── hf_cache/                          ← gedeeld, GITIGNORED
│   └── Orchard/                           ← toekomstige fine-tuned Qwen3-8B-adapters (nog leeg)
├── app/                                   ← Streamlit-app
│   ├── Home.py
│   ├── orchard_common.py                  ← gedeelde helpers: AgentPaths, sidebar, settings, weer-popup
│   └── pages/                             (volgorde 2026-10-09 herschikt naar logische groepering, zie G.20)
│       ├── 1_Boomgaard_Dashboard.py
│       ├── 2_Waarschuwingen.py
│       ├── 3_Vraag_de_Adviseur.py
│       ├── 4_Seizoensplanning.py
│       ├── 5_Logboek.py
│       ├── 6_Logboek_Verifieren.py        (op de publieke pod inmiddels geactiveerd, zie G.1/G.19)
│       ├── 7_Patroonherkenning.py
│       ├── 8_Gebruik_van_Middelen.py
│       ├── 9_Bibliotheek.py
│       ├── 10_Help.py                     ← nieuw, zie G.10
│       └── 11_Instellingen.py             ← nieuw, zie G.15 (locatie/ras/fase, uit de zijbalk gehaald)
├── core/
│   ├── paths.py                           ← AgentPaths(domain="Orchard")
│   ├── io.py, qwen_loader.py
├── pipeline/
│   ├── orchard_phenology_spec.py          ← deterministische kern (koude-uren/GDD/vorst/suzukii/barst)
│   ├── orchard_tools.py                   ← Open-Meteo/Buienradar/geocoding/Ctgb-stub/bodem-stub
│   ├── orchard_rag.py                     ← RAG-retrieval + reranking (Fase 3)
│   ├── orchard_eval.py                    ← eval-bibliotheek: hit@k/MRR, feitendekking, guardrail, latency (G.22)
│   ├── run_orchard_eval.py                ← CLI: python -m pipeline.run_orchard_eval [--answers] [--no-rerank]
│   ├── orchard_tool_catalog.py            ← ReACT-tool-catalogus voor de chatbot
│   ├── orchard_agent.py                   ← ask_orchard_advisor() (RAG+ReACT+CoT)
│   ├── orchard_patterns.py                ← meerjaren-patroonherkenning (Patroonherkenning-pagina)
│   ├── orchard_season_watch.py            ← seizoenswaarschuwingen (idem)
│   ├── orchard_disease_weather_links.py   ← preventieve weer-naar-ziekte-signalen (idem)
│   ├── orchard_middelen.py                ← canonicalisatie/categorisatie middelen (Gebruik van Middelen)
│   ├── qwen_remote.py                     ← HTTP-client naar de cloud-Qwen-server
│   └── ingest/
│       ├── build_logbook_database.py      ← Track 2: OCR-transcripten -> SQLite
│       ├── build_orchard_corpus.py        ← Track 1: downloaden + manifest.json
│       ├── build_orchard_json.py          ← Track 1: PDF/HTML/MD -> gestructureerde JSON + chunk-definitie (G.23)
│       ├── orchard_structure.py           ← pure structuurlogica: secties, chunks, tabel/figuur-scheiding (G.23)
│       ├── orchard_qc.py                  ← chunk-QC (zinnen/OCR/tabellen/paginagrenzen) + repair (G.24)
│       ├── parse_orchard_documents.py     ← VERVALLEN (vervangen door build_orchard_json.py; nog te verwijderen)
│       └── build_orchard_rag.py           ← Track 1: embedden van de QC-geslaagde JSON-chunks -> RAG-index
├── cloud/
│   └── qwen_inference_server.py           ← localhost-only Qwen3-8B-server (poort 8811) op de pod
├── tests/                                 ← 139 tests (pytest), zie G.11
├── design_cherry_orchard_advisor.md       ← dit document
├── README.md
└── requirements.txt
```

Cloud-pod (`45.135.57.59`, LeafCloud, NVIDIA A30 24GB — zie [G.1](#sec-g1)): spiegelt bovenstaande
structuur 1-op-1 onder `/home/ubuntu/Orchard`, met twee extra systemd-services
(`orchard-streamlit`, `orchard-qwen`) en een nginx-reverse-proxy + Let's Encrypt-certificaat voor
`https://45-135-57-59.sslip.io`.

---

<a id="deel-e"></a>
# Deel E — Roadmap: walking skeleton eerst

Mirror van Captain's eigen aanpak (§14 `design_captain_missions.md`, "Approach: walking skeleton
first") — niet alles tegelijk bouwen, maar in deze volgorde. **Status per 2026-10-09** toegevoegd per
stap (zie [Deel G](#deel-g) voor het volledige verhaal); de daadwerkelijke volgorde week op een paar
punten af van het oorspronkelijke plan (met name: de Streamlit-app en de deterministische kern kwamen
eerder dan Track 1-RAG, en training (stap 5/7) is nog niet gestart — eerst is een werkend,
tool-gebaseerd systeem zonder fine-tuning gebouwd, zie [G.6](#sec-g6)):

1. **Data gereedheid**: OCR van de logboeken + JSON-structurering (hoogste prioriteit, blokkeert
   Track 2 volledig). — ✅ **GEDAAN** (91/91 pagina's, zie [G.3](#sec-g3)).
2. **Deterministische kern v0**: koude-uren + GDD-berekening, gevalideerd tegen 1–2 bekende seizoenen
   uit de logboeken. — ✅ **GEDAAN** (`pipeline/orchard_phenology_spec.py`, zie [G.2](#sec-g2)).
3. **Tool-laag v0**: Open-Meteo (verleden+toekomst) + Ctgb-opzoekfunctie, zonder LLM — puur
   geverifieerde data-ophaal-functies. — ✅ **GEDAAN voor weer/neerslag/geocoding én Ctgb** (de open Ctgb-API is sinds 2026-10-10 aangesloten,
   [G.31](#sec-g31)); alleen de bodem-API (BOFEK) blijft een bewuste stub (zie [C.4](#sec-c4)).
4. **RAG v0**: alleen Track 1 (WUR/Actua Steenfruit/Ctgb), nog zonder logboeken. — ✅ **GEDAAN**
   (7 documenten, dense retrieval + reranking, zie [G.5](#sec-g5)/[G.6](#sec-g6)).
5. **Eerste Mistral-SFT**: basis vraag-antwoord-gedrag op Track 1-data. — 🟡 **EERSTE RONDE GEDAAN (2026-10-10, [G.28](#sec-g28))**: QLoRA op Qwen3-8B
   (`sft_v2`, 95 kaarten + 48 compliance-voorbeelden): held-out volledige dekking 55,6 → 86,7 %, guardrail ≥ basismodel; nog niet de standaard in productie (zie G.28 punt 5).
   Qwen3-8B draait wel al live (basismodel, geen fine-tuning), met RAG+tools+CoT als tussenstap i.p.v.
   te wachten op een trainingsronde — zie de afwijking hierboven en [G.6](#sec-g6).
6. **Track 2 erbij**: zodra OCR klaar is, logboek-RAG + conversational SFT-data toevoegen. — 🟡
   **DEELS**: de logboek-data wordt al live gebruikt door Patroonherkenning/Seizoenswaarschuwingen/
   Gebruik van Middelen ([G.7](#sec-g7)-[G.9](#sec-g9)), en sinds 2026-10-10 is het logboek ook een lokale RAG-bron voor de chatbot
   ([G.27](#sec-g27)) plus open-book SFT-data (lokaal); een conversational-SFT-dataset op echte antwoorden bestaat nog niet.
7. **DPO**: biologisch-vs-chemisch-voorkeur. — 🟡 **DATA KLAAR, RONDE NIET GEDRAAID** ([G.28](#sec-g28)): 69 on-policy paren uit rejection sampling met een
   deterministische reward; na SFT v2 zijn er geen verliezende samples meer op de validatieprompts, dus DPO wacht op een bredere promptverdeling. Ook
   een UI-mechanisme om voorkeursparen te VERZAMELEN (duim omhoog/omlaag op elk antwoord, zie
   [G.6](#sec-g6)) — de daadwerkelijke DPO-trainingsronde zelf volgt later, zodra er genoeg paren zijn.
8. **Streamlit-dashboard v0**: alleen het Boomgaard Dashboard + Chat-pagina. — ✅ **GEDAAN, en ver
   voorbij v0**: 10 pagina's totaal, zie [B.9](#sec-b9)/[G.10](#sec-g10).
9. **Evaluatie + ablaties**: pas zinvol zodra stap 1–7 staan. — 🟡 **GESTART** (2026-10-09): gouden
   eval-set van 83 vragen + meetharnas + eerste baseline staan ([G.22](#sec-g22)); de antwoord-evaluatie (`--answers`) en de
   herhaalmeting na de RAG-herbouw zijn gedaan ([G.25](#sec-g25), [G.27](#sec-g27)); nog te doen: herhaalde runs (ruis ±5 pt) en een
   nieuwe held-out set.
   139 → 240 UNIT-tests bestaan ook (zie [G.11](#sec-g11)), maar dat is iets anders dan een
   agronomische kwaliteits-evaluatie. **Stand 2026-10-10**: 114 vragen (gouden + held-out v2, n = 31 held-out), herhaalde runs, deterministische reward en
   guardrail-sets zijn gedaan ([G.28](#sec-g28)); nog te doen: een grotere held-out set (n ≥ 60), multi-turn- en tool-gesprekken, en merknaam-/multi-hop-scenario's ([Deel I](#deel-i)).
10. **Waterbalans (te droog / te nat)** — ✅ **GEDAAN** (2026-10-10, [G.29](#sec-g29)): FAO-56-emmer, 7-daagse vooruitblik, dashboard en adviseur-tool `waterbalans`.
11. **Logboek-kalender** — ✅ **GEDAAN** (2026-10-10, [G.30](#sec-g30)): "wat deed ik rond deze tijd?", dedupe van dubbel ingescande regels, adviseur-tool `logboek_kalender`.
12. **Ctgb-opzoektool + `middel_opzoeken`** — ✅ **GEDAAN** (2026-10-10, [G.31](#sec-g31)): open API, officiële voorschriftkaart, eigen gebruik + praktijkcontrole.
13. **Seizoen 2027: uitkomsten vastleggen, multi-hop-adviezen met poorten, kalibratie, daarna SFT/DPO op echte uitkomsten** — 🟦 **GEPLAND**, zie [Deel I](#deel-i)
    (en [Deel H](#deel-h) voor wat de teler vastlegt).

---

<a id="deel-f"></a>
# Deel F — Open vragen

1. Welke kersenrassen staan er precies in de boomgaard (en in welke oppervlakte-verhouding)? — nodig
   voor rasspecifieke koude-uren-/GDD-drempels.
2. Is er al een vorm van vorstbescherming aanwezig (beregening, rookpotten, windmachines) waarover het
   systeem zou moeten adviseren, of is dat nog niet geïnstalleerd?
3. Streeft het bedrijf (deels) naar officiële bio-certificering (EU 2018/848), of is "organisch waar
   mogelijk, chemisch waar nodig" het uitgangspunt? — bepaalt hoe streng het EU-bio-shield moet zijn.
4. Zijn er al bodemmonster-/pH-/EC-historie-gegevens van de boomgaard, of moet dit nog verzameld
   worden?
5. Zijn er oogst-/opbrengstcijfers per jaar beschikbaar (los van de gewasbeschermingslogboeken)?
6. Hoe actueel/compleet is het Actua Steenfruit-archief dat beschikbaar is — alleen deze twee
   nummers (#6, #7, 2026), of is er een lopend abonnement/archief met meer nummers op te halen?
7. Wil je (zoals het masterproject-document als lange-termijnvisie noemt) vanaf het begin al rekening
   houden met een later te delen "multi-telers"-platform, of expliciet single-tenant houden voor v1
   (dit ontwerp gaat voorlopig uit van single-tenant, zie [A.8](#sec-a8))?
8. **EU 2018/848 taalprobleem (ontdekt 2026-10-08, Fase 3)**: het opgeslagen HTML-bestand
   (`eu_verordening_2018_848_biologische_productie_nl.html`, gedownload via
   `.../legal-content/NL/TXT/?uri=CELEX:32018R0848`) bleek bij parsen toch **Engelstalig** te zijn
   (`<title>Verordening - 2018/848 - EN - EUR-Lex</title>`) — waarschijnlijk content-negotiation op
   basis van een ontbrekende/genegeerde `Accept-Language`-header, niet (zoals eerder vermoed) een
   RDF/ELI-metadata-probleem. Een hernieuwde poging (met expliciete `/HTML/`- en `/PDF/`-varianten en
   een `Accept-Language: nl`-header) kreeg herhaaldelijk `202 Accepted` met lege body terug van
   EUR-Lex — waarschijnlijk tijdelijke rate-limiting na een paar snelle requests. Dit bestand is
   daarom expliciet uitgesloten van de RAG-index (`pipeline/ingest/parse_orchard_documents.py`'s
   `SKIP_FROM_RAG`) totdat een echt Nederlandstalige versie is bevestigd — ofwel door het later
   opnieuw (rustiger) te proberen, ofwel door de Engelse tekst alsnog te vertalen conform het
      project's eigen "eerst vertalen naar NL, dan agentic maken"-regel (zie Sec C.6).
9. **Oogst-/opbrengstcijfers blijven de belangrijkste openstaande data-leemte** (zie ook [C.7](#sec-c7)):
   zonder deze cijfers kan geen enkel onderdeel van het systeem daadwerkelijk op "maximale opbrengst"
   geoptimaliseerd/geëvalueerd worden — alle huidige patroondetectie ([G.7](#sec-g7)-[G.9](#sec-g9))
   werkt noodgedwongen op *proxy*-signalen (behandelfrequentie, weer, timing), niet op uitkomst.
10. **Is "Tracor" (13× in het logboek) een schrijfvariant van het insecticide "Tracer"?** Bij het
    bouwen van Gebruik van Middelen ([G.9](#sec-g9)) leek dit aannemelijk maar niet zeker genoeg om
    aan te nemen — bewust in categorie "overig" gehouden. Alleen de teler zelf kan dit met zekerheid
    bevestigen.
11. **Duim-omhoog/omlaag-feedback en DPO-training** (toegevoegd 2026-10-09, zie [G.6](#sec-g6)): de
    chatbot verzamelt nu voorkeursparen, maar er is nog geen besluit over (a) hoeveel paren nodig zijn
    vóór een eerste DPO-trainingsronde zinvol is, en (b) of een duim-omlaag zonder toelichting genoeg
    signaal geeft, of dat de teler ook een korte reden zou moeten kunnen opgeven.
12. **Hallucinatiedetectie is een heuristiek, geen garantie** (zie [G.6](#sec-g6)): de huidige
    rood/groen-indicatie herkent OF een antwoord zich baseert op aangeleverde RAG-fragmenten/
    tool-resultaten, niet OF de inhoud daadwerkelijk feitelijk correct is. Een antwoord kan "groen"
    zijn (goed gegrond) en toch een verkeerde conclusie trekken uit de aangeleverde data, of "rood"
    zijn voor een onschuldige, algemene uitspraak die geen grounding nodig had. Dit moet in de UI
    duidelijk blijven (geen vals gevoel van zekerheid).
13. **PDF-tekstextractie moet per document steekproefsgewijs gelezen worden, niet alleen
    "lukte het parsen"-gecontroleerd** (ontdekt 2026-10-09 door de gebruiker, bij het Netafim-
    adviesrapport): een pagina met een lopende tekstkolom naast een productsidebar kan door
    `pdfplumber`'s standaard `extract_text()` door elkaar gehusseld worden tot onzinnige, semantisch
    kapotte tekst (zinnen die halverwege afbreken in een productnaam uit de andere kolom). Dit is
    een REQUIREMENT geworden (zie ook `.github/copilot-instructions.md`): elk nieuw/bestaand
    Track 1-document moet steekproefsgewijs handmatig gelezen worden in de geparste JSON-vorm
    (`Data/Orchard/Orchard_JSON/`) vóór het vertrouwd wordt in de RAG-index — status "N pagina's
    geparsed" alleen zegt niets over leesbaarheid. **OPGELOST, zie [G.17](#sec-g17)** —
    overgestapt op PyMuPDF (zelfde fix als Auto Pilot al had, zie hieronder).
14. **Observation-Action-Consequence(-Why/Worst-case)-tuples nog niet geëxtraheerd**
    (voorgesteld door de gebruiker, 2026-10-09): zowel het logboek (Track 2) als de inmiddels
    uitgebreide literatuur (Track 1, zie [G.16](#sec-g16)) bevatten impliciet dit patroon, maar
    het is nergens expliciet gestructureerd. **Logboek**: een ingreep-regel (observatie + actie)
    moet gekoppeld worden aan het GEVOLG — meestal af te leiden uit latere regels in dezelfde
    categorie (kwam het probleem terug = mislukte timing/middel, of bleef het weg = succes).
    **Literatuur**: bronnen bevatten vaak expliciete "doe dit niet, want..."-waarschuwingen (bv.
    "verwijder Monilia-vruchtmummies, nooit op de composthoop" — het worst-case-scenario staat er
    letterlijk bij). Beide zijn een los extractiescript-project, bedoeld als structureel invoer
    voor een toekomstige SFT/DPO-trainingsronde (zie [Deel E](#deel-e) stap 5-7). **DEELS GEDAAN (2026-10-10, [G.27](#sec-g27))**:
    voor de 200 kaarten van de probleembank (die de OAC-structuur al hebben) is het een deterministische parse (200/200; 198 met ≥ 2 stappen);
    voor prozachunks en logboek nog niet (logboek kent geen uitkomsten).
15. **Procedurele grafen (meerstaps-workflows) nog niet afgeleid** — Auto Pilot heeft hier al
    een werkend, direct overdraagbaar patroon voor (`../Auto Pilot/pipeline/ingest/build_pg.py`,
    "Procedural Graph over de reasoning traces", Lu et al. 2026-stijl): een volledig
    deterministische (geen LLM) graaf van `(stap, NEXT, stap)`-triples, gemined uit geordende
    `procedures`-lijsten, met drie edge-attributen — `condition` (wanneer geldt deze overgang),
    `guidance` (hoe/waarom de volgende stap te nemen) en `pitfalls` (wat te vermijden, exact het
    "wat was het slechtste om te doen"-idee uit punt 14 hierboven). Stap-acties worden over
    meerdere bronnen heen gecanonicaliseerd via embedding-gelijkenis (greedy clustering), en
    identieke overgangen uit meerdere documenten/logboekregels smelten samen met een
    support-telling (hoe vaker eenzelfde volgorde bevestigd wordt, hoe zwaarder die telt). Voor
    Orchard zou een ingreep (bv. "Monilia bestrijden": snoei zieke delen → gereedschap
    ontsmetten → mummies verwijderen+afvoeren → fungicide bij juiste BBCH-stadium → herhalen bij
    aanhoudend nat weer) zo'n procedure-reeks worden, gemined uit zowel de literatuur (nu
    uitgebreid, zie [G.16](#sec-g16)) als het logboek.     **GEBOUWD voor de kaarten (2026-10-10, [G.27](#sec-g27))**: `orchard_pg.py` + `build_orchard_pg.py` (611 nodes, 435 edges, maar
    slechts 1 edge met support > 1 -- elke kaart is een eigen procedure); nog niet in de agent geschakeld, wacht op prozatraces en
    logboek-procedures voor meer-bron-support.
16. **Kennisgraaf (Knowledge Graph) voor complexe, onderling verbonden elementen nog niet
    gebouwd** — ook hiervoor heeft Auto Pilot al een werkend patroon
    (`../Auto Pilot/pipeline/ingest/build_kg.py`, "Tutorial 13 § 8"): GEEN klassieke
    subject-predicate-object-triplestore, maar een inverted-index-achtige graaf bovenop de
    bestaande RAG-chunks — concept→chunk_ids, concept↔concept co-occurrence (gewogen),
    topic→chunk_ids, document→chunk_ids, chunk↔chunk-adjacentie binnen een hoofdstuk/sectie, en
    een alias→concept-woordenboek voor query-normalisatie (bv. "dsc alert" → `["DSC",
    "Channel 70"]` bij Auto Pilot; voor Orchard zou dat bv. "kersenvlieg" → `["Rhagoletis
    cerasi"]` of "hagelschot" → `["Stigmina carpophila", "Pseudomonas syringae"]` worden).
    Ondersteunt hybride retrieval (dense embeddings + graaf-expansie) — met een smoke-test die
    specifiek de queries print waar dense-only retrieval op vastliep (zelfde diagnostische
    aanpak als [G.16](#sec-g16) hierboven al informeel deed). Voor Orchard zou dit de nu
    verspreide relaties (weer → ziekte/plaag → product/dosering/timing → rasgevoeligheid →
    seizoensfase) in één doorzoekbare structuur kunnen samenbrengen i.p.v. losse Python-functies
    (`orchard_disease_weather_links.py`, `orchard_middelen.py`, `orchard_phenology_spec.py`).
    **GEBOUWD (2026-10-10, [G.27](#sec-g27))**: `orchard_kg.py` + `orchard_concepts.py` (70 concepten, hybride retrieval: hit@6 95% → 100%
    op de gouden set, deels in-sample; neutraal op de onafhankelijke set).
17. **Reward-functie voor toekomstige optimalisatie (bv. RL/DPO-achtige training) nog niet
    ontworpen**: er is nu een eenvoudig voorkeurssignaal (duim omhoog/omlaag, zie [G.14](#sec-g14))
    maar geen geëxpliciteerde reward-functie die meerdere doelen afweegt (bv. feitelijke
    juistheid/grounding, veiligheid rond doseringen, bruikbaarheid/beknoptheid, en op termijn
    mogelijk ECHTE opbrengst-/oogstuitkomsten). Zonder zo'n expliciet ontwerp blijft optimalisatie
    beperkt tot losse DPO-voorkeursparen zonder een gewogen, samengesteld doel. **ONTWORPEN (2026-10-10, [G.28](#sec-g28))**: `pipeline/orchard_reward.py`, deterministisch, met
    compliance-poort; nog zonder extern opbrengstsignaal.
18. **RAG-chunking is nu nog een simpele, per-pagina woordenteller-pack — Auto Pilot's eigen
    `pipeline/ingest/build_rag.py` doet dit merkbaar slimmer** en is een directe kandidaat om
    over te nemen: (a) secties worden daar PER DOCUMENT (niet per pagina) opgebouwd, zodat een
    alinea die een paginagrens overschrijdt niet kunstmatig wordt afgekapt — Orchard chunkt nu
    nog strikt binnen één `page["text"]` tegelijk; (b) een sectie wordt pas gesplitst na een
    embedding-based topic-boundary-detectie (Hearst 1997 TextTiling-depth-score op
    zinsembeddings, adaptieve percentiel-drempel per sectie), niet blind op een vast
    woordenaantal; (c) kleine, verwante buursecties worden intelligent SAMENgevoegd tot het
    token-budget, geblokkeerd door een adaptieve ondergrens op de boundary-embedding-gelijkenis
    (voorkomt dat twee toevallig gelijk-gelabelde maar inhoudelijk ongerelateerde stukken
    samensmelten); (d) bepaalde type's (`rule`, `definition`, `procedure`, ...) zijn altijd
    precies ÉÉN chunk, nooit gesplitst of samengevoegd; (e) een losse filter verwijdert
    "degenerate" chunks (minder dan 2 alfabetische woorden — paginanummers, kale opsommingstekens)
    vóórdat ze de RAG-index bereiken. **OPGELOST, zie [G.18](#sec-g18)** — volledig overgenomen
    van Auto Pilot (niet opnieuw ontworpen), inclusief een nieuw `"probleem"`-STANDALONE-type
    voor genummerde kennisitems. **Bleek daarna nog steeds te simpel** (PDF = nog steeds één sectie
    per pagina, HTML = één sectie voor de héle pagina, geen kop-/tabel-/figuurdetectie, token-budget-
    samenvoegen = quasi-vaste lengte): tweede ronde, zie [G.23](#sec-g23) (structuur-JSON zoals
    Auto Pilot's OOW/VHF-parsers) en [G.24](#sec-g24) (QC-poort).
20. **Kapotte chunks repareren (backlog, bewust uitgesteld).** De QC ([G.24](#sec-g24)) keurt chunks af
    die geen complete zinnen bevatten (afgebroken zinnen, tabellen/figuurtekst, OCR-ruis,
    pagina-/kolomresten, bibliografie). Die blijven in de JSON staan (met reden + `text_raw`) maar
    gaan NIET naar RAG/KG/PG. Het meeste verlies zit in de gescande USDA-handbook (OCR-boek, 2
    kolommen) en de WUR-/BIOFRUITNET-tabellen. Toekomstig werk: parser per document verbeteren
    (tabellen als gestructureerde `tables` met eigen opzoek-tool, kolomvolgorde, voorzichtige
    OCR-correctie met audit-spoor), QC opnieuw draaien — wat dan slaagt doet vanzelf mee.
21. **Embedder kapt af op 128 tokens — OPGELOST, zie [G.25](#sec-g25).** `paraphrase-multilingual-mpnet-base-v2`
    heeft `max_seq_length=128`; in de oude index waren 506 van de 644 chunks langer. Vervangen door
    `BAAI/bge-m3` (meertalig, 512 tokens in gebruik): hit@6 95% / MRR 0,92 zonder reranker (was 87% /
    0,81 mét reranker).
19. **Het logboek zelf (Track 2) is nog GEEN RAG-bron voor de Adviseur** (gedeeltelijk al
    gesignaleerd in [Deel E](#deel-e) stap 6, hier expliciet herhaald en aangescherpt op verzoek
    van de gebruiker): **de 14 jaar (2013–2026) aan eigen, handgeschreven logboekregels zijn een
    goudmijn** — twaalf-plus seizoenen van exact welke ingreep wanneer, bij welk weer, met welk
    resultaat, op DEZE specifieke boomgaard, met DEZE rassen en DEZE bodem. Dat is precies het
    soort gedetailleerde, lokale ervaringskennis die geen enkele externe WUR-/PCFruit-/Bayer-
    bron ooit kan evenaren, en die daarom NIET als bijzaak behandeld mag worden naast Track 1 —
    de logboekregels moeten een eigen, volwaardige RAG-bron worden. Nu wordt deze data wel al
    gebruikt door Patroonherkenning/Seizoenswaarschuwingen/Gebruik van Middelen
    ([G.7](#sec-g7)-[G.9](#sec-g9)) — stuk voor stuk eigen, deterministische analysefuncties —
    maar "Vraag de Adviseur" kan er nog NIET zelf in zoeken/uit citeren. De teler moet dus kunnen
    leren van zijn EIGEN historie, niet alleen van externe literatuur: een vraag als "wat deed ik
    de vorige keer dat de kersenvlieg explosief toesloeg?" of "welk middel gebruikte ik vorig
    jaar tegen Monilia, en hielp dat?" zou idealiter ook een logboek-RAG-zoekopdracht triggeren,
    naast de bestaande Track 1-kennisbankzoekopdracht. Dit hangt nauw samen met punt 14 hierboven
    (Observation-Action-Consequence-tuples) — dezelfde logboekregels zijn de bron voor beide,
    en een OAC-tuple-extractie zou een natuurlijke tussenstap kunnen zijn vóór een volledige
    logboek-RAG-index (al is dat niet strikt noodzakelijk: ook de ruwe, ongestructureerde
    logboekregels zelf zouden al een eerste, eenvoudiger versie van deze RAG-bron kunnen vormen).
    Let op: dit raakt de bestaande "nooit proprietaire bedrijfsdata naar een publieke/gedeelde
    context lekken"-afspraak (zie [G.13](#sec-g13)) niet — de logboek-RAG-index zou, net als de
    database zelf, lokaal-only blijven en nooit in de publieke pod-kennisbank terechtkomen.
    **GEBOUWD, lokaal-only (2026-10-10, [G.27](#sec-g27))**: `orchard_logbook_rag.py` (tool `logboek_zoeken` + upfront-retrieval voor
    "eigen historie"-vragen, alleen met `ORCHARD_LOGBOOK_RAG=1`, niet op de pod). Nog te doen: de 487 regels laten verifiëren (0 geverifieerd).
22. **Waar voert de teler in het seizoen gegevens in (privacy en toegang)?** De regel is dat bedrijfsdata (logboek, scans, instellingen, straks oogst/foto's) lokaal blijft; de publieke pod
    heeft sinds 2026-10-09 echter een schrijfbare verificatiepagina met de database en scans, bereikbaar voor iedereen met de URL (zie "Local vs cloud"). Voor invoer in het veld (telefoon)
    is een **privé, beveiligde instantie** nodig (login of VPN), gescheiden van de publieke, alleen-lezen spiegel. Besluit nodig vóór de datainvoer begint ([Deel I](#deel-i), D1).
23. **Perceel-/blok-/rijindeling**: bestaat er een kaart met blokken, rijnummers en rassen? Nodig om elke meting, behandeling en pluk aan een plek te koppelen ([H.1](#sec-h1)).
24. **Syllit-bevinding ([G.31](#sec-g31))**: kloppen de 3–5 toepassingen per jaar in het logboek (of zijn het deelbehandelingen/aparte percelen)? En wat is er in plaats van Movento gebruikt
    sinds de toelating onder die naam verliep? Alleen de teler kan dat bevestigen.
25. **Beregening en watervoorziening**: is er beregening of druppelirrigatie, uit welke bron (grondwater/sloot/leiding), en wordt de hoeveelheid ergens gemeten? Nodig voor de waterbalans ([G.29](#sec-g29)).
26. **Afzet en prijzen**: welke klassen/maten worden verkocht, tegen welke prijs, en waar worden de kilo's nu al ergens geregistreerd? Nodig voor de economie-koppeling ([H.3](#sec-h3) I).
27. **Verificatiecapaciteit**: wie verifieert de 487 logboekregels (en de 2026-regels die nog ingevoerd moeten worden) en hoeveel uur per week is daarvoor beschikbaar? Zonder verificatie blijft 0 van 487 regels bevestigd.
28. **Budget en beheer van sensoren en camera's**: wat is de ruimte en wie plaatst, onderhoudt en leest ze uit ([H.7](#sec-h7))? Bepaalt of we met het starterspakket beginnen of verder gaan.

---



<a id="deel-g"></a>
# Deel G — Implementatiestatus (chronologisch verslag van wat werkelijk gebouwd is)

Dit deel is géén ontwerp meer — het is het chronologische, eerlijke verslag van wat er sinds
2026-10-08 daadwerkelijk gebouwd, getest en gedeployed is, in dezelfde geest als Auto Pilot's eigen
`design_captain_missions.md` §14-17 ("de echte implementatielog — neem nooit 'alleen ontwerp' aan
zonder dit gelezen te hebben"). Waar iets afweek van Deel A-F staat dat hier expliciet benoemd, en is
Deel A-F zelf ook bijgewerkt met een verwijzing hierheen.

<a id="sec-g1"></a>
## G.1 Lokale + cloud-infrastructuur

- **Lokaal**: `.venv` met Python 3.13.16 in de projectroot, Streamlit draait op `localhost:8511`.
- **Cloud-pod**: LeafCloud-instance `orchard-v2` (IP `45.135.57.59`), type `eg1.a30x1.V8-32` =
  1× NVIDIA A30 (24 GB VRAM). NVIDIA-driver 570 + CUDA 12.8 geïnstalleerd (reboot nodig geweest).
  Python 3.13 via `uv` (de deadsnakes-PPA had geen Ubuntu-focal-packages beschikbaar). Volledige
  ML-stack geïnstalleerd: `torch` (cu128), `transformers`, `peft`, `trl`, `bitsandbytes`, later
  aangevuld met `sentence-transformers`/`pdfplumber`/`beautifulsoup4`/`lxml` voor de RAG-pipeline
  (torch bleef ongemoeid — pip zag de al-geïnstalleerde versie als voldoende, geen herdownload nodig).
- **Publieke deployment**: nginx reverse-proxy (poort 80/443 → Streamlit's interne 8501), twee
  systemd-services (`orchard-streamlit`, `orchard-qwen`) zodat beide overleven na
  SSH-disconnect/reboot. De schrijfbare Logboek-Verifiëren-pagina stond aanvankelijk uitgeschakeld
  op de pod (bestand hernoemd naar `_6_Logboek_Verifieren.py.disabled`, database-file `chmod 444`)
  zodat de publieke demo read-only was. **Op expliciet verzoek van de gebruiker (2026-10-09)
  heractiveerd**: bestand teruggezet naar `6_Logboek_Verifieren.py`, database `chmod 664` —
  de publieke pod is dus niet langer read-only; iedereen met de link kan nu de originele scans
  bekijken en de database bewerken. Terugdraaien kan door dezelfde stappen in omgekeerde
  volgorde uit te voeren (zie `.github/copilot-instructions.md`).
- **HTTPS**: geen eigen domein beschikbaar, dus `sslip.io` gebruikt (`45-135-57-59.sslip.io` resolvet
  automatisch naar dat IP) om een Let's Encrypt-certificaat te kunnen aanvragen via certbot — werkend
  HTTPS + HTTP→HTTPS-redirect + automatische renewal-timer.
- **Netwerk-beperking ontdekt**: LeafCloud's standaard security group staat alleen SSH(22)/HTTP(80)/
  HTTPS(443) van buitenaf toe, ook als een proces op bijv. poort 8501 aan `0.0.0.0` bindt — vandaar de
  nginx-reverse-proxy-opzet in plaats van Streamlit direct extern te ontsluiten.
- **Poortconflict opgelost**: de Qwen-inferentieserver draait op poort **8811**, niet het "default"
  8801, omdat de gebruiker al een lokale SSH-tunnel op 8801 had staan naar een ANDER
  Auto-Pilot-Qwen-proces — gedocumenteerd in zowel `cloud/qwen_inference_server.py` als
  `pipeline/qwen_remote.py` zodat dit niet per ongeluk terugverandert.
- **GPU-kosten: automatische idle-unload** (`cloud/qwen_inference_server.py`, `IDLE_UNLOAD_S`): een
  achtergrondthread (`_idle_unload_loop()`) verwijdert het Qwen3-8B-model uit VRAM als er
  **3 minuten (180s)** geen `/generate`-verzoek is geweest — zichtbaar in `nvidia-smi`/`/status` als
  `loaded_models: []`. De eerstvolgende vraag daarna laadt het model opnieuw (een paar seconden
  extra), maar dat is bewust geaccepteerd: de GPU staat zo het grootste deel van een rustige dag
  leeg i.p.v. onnodig VRAM (en dus stroom/kosten) vast te houden voor een model dat toch niet gebruikt
  wordt. Was aanvankelijk op 60s gezet, op verzoek verruimd naar 180s zodat een gebruiker die binnen
  een paar minuten een vervolgvraag stelt niet steeds opnieuw de laadtijd betaalt. **Update
  2026-10-09** ([G.21](#sec-g21)): na de vLLM-migratie verder verruimd naar **300s (5 minuten)** als
  nieuwe standaard (`ORCHARD_QWEN_IDLE_UNLOAD_S`) — AWQ-gewichten+KV-cache passen zo ruim naast de
  rest dat een langere drempel geen VRAM-risico geeft, alleen minder onnodige koude starts.

<a id="sec-g2"></a>
## G.2 Walking skeleton: deterministische kern + Streamlit-app

- `core/paths.py`: `AgentPaths`-conventie, direct overgenomen van Auto Pilot, vereenvoudigd tot één
  domein (`AgentPaths.orchard()`).
- `pipeline/orchard_phenology_spec.py`: pure, deterministische functies voor koude-uren (Weinberger
  0-7,2°C-venster), growing-degree-days, nachtvorst-risico, suzuki-fruitvlieg-risico,
  vruchtbarsten-risico — elk met een `source_citation`-veld en een expliciet "illustrative placeholder"
  vs. "real, cited"-label (nooit stilzwijgend een drempel verzinnen).
- `pipeline/orchard_tools.py`: Open-Meteo forecast/historical/window, Buienradar-nowcast,
  Nominatim+Open-Meteo-geocoding; `check_ctgb_toelating()`/`get_soil_info()` blijven expliciete
  `NotImplementedError`-stubs.
- Streamlit-app: `app/Home.py` + aanvankelijk 5, nu 10 pagina's (zie [B.9](#sec-b9)).
- **Emoji volledig verwijderd** uit alle UI-labels/bestandsnamen/knoppen (op expliciet verzoek) —
  Streamlit genereert navigatielabels automatisch uit bestandsnamen, dus bestanden zijn hernoemd
  i.p.v. alleen de titel-tekst aan te passen.
- Hero-afbeelding (`Images/kersenboomgaard-...jpg`) toegevoegd aan de Home-pagina — **blijft
  gitignored** omdat de bestandsnaam een WordPress-media-patroon suggereert (mogelijk niet eigen
  auteursrecht), zie [G.13](#sec-g13).
- Alles getest via `pytest` + `streamlit.testing.v1.AppTest` (smoke-check: elke pagina moet
  exceptie-vrij renderen).

<a id="sec-g3"></a>
## G.3 Logboek-OCR en -database (Track 2)

- Alle 91 pagina's (`Data/Data Log Books/jaar 2013.pdf` … `jaar 2026.pdf`) gerenderd naar PNG en
  visueel getranscribeerd (multimodaal, geen klassieke OCR-engine) door meerdere parallelle
  achtergrond-agents, elk een jaar-reeks.
- `pipeline/ingest/build_logbook_database.py`: bouwt `Data/Orchard/OrchardLogbooks/orchard_logbook.db`
  (SQLite: `pages`/`entries`/`toepassingen`) uit de transcriptie-JSONs, met een `--force`-vangrail
  tegen het per ongeluk overschrijven van al-geverifieerde rijen. Resultaat: **487 entries, 1063
  toepassingen, periode 2013-05-08 t/m 2025-11-07, 163 entries (33%) `onzeker=true`**.
  464/487 (95%) entries hebben een bruikbare `datum_iso`.
  - *Bekende eigenaardigheid*: één logboekregel bleek een vooruitgeschreven, later doorgehaalde regel
    in het 2022-boekje te zijn voor 2023 — een voorbeeld van waarom `datum_iso` (de echte datum op de
    regel) leidend is, niet `pages.jaar` (welk fysiek boekje het is).
- `app/pages/5_Logboek.py`: doorzoekbaar op jaar/middel/zekerheid, met een weer-contextknop per entry.
- `app/pages/6_Logboek_Verifieren.py`: menselijk verificatie-werkproces met roteer-/zoomknoppen op de
  originele scan-afbeelding (uitgeschakeld op de publieke pod, zie [G.1](#sec-g1)).
- **Weer-in-context-popup** (`app/orchard_common.py::render_weather_dialog_button`, gedeeld tussen
  Logboek en Logboek Verifiëren): toont het weer van de week ervoor/erna rond een logboekregel
  (regen, wind(richting), temperatuur, zonuren, ET0) — met expliciete afronding
  (`st.column_config.NumberColumn`, 1 decimaal, ET0 2 decimalen; Python-`round()` alléén bleek
  onvoldoende om `st.dataframe()`'s eigen weergave te sturen).
- **Adres-geocoding**: sidebar-invoerveld dat een adres omzet naar lat/lon (Nominatim/OpenStreetMap —
  Open-Meteo's eigen geocoder bleek alleen plaatsnamen te herkennen, geen volledige straatadressen) en
  persisteert naar `Data/Orchard/orchard_settings.json` (gitignored, bevat de echte locatie).
- **Dashboard-uitbreiding**: "weer van de afgelopen periode" (aanpasbare schuifbalk 7-90 dagen) onderaan
  `1_Boomgaard_Dashboard.py` — bewust onderaan, want "komend weer is belangrijker".

<a id="sec-g4"></a>
## G.4 Qwen3-8B live op de cloud-pod (Fase 1)

> **Update 2026-10-09** ([G.21](#sec-g21)): de inference-server (`cloud/qwen_inference_server.py`)
> is sindsdien gemigreerd van `transformers.generate()` + bitsandbytes NF4 naar vLLM + AWQ 4-bit
> (snelheid + streaming) — de rest van deze sectie beschrijft de oorspronkelijke, inmiddels
> vervangen opzet, nog correct als geschiedenis van hoe Qwen3-8B voor het eerst live kwam.

- `core/qwen_loader.py`, `cloud/qwen_inference_server.py`, `pipeline/qwen_remote.py`: direct
  overgenomen van Auto Pilot, vereenvoudigd tot één domein ("Orchard").
- Qwen3-8B gedownload in 4-bit NF4-kwantisatie (~6 GB VRAM van de 24 GB beschikbaar) — de volledige
  bf16-gewichten (~16 GB) moeten wel eerst gedownload worden (bitsandbytes kwantiseert pas bij het
  laden, niet vooraf op schijf), wat met de pod se beperkte bandbreedte (~3,5 MB/s) 75-90 minuten duurde.
  Dit was ook de reden om voor Qwen3-8B i.p.v. Mistral te kiezen (zie [B.7](#sec-b7)).
  - Er is overwogen een nog kleiner model te nemen, maar Qwen3-8B past ruim en Auto Pilot had er al
    een beproefde laadroutine voor.
- Gedeployed als systemd-service `orchard-qwen` (localhost-only, poort 8811 — zie [G.1](#sec-g1)).
- "Vraag de Adviseur"-pagina herbedraad: deterministische tool-routing blijft eerst en autoritatief;
  alleen niet-gematchte vragen gaan naar het echte Qwen3-8B (met een expliciete
  hallucinatie-waarschuwing, want nog geen RAG/training in deze fase). Bevestigd: Qwen antwoordt vlot
  in het Nederlands, maar hallucineert domeinfeiten (verwacht, pre-RAG).
- Lokale `.env` met `ORCHARD_CLOUD_SSH_HOST/KEY/USER` voor automatisch SSH-tunnel-herverbinden vanaf de
  laptop (`pipeline/qwen_remote.reconnect_tunnel()`).

<a id="sec-g5"></a>
## G.5 Track 1-kennisbank verzamelen (Fase 2)

- `pipeline/ingest/build_orchard_corpus.py`: een `SOURCES`-registry + `manifest.json`-provenance-writer,
  rechtstreekse mirror van Auto Pilot's `build_chief_engineer_corpus.py`-opzet — elke URL is
  handmatig geverifieerd vóórdat hij in de registry komt, nooit een gegokte/plausibel-ogende link.
- **Eerste ronde (4 documenten)**: WUR-teelthandleiding, WUR-onderstammenproef zoete kers, USDA
  Agriculture Handbook 442 (1973, GovInfo, public domain — vervangt de niet-gevonden pre-1930
  Farmers' Bulletin 776), EU 2018/848 (HTML, bleek later Engelstalig — zie [Deel F](#deel-f) #8).
- **Tweede ronde (+3 documenten)**: Netafim-kersenadviesrapport (commercieel, als zodanig gelabeld),
  Biofruitnet-onderstammen-factsheet (EU Horizon 2020-project), OSU EM9267
  (Spotted Wing Drosophila-gids, Oregon State University Extension — grondt eindelijk de suzukii-
  risicofunctie op een echte, citeerbare bron i.p.v. "illustrative placeholder").
- **Bewust niet gebruikt**: een door websearch gesuggereerde WUR-edepot-ID voor een Nederlandstalige
  suzuki-fruitvlieg-factsheet bleek bij download een compleet ander (tuinbouw-statistiek) document te
  zijn — niet gebruikt, zelfde les als de eerdere FB1399-misser (nooit een gesuggereerde
  bron-ID vertrouwen zonder de gedownloade inhoud te verifiëren).
- **Geblokkeerd, eerlijk gedocumenteerd**: Ctgb-bulk-export (dode URL), Actua Steenfruit-archief
  (alleen de 2 al-bezeten nummers), pre-1930 USDA-bulletin.
- Resultaat: **7 acquired, 3 blocked, 0 failed** — zie [C.1](#sec-c1) voor de volledige lijst.

<a id="sec-g6"></a>
## G.6 RAG + reranking + ReACT-agent + zichtbare CoT (Fase 3 — "Vraag de Adviseur")

- **Parsen**: `pipeline/ingest/parse_orchard_documents.py` (pdfplumber voor PDF, BeautifulSoup voor
  HTML) → per-document JSON in `Data/Orchard/Orchard_JSON/`. Het EU-2018/848-bestand wordt hier bewust
  overgeslagen (`SKIP_FROM_RAG`).
- **Chunken + embedden**: `pipeline/ingest/build_orchard_rag.py` — eenvoudiger dan Auto Pilot's eigen
  TextTiling-gebaseerde chunker (bewust: bij 6 documenten is dat disproportioneel), paragraaf-bewust
  token-budget-chunken (~220 woorden, 30 woorden overlap). Embedding-model:
  `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` (niet Auto Pilot's Engelstalige
  `BAAI/bge-large-en-v1.5`, want deze kennisbank mengt NL en EN). Resultaat: **347 doorzoekbare
  fragmenten**.
- **Retrieval + reranking**: `pipeline/orchard_rag.py` — dense cosine-similarity-zoekopdracht (brede
  kandidatenpool) gevolgd door een pretrained multilingual cross-encoder
  (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, Nederlands is een van mMARCO's 14 talen) die
  herscoort naar de uiteindelijke top-k — bewust GEEN zelf-getrainde reranker (nog geen gouden
  eval-set om op te trainen, zie Auto Pilot's eigen `train_reranker.py`-precedent).
- **Tool-catalogus**: `pipeline/orchard_tool_catalog.py` bindt de bestaande deterministische tools
  (weer, koude-uren, vorst, suzuki, vruchtbarsten, Ctgb-guardrail) + een kennisbank-zoektool als
  aanroepbare functies.
- **ReACT-agent**: `pipeline/orchard_agent.py::ask_orchard_advisor()` — altijd eerst een
  kennisbank-zoekopdracht met de vraag zelf, dan een lus (max. 3 stappen) waarin Qwen een tool mag
  aanroepen vóór het einantwoord. Gebruikt Qwen3's **eigen** `<think>`-redenering (`enable_thinking=True`)
  i.p.v. een handmatige CoT-prompt-truc — getoond in een inklapbare "Redenering (CoT)"-sectie.
- **Bug gevonden en gefixt**: bij een te klein token-budget kon generatie worden afgekapt MIDDEN in het
  `<think>`-blok, waardoor de ruwe, onafgemaakte redenering als "antwoord" dreigde te lekken —
  opgevangen met detectie van een ongesloten `<think>`-tag + één automatische retry met een groter
  budget.
- **Duim-omhoog/omlaag + DPO-dataverzameling** (toegevoegd 2026-10-09): elk antwoord van de agent
  krijgt 👍/👎-knoppen. Een klik slaat het (vraag, gegeven-antwoord, alternatief-label)-paar op als
  een DPO-voorkeurspaar in `Data/Orchard/Orchard_Agents_Training/orchard_dpo_feedback.jsonl` — 👍
  markeert het getoonde antwoord als `chosen`, 👎 markeert het als `rejected` (met het antwoord zelf
  nog steeds zichtbaar, geen her-generatie nodig). Dit is een VERZAMELMECHANISME, geen trainingsstap
  op zich — de daadwerkelijke DPO-trainingsronde (roadmapstap 7, [Deel E](#deel-e)) volgt pas als er
  genoeg paren zijn. Zie [Deel F](#deel-f) #11 voor de open vraag hierover.
- **Hallucinatie-indicator** (toegevoegd 2026-10-09): elk antwoord krijgt een rood/groen label
  (`pipeline/orchard_agent.py`'s `grounding`-veld) — **groen** als het antwoord aantoonbaar
  RAG-fragmenten en/of tool-resultaten uit DEZE beurt gebruikt (gemeten: zijn er bronnen/tool-calls
  EN citeert de tekst van het antwoord daadwerkelijk naar "Bronnen:"/tool-namen), **rood** als het
  antwoord geen enkele gebruikte bron/tool-call heeft maar wel een feitelijke bewering lijkt te doen.
  Dit is EXPLICIET een heuristiek (zie [Deel F](#deel-f) #12) — geen garantie dat een "groen" antwoord
  klopt, alleen dat het zich op iets aangeleverds baseert.

<a id="sec-g7"></a>
## G.7 Patroonherkenning: meerjaren-trends

- `pipeline/orchard_patterns.py`: 10 zelfgedefinieerde probleemcategorieën (fruitvliegen, vruchtrot,
  bacterieziekte/kanker, bladvlekkenziekte, bladvalziekte, hagelschot, spint, luis, rupsen,
  bestuiving/bijen, bladvoeding), elk met een eigen, EXPLICIET-benoemd "belang voor de oogst"-gewicht
  (geen literatuur-ranking — een eigen inschatting, zie de UI-uitleg op de pagina zelf).
- Drie detectortypes: **seizoenstiming** (verschuift het eerste moment per jaar vroeger/later?),
  **frequentie** (neemt het aantal behandelingen per jaar toe/af?), **dosering** (stijgt de
  gemiddelde dosis per toepassing — mogelijk resistentiesignaal?) — elk gescoord op dezelfde 0-1
  "belang"-schaal zodat ze onderling vergelijkbaar zijn, plus een altijd-getoonde teeltkalender
  (maand-voor-maand heatmap, geen trend).
- **Gevalideerd tegen echte data**: fruitvliegendruk en bacterieziekte nemen aantoonbaar toe over de
  jaren, bestuiving piekt in april (bloeitijd), vruchtrot/fruitvliegen pieken in mei-juni (vlak
  voor/tijdens oogst) — allemaal agronomisch plausibel. Opvallendste los gevonden patroon: de
  dosering van Zink steeg van ~200 naar ~900 ml per toepassing.
- UI: `app/pages/7_Patroonherkenning.py`, met drill-down naar de onderliggende logboekregels per
  patroon.

<a id="sec-g8"></a>
## G.8 Seizoenswaarschuwingen en preventieve weer-naar-ziekte-signalen

Twee aanvullende, los ontwikkelde detectielagen op dezelfde pagina:

- **Seizoenswaarschuwingen** (`pipeline/orchard_season_watch.py`): vergelijkt het gekozen seizoen
  TOT NU TOE met dezelfde kalenderperiode in voorgaande jaren — temperatuur, waterbalans
  (neerslag − ET0, zowel een tekort- als een overschot-signaal), logboek-plaagdruk (cumulatief aantal
  meldingen per categorie, vergeleken met hetzelfde punt in eerdere seizoenen), en bestuivingsweer
  tijdens de bloei (vuistregel: bijen vliegen slecht onder 13°C/bij regen/bij harde wind >25 km/u).
  Een altijd-getoonde, eerlijke placeholder (`soil_ph_status_note()`) legt uit dat bodem-pH/zuurgraad
  nog NIET gesignaleerd kan worden (geen echte bodemdata-koppeling, zie [C.4](#sec-c4)).
- **Preventieve weer-naar-ziekte-signalen** (`pipeline/orchard_disease_weather_links.py`) — dit is de
  directe invulling van "relaties tussen weer, ziektes en middelen herkennen zodat we niet te laat
  zijn": voor elke categorie wordt het weer in de dagen VÓÓR elke historische eerste-behandeling-per-
  jaar opgehaald (vocht voor schimmel-/bacterieziekten, warmte voor insecten — een eigen, transparante
  vuistregel, geen literatuur-gekalibreerd model) en vergeleken met het weer van de laatste 10 dagen.
  Alleen als de actuele omstandigheden (a) minstens zo "erg" zijn als ELKE eerdere aanleiding ÉN (b)
  binnen het seizoensvenster vallen waarin die categorie historisch ook echt voorkomt, wordt het
  gemeld. (b) was een noodzakelijke bugfix: zonder seizoensgrens meldde het systeem aanvankelijk
  "vruchtrot-risico" zelfs in oktober, wat agronomisch onzinnig is.
  **Gevalideerd** tegen een echt historisch moment (de dag vóór een bekende vruchtrot-behandeling in
  2025) — het signaleerde daar correct.
- Beide lagen hergebruiken dezelfde `TARGET_CATEGORIES`/harvest-weight-registry uit
  `orchard_patterns.py` — geen dubbele categorisering.

<a id="sec-g9"></a>
## G.9 Gebruik van Middelen

- `pipeline/orchard_middelen.py`: een handmatig opgebouwde canonicalisatie-/categoriseringsregistry
  die de ~120 schrijfwijzen/OCR-varianten van middelnamen in het logboek (bv. "Zinc"/"Zink",
  "Roval"/"Rovral", "Epso microtop"/"Epso Microstop bitterzout") samenvoegt tot echte producten en
  indeelt in: gewasbescherming (schimmel/bacterie, insect/mijt, onkruid), meststof/bladvoeding,
  hulpstof, bestuiving (bijen/hommels — GEEN middel, maar wel in de `middel`-kolom beland), en
  eerlijk "overig" waar de identiteit niet zeker genoeg was (27 van 1026 toepassingen, 2,6%).
- Telt per week/maand/kwartaal/jaar op — ml en gram worden NOOIT bij elkaar opgeteld.
- UI: `app/pages/8_Gebruik_van_Middelen.py`, met gestapelde grafieken per categorie en drill-down per
  product naar de onderliggende logboekregels.

<a id="sec-g10"></a>
## G.10 Bibliotheek, Help en overige UI-afwerking

- `app/pages/9_Bibliotheek.py`: lijst van en toegang tot de Track 1-kennisbank (download +
  inline PDF-voorbeeld), gevoed door `manifest.json`. De historische logboeken/nieuwsbrieven staan
  hier BEWUST niet (horen bij de Logboek-pagina als doorzoekbare data, niet als losse bestandenlijst).
- Decimalen-precisie: overal waar weer-tabellen getoond worden, expliciete
  `st.column_config.NumberColumn(format="%.1f")` (1 decimaal, ET0 2 decimalen) — `round()` in Python
  alleen bleek niet genoeg om Streamlit's eigen dataframe-weergave te sturen.
- "Vraag de Adviseur"-layout: de lange fase-waarschuwing staat nu ONDER de chatgeschiedenis, vlak
  boven de invoerbalk, zodat de chat direct bovenaan begint (invoerbalk zelf is sowieso
  altijd-onderaan-vast door Streamlit's eigen `st.chat_input()`-gedrag).
- `app/pages/10_Help.py` (toegevoegd 2026-10-09): gebruikersgerichte documentatie — wat elke pagina
  doet en hoe je 'm gebruikt, GEEN technische architectuur-uitleg (die staat in dit document).

<a id="sec-g11"></a>
## G.11 Test- en kwaliteitsstatus

- **139 automatische tests** (`pytest tests`, groeiend met elke nieuwe feature) — uitsluitend op
  synthetische/eigen testdata, nooit op de echte (gitignored) logboek-/instellingen-data.
- Elke nieuwe/gewijzigde Streamlit-pagina krijgt een smoke-check via
  `streamlit.testing.v1.AppTest` (laadt de pagina, controleert op exceptions) — niet als permanente
  pytest-bestanden (zelfde conventie als dit project al hanteerde), maar als terugkerende
  verificatie-stap vóór elke sync naar de pod.
- Live/netwerk-afhankelijke functionaliteit (Open-Meteo, Qwen3-8B-generatie, RAG-modellen laden)
  wordt NIET in de geautomatiseerde suite getest (geen flaky/netwerk-afhankelijke CI), maar wel
  handmatig gevalideerd tegen de echte data/API's bij elke nieuwe feature (zie bijv. [G.8](#sec-g8)'s
  validatie tegen een echt historisch moment).
- Beide omgevingen (laptop + cloud-pod) draaien dezelfde testsuite vóór elke herstart van de publieke
  service.

<a id="sec-g12"></a>
## G.12 Belangrijkste geleerde lessen / bugs opgelost

Een eerlijke lijst van wat er mis ging en hoe het opgelost is — nuttig voor toekomstig werk aan dit of
een volgend domein:

- **`st.dataframe()`-decimalen**: Python-`round()` alleen stuurt de weergave niet; nodig is
  `st.column_config.NumberColumn(format=...)` (of `.format()` op een pandas `Styler`).
- **Open-Meteo Archive-API heeft nog geen data voor "vandaag" zelf** (pas vanaf gisteren) — ontdekt
  toen `compute_disease_weather_early_warnings()` crashte met HTTP 400. Opgelost met
  `pipeline.orchard_tools.latest_available_archive_date()`, overal consequent toegepast.
  - Gerelateerde EUR-Lex-les: herhaalde snelle requests leidden tot `202 Accepted`/lege body —
    waarschijnlijk rate-limiting, niet geforceerd ("don't brute-force a blocked approach").
- **Z-score bij nul-variantie-baseline**: als elk voorgaand jaar exact dezelfde waarde had (bv.
  "altijd precies 1x"), gaf een standaard z-score-berekening 0.0 terug bij een afwijkende huidige
  waarde (division-by-zero-vangrail verborg het net de interessante gevallen) — opgelost met een
  heuristische minimale spreiding (10% van het gemiddelde) als de echte spreiding nul is.
- **Qwen3 `<think>`-afkapping**: bij te weinig `max_new_tokens` kon de redenering nooit worden
  afgesloten, waardoor ruwe CoT-tekst als "antwoord" dreigde te lekken — opgevangen met
  ongesloten-tag-detectie + automatische retry.
- **WUR edepot.wur.nl blokkeert kale/HEAD-requests (403)** — vereist een GET met een realistische
  browser-`User-Agent`-header (zelfde les als Auto Pilot's eigen "maritime.org heeft een
  Referer-header nodig"-ontdekking: andere site, zelfde les — probeer realistische headers vóór je
  concludeert dat iets "geblokkeerd" is).
- **Nooit een door een taalmodel gesuggereerde bron-ID vertrouwen zonder de gedownloade inhoud te
  verifiëren** — twee keer deze sessie bleek een plausibel-ogende suggestie (een WUR-edepot-ID, een
  Farmers'-Bulletin-nummer) bij daadwerkelijke download een compleet ander document te zijn.
- **PowerShell-naar-SSH-quoting**: complexe bash-commando's met `$VAR`/pipes/geneste quotes via
  PowerShell→ssh→bash verliezen escaping. Oplossing: voor iets complexers dan een eenvoudig
  commando, een lokaal tijdelijk `.py`/`.sh`-scriptje schrijven en via `scp` overzetten i.p.v. inline
  te quoten.
- **Streamlit's `st.chat_input()` is altijd onderaan vast** (viewport-gedrag), ongeacht waar in de
  code het aangeroepen wordt — "de vraagbalk naar boven zetten" is daarom vertaald naar "alles wat
  niet de chat zelf is, inclusief de lange waarschuwing, naar onderen verplaatsen".

<a id="sec-g13"></a>
## G.13 Git/GitHub en synchronisatie

- Repo aangemaakt op `https://github.com/TextMiningUM/Orchard` (zelfde account/org als Auto Pilot,
  credentials al aanwezig via Windows Credential Manager).
- **`.gitignore`-ontwerpkeuze (bewust, met de gebruiker afgestemd)**: de eigen logboek-bedrijfsgegevens
  (`Data/Data Log Books/`, `orchard_logbook.db` + transcripten + scans, `orchard_settings.json` met
  het echte adres) blijven **lokaal-only** — dit is echte, herleidbare bedrijfsinformatie van één
  specifieke teler (welke middelen, wanneer, hoeveel) die niet ongevraagd naar een (mogelijk publieke)
  git-repo hoort, ook al is dat technisch dezelfde org als Auto Pilot. Ook `Images/` (vermoedelijk
  gescrapete stockfoto) en `Docs/` (privé-briefingdocumenten) blijven lokaal, zelfde conventie als
  Auto Pilot's eigen `Docs/`-behandeling. De Track 1-kennisbank (overheids-/universiteitsbronnen) WEL
  getrackt, zelfde precedent als Auto Pilot's eigen corpus-bestanden.
- `.github/copilot-instructions.md` en `README.md` geschreven (stonden al open van een eerder verzoek)
  — documenteren de AgentPaths-conventie, de lokaal-vs-cloud-split, en alle hierboven genoemde
  geleerde lessen, zodat een toekomstige sessie (mens of agent) niet opnieuw tegen dezelfde muren
  aanloopt.
- **Sync-werkwijze naar de pod**: de pod heeft geen git-checkout (geen `git` push/pull-workflow
  opgezet) — wijzigingen worden per batch als `tar.gz` gepackaged, ge-`scp`'t, en op de pod uitgepakt,
  gevolgd door `pytest` + een systemd-service-herstart + een curl-verificatie van zowel de
  lokale als de publieke URL. Dit is bewust lichtgewicht gehouden i.p.v. een CI/CD-pipeline op te
  zetten, gezien de schaal van dit project.

<a id="sec-g14"></a>
## G.14 Chat-UX: feedback/grounding, gespreksgeheugen en bewaarde chats

Na de bovenstaande herschrijving van dit document zijn op "Vraag de Adviseur" nog vier met elkaar
samenhangende features toegevoegd, allemaal in `app/pages/3_Vraag_de_Adviseur.py` +
nieuwe/uitgebreide pipeline-modules:

- **DPO-feedback (duim omhoog/omlaag)** — `pipeline/orchard_feedback.py`: elk antwoord krijgt een
  "Nuttig"/"Niet nuttig"-knop (bewust tekst, geen emoji — zie hieronder). Een klik slaat een
  `FeedbackRecord` op als regel in `Data/Orchard/Orchard_Agents_Training/orchard_dpo_feedback.jsonl`
  (vraag, antwoord, voorkeur, timestamp, gebruikte bronnen/tools). Dit is **één kant** van een
  toekomstig DPO-voorkeurspaar (chosen óf rejected) — een los dataset-bouw-script moet records met
  vergelijkbare vragen later samenvoegen tot echte paren; dat script bestaat nog niet (zie
  [Deel F](#deel-f) #11).
- **Hallucinatie-/grounding-indicator** — `pipeline.orchard_agent.assess_grounding()`: een HEURISTIEK
  (geen garantie) die een antwoord als "gegrond" bestempelt als zowel (a) er tool-output en/of
  kennisbank-bronnen beschikbaar waren ALS (b) de antwoordtekst daar ook daadwerkelijk naar verwijst.
  UI toont dit als `st.success`/`st.error` met tekstlabel "GEGROND" / "GEEN GROUNDING GEVONDEN" (ook
  hier bewust geen rood/groen-emoji of iconen, zie [Deel F](#deel-f) #12 voor de beperkingen van deze
  heuristiek).
- **Gespreksgeheugen over meerdere beurten** — `ask_orchard_advisor()` accepteert nu `history` +
  `max_history_turns`; `build_history_messages()` (pure helper) zet eerdere beurten uit
  `st.session_state["chat_history"]` om in chat-berichten vóór de huidige vraag, en strip daarbij het
  UI-only-disclaimer-voetnotje van eerdere assistent-antwoorden (anders zou het model dat opnieuw
  gaan citeren). Hierdoor werken vervolgvragen ("en is dat erg voor kersen?") correct met de context
  van het voorgaande antwoord — handmatig gevalideerd met een echte suzuki-fruitvlieg-vervolgvraag.
- **Bewaarde/hervatbare chats (ChatGPT-stijl)** — `pipeline/orchard_chats.py`: één JSON-bestand per
  chatsessie (`ChatSession`/`ChatTurn`-dataclasses) in `Data/Orchard/OrchardChats/` (GITIGNORED,
  zelfde reden als de logboekdata — kan echte vragen over de eigen boomgaard bevatten). De pagina
  opent ALTIJD op een verse, lege chat (bewuste keuze, zelfde gedrag als ChatGPT — geen automatisch
  hervatten van de laatste chat); eerdere chats staan als knop in de zijbalk met een automatisch
  afgeleide titel (`derive_title()`: eerste vraag ingekort/opgeschoond, val terug op "Nieuwe chat" als
  er nog geen vraag was) en kunnen met een klik hervat worden (volledige vraag/antwoord-geschiedenis
  + feedback-status wordt teruggezet) of verwijderd. Elke nieuwe beurt en elke feedback-klik roept
  `_save_current_chat()` aan, dus een chat staat altijd actueel op schijf, ook als de gebruiker
  tussentijds wegnavigeert.
- **"De adviseur denkt na"-spinner** — een volledige chat-beurt duurt op de pod ~30-35s (RAG-index
  laden + Qwen3-8B-generatie); zonder enige visuele terugkoppeling leek dit "kapot". Een
  `st.spinner("De adviseur denkt na...")` rond de hele routeringsaanroep lost dit op.

Twee bugs kwamen bij het bouwen van bovenstaande aan het licht (zie ook [G.12](#sec-g12)):

- **"Maar één vraag werkt, dan niets meer"** bleek het inmiddels bekende stale-module-cache-probleem
  (zie [G.12](#sec-g12)) opnieuw — ditmaal `AttributeError: 'AdvisorResponse' object has no attribute
  'grounding'` omdat de lang-lopende lokale `streamlit run`-server het nieuwe dataclass-veld niet had
  opgepikt. Opgelost door het proces volledig te stoppen en opnieuw te starten (niet door code te
  wijzigen) — dit is nu de tweede keer dat dit exacte symptoom zich voordeed, dus eerste
  verdenking bij toekomstige "werkte net nog, nu ineens een AttributeError/ImportError"-meldingen.
- **Emoji sloop zich er opnieuw in** (rood/groen bolletjes, duim-emoji) tijdens het bouwen van
  bovenstaande features — opnieuw gesaneerd met dezelfde regex als eerder
  (`[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}]`), met tekstlabels als vervanging. Dit project heeft dus
  een terugkerende "geen emoji in de UI"-afspraak die bij élke nieuwe feature opnieuw gecontroleerd
  moet worden, niet een eenmalige opschoning.

<a id="sec-g15"></a>
## G.15 Boomgaard-instellingen verhuisd naar een eigen "Instellingen"-pagina

De locatie-/ras-/fase-invoervelden stonden eerst op élke pagina bovenaan de zijbalk
(`orchard_common.render_sidebar()`) — bij een lager browservenster duwde dat andere
zijbalk-inhoud (met name de "Chats"-lijst op Vraag de Adviseur, zie [G.14](#sec-g14)) buiten
beeld zonder te scrollen. Opgelost in twee stappen (de eerste bleek nog niet ver genoeg):

1. Eerst een compacte samenvatting + link geprobeerd (`st.sidebar.page_link(...)`) i.p.v. de
   volledige velden. Dit werkte in de echte app, maar nam alsnog ruimte in — de gebruiker gaf
   terecht aan dat zelfs die samenvatting niet nodig is ("de gebruiker kan zelf wel verzinnen
   dat dat in instellingen zit").
2. **`render_sidebar()` rendert nu helemaal niets meer** — de functie laadt/seedt alleen nog
   `st.session_state` (met dezelfde "onthoud de laatst gezochte locatie"-logica als voorheen)
   en geeft een `OrchardContext` terug; geen enkele widget, caption of link meer in de zijbalk
   van welke pagina dan ook.
- Nieuwe pagina `app/pages/11_Instellingen.py`: bevat nu de volledige, ongewijzigde
  invoervelden (adres zoeken + onthouden, lat/lon, ras, fenologische fase) die voorheen in de
  zijbalk stonden — zelfde gedrag, alleen een andere plek in de navigatie. Ook toegevoegd aan
  Help ([10_Help.py](#sec-g10)).
- **Les (AppTest-valkuil, geen echte bug)**: `st.page_link("pages/11_Instellingen.py", ...)`
  gaf tijdens een `AppTest`-run `StreamlitPageNotFoundError`, terwijl het in de echte, draaiende
  multipage-app prima werkte — `AppTest.from_file()` laadt één pagina-script geïsoleerd, zonder
  de omringende multipage-navigatiecontext te simuleren, dus `page_link`/`switch_page` kunnen
  daar niet getest worden. Niet verder nagejaagd omdat stap 2 hierboven `page_link` toch weer
  overbodig maakte.

<a id="sec-g16"></a>
## G.16 Fase 4: gerichte kennisbank-uitbreiding (10 praktijkproblemen) + retrieval-afstelling

**Aanleiding**: de gebruiker testte "Vraag de Adviseur" met een lijst van tien klassieke
kersenteelt-problemen (nachtvorst tijdens bloei, slechte bestuiving, Monilia, zwarte
kersenluis, kersenvlieg, suzuki-fruitvlieg, vruchtbarsten, vogelschade, bacteriekanker,
bladvlekkenziekte) en kreeg vage, nergens-op-gegronde antwoorden. Voordat er iets aan het
model/de prompt werd veranderd, is dit eerst **empirisch gediagnosticeerd**:

- Een directe RAG-retrieval-test voor alle vijf eerst-geteste onderwerpen leverde bijna
  uitsluitend fragmenten op uit **één Engelstalig document uit 1973** (USDA Handbook 442), met
  voor de meeste onderwerpen zelfs NEGATIEVE cross-encoder-relevantiescores (-1 tot -2,7) — in de
  praktijk "dit fragment gaat hier niet over". De kennisbank bevatte toen maar 7 echt bruikbare
  documenten; niets behandelde specifiek kersenvlieg (Rhagoletis cerasi — iets anders dan
  suzuki-fruitvlieg), zwarte kersenluis, bladvlekkenziekte, vogelschade, of Nederlandstalige
  Monilia/bacteriekanker-bestrijding.
- Conclusie: fine-tunen zou dit NIET oplossen (SFT/DPO verandert stijl/gedrag, niet
  feitenkennis die er niet is) — de kennisbank moest eerst uitgebreid worden. Zie ook de
  bijgewerkte roadmap-prioritering in [Deel E](#deel-e)/[Deel F](#deel-f).

**Uitgevoerd** (`pipeline/ingest/build_orchard_corpus.py` SOURCES-registry uitgebreid,
2026-10-09): 14 nieuwe, stuk voor stuk met een HTTP-request geverifieerde bronnen toegevoegd
(status 200, geen inlogmuur) — 2 extra BIOFRUITNET-praktijksamenvattingen (zelfde
EU Horizon 2020-reeks als de al-aanwezige onderstammen-factsheet: zwarte kersenluis +
aanbevolen rassen) en 12 Nederlandstalige HTML-bronnen (Bayer CropScience, Koppert, Baldur-
Nederland, Fruitbomen.net, Organic Farm Knowledge, AgruniekRijnvallei-tenlersnieuwsbrief,
FruitSecurity Holland, Oosterom Kersen — een ECHTE Nederlandse kersenteler, Bomenenzo).
Commerciële bronnen zijn expliciet als zodanig gelabeld in hun `note`-veld (zelfde
"niet als onafhankelijk onderzoeksinstituut citeren"-discipline als de Netafim-bron). Eén
kandidaat-bron bleek NIET bruikbaar: **pcfruit.be's "kennisdatabank"** (het Vlaamse
Proefcentrum Fruitteelt) gaf bij een geautomatiseerde fetch alleen lidmaatschaps-wervingstekst
en een cookie-dialoog terug, geen artikel-inhoud — ofwel een inlogmuur, ofwel client-side
JavaScript-rendering; niet verder geforceerd, zelfde discipline als de eerdere
Actua-Steenfruit/Ctgb-blokkades.

**Resultaat**: kennisbank van 10 → 21 geaccepteerde documenten, RAG-index van 347 → 397
chunks. Retrieval voor dezelfde vijf onderwerpen die eerst faalden, opnieuw getest: Monilia,
bacteriekanker/hagelschot, kersenvlieg en zwarte kersenluis scoren nu allemaal **sterk
positief** (score +2 tot +8,6) met de juiste, specifieke Nederlandstalige bron als
nummer 1 resultaat (in plaats van een zwak/negatief scorend Engels fragment uit 1973). Een
volledige end-to-end test van `ask_orchard_advisor()` op de Monilia-vraag leverde een
substantieel, correct, groen-gegrond antwoord met 5 echte bronverwijzingen op (tegenover de
eerdere vage non-antwoorden).

**Retrieval-afstelling** (`pipeline/orchard_rag.py::retrieve()`): tijdens het testen bleken
twee van de nieuw toegevoegde, overduidelijk relevante bronnen (vogelschade, vorstberegening)
ALSNOG niet in de top-resultaten te verschijnen — niet omdat de inhoud ontbrak, maar omdat hun
beste fragment op rank 28 resp. 43 viel terwijl de dense-kandidatenpool (`pool_n`) nog op 25
stond (een instelling die paste bij de oude, kleinere kennisbank). `pool_n` is verhoogd naar
**60** en de agent's eigen `k` (aantal fragmenten dat in de prompt komt) van 4 naar **6** — na
deze wijziging scoorden beide onderwerpen meteen de juiste bron als nummer 1 resultaat. Een
derde onderwerp (bestuiving/rassenkeuze) bleef zwakker scoren ondanks aanwezige, relevante
inhoud (BIOFRUITNET-rassenfactsheet) — vermoedelijk gerelateerd aan hetzelfde kolom-
interleaving-parseprobleem dat de gebruiker apart meldde (zie [Deel F](#deel-f) punt 13,
nog niet opgelost): een chunk vol doorelkaar-gehusselde tabeldata reranked merkbaar slechter
dan lopende prosetekst.

**Nog niet gedaan** (op het moment van schrijven van deze sectie): de PDF-kolom-interleaving-
parseproblemen zelf oplossen (Deel F #13) en een systematische
Observation-Action-Consequence(-Why/Worst-case)-tuple-extractie uit zowel het logboek als deze
nu uitgebreide literatuur (voorgesteld door de gebruiker, zie [Deel F](#deel-f) #14) — de eerste
is inmiddels opgelost, zie [G.17](#sec-g17) hieronder; de tweede staat nog gepland.

<a id="sec-g17"></a>
## G.17 PDF-parseerfix (PyMuPDF) + automatische RAG-chunk-kwaliteitscontrole

**Diagnose**: de gebruiker herkende het Netafim-adviesrapport-fragment uit [G.16](#sec-g16) als
een klassiek twee-kolommen-PDF-parseprobleem en vroeg: hebben we dit niet al eens in Auto Pilot
gehad? Dat bleek zo te zijn.

**De fix (direct overgenomen van Auto Pilot, niet opnieuw ontworpen)**: Auto Pilot
(`../Auto Pilot/pipeline/ingest/build_chirp_json.py`, `build_captain_navy_yearbooks_json.py`)
had exact hetzelfde probleem met zijn 2-koloms CHIRP-nieuwsbrieven/Navy-jaarboeken: `pdfplumber`'s
`extract_text()` sorteert woorden primair op verticale positie over de VOLLE paginabreedte, wat
een linker- en rechterkolom regel-voor-regel door elkaar husselt (daar letterlijk bevestigd: twee
ongerelateerde kolommen aaneengesmeed tot één onzinnige zin). Hun oplossing was overstappen op
**PyMuPDF** (`pymupdf`/`fitz`)'s `page.get_text("text")` — expliciet ZONDER `sort=True` (die
modus husselde daar juist nog agressiever) — wat de eigen content-stream-blokvolgorde van de PDF
volgt en zo voor elk geteste document eerst de volledige linkerkolom leest, dan pas de
rechterkolom. Daarnaast passen ze `join_hyphenated_linebreaks()` toe (regex `(\w)-\n(?=[a-z])` →
`\1`) om woorden die een PDF's eigen regelafbreking in tweeën hakte weer aan elkaar te plakken.

Exact dezelfde fix toegepast in `pipeline/ingest/parse_orchard_documents.py::_parse_pdf()`
(nieuwe gedeelde helper `core/text_segmentation.py::join_hyphenated_linebreaks()`, zelfde
module-naam/-locatie als Auto Pilot op doel). Resultaat, handmatig geverifieerd op zowel het
Netafim-rapport als de BIOFRUITNET-zwarte-kersenluis-factsheet (die een vergelijkbare
sidebar-tabel had): beide lezen nu volledig vloeiend en coherent, geen enkel fragment meer dat
halverwege een woord naar een andere kolom springt.

**Automatische kwaliteitscontrole** (`pipeline/ingest/check_rag_chunk_quality.py`, nieuw): om het
"lees een steekproef, bevestig dat het klopt"-vereiste uit [Deel F](#deel-f) #13 te
automatiseren in plaats van puur handmatig te blijven doen, scoort dit script elke RAG-chunk op
next-token-predictie-perplexiteit onder een klein, taal-passend causaal taalmodel
(`GroNLP/gpt2-small-dutch` voor Nederlandse chunks, `distilgpt2` voor Engelse — bewust
taalbewust: een Nederlandse chunk scoren met een Engels model zou vloeiend Nederlands onterecht
als "kapot" bestempelen). Idee: kapotte, door elkaar gehusselde tekst voorspelt zichzelf
inherent slecht (hoge perplexiteit), vloeiend proza voorspelt zichzelf goed (lage perplexiteit).
Resultaat, empirisch bevestigd met een vóór/na-vergelijking:
- VÓÓR de PyMuPDF-fix: de chunks met de hoogste perplexiteit waren overduidelijk kapot —
  letterlijke voorbeelden als "...ra ja N gen..." en "these have limited and temporary value
  though not adopted as a standard management or are almost prohibitive in cost. Control can
  practice. be obtained by scree" (twee onsamenhangende kolom-fragmenten aaneengeplakt).
- NA de fix: dezelfde top-25 bevat geen kolom-interleaving-garbage meer — de resterende hoogst
  scorende chunks zijn ofwel legitiem-maar-ongebruikelijke tekst (titelpagina's,
  auteursnamen, literatuurlijsten — vals-positief voor een klein taalmodel, maar inhoudelijk
  prima) ofwel een APART probleem: HTML-paginachrome (een fruit-categorie-navigatiemenu, een
  webshop-bestel-/sorteerbalk) die niet door de generieke script/style/nav/header/footer-tag-
  strip in `_parse_html()` werd gevangen omdat deze sites die chrome niet in zo'n semantische
  tag verpakken.
- Voor die laatste categorie: 6 specifieke chunk-id's (2 per document, uit
  `fruitbomen_net_bladvlekkenziekte`, `fruitbomen_net_hagelschotziekte`,
  `puurvantveld_kersenvlieg`) zijn handmatig bevestigd als zuivere ruis (nul inhoudelijke
  waarde) en expliciet uitgesloten via een nieuwe, gedocumenteerde `EXCLUDED_CHUNK_IDS`-set in
  `build_orchard_rag.py` (zelfde "eerlijk gedocumenteerde uitsluiting"-discipline als
  `SKIP_FROM_RAG`, nu op chunk- i.p.v. documentniveau).
- Resultaat: kennisbank-index van 389 → 383 chunks na uitsluiting. Een hernieuwde retrieval-test
  op alle tien praktijkonderwerpen uit [G.16](#sec-g16) bevestigt geen regressie — elk onderwerp
  haalt nog steeds de juiste bron als nummer 1 resultaat op.

**Afhankelijkheid toegevoegd**: `pymupdf` (vervangt `pdfplumber` in `requirements.txt`),
`transformers`/`torch` nu ook expliciet vermeld (al transitief aanwezig via
`sentence-transformers`, nu ook rechtstreeks gebruikt door de kwaliteitscontrole).

<a id="sec-g18"></a>
## G.18 RAG-chunker vervangen door Auto Pilot's sectie/topic-boundary-aanpak + 200-probleem-kennisbank

**Aanleiding**: de gebruiker leverde een nieuw, eigen samengesteld kennisdocument aan
(`Data/Orchard/OrchardKnowledge/internet_crawl/Kersenteelt 100 problemen door het jaar
heen.md`, Jan Scholtes): **200 genummerde praktijkproblemen**, elk in een vast
Observatie/Actie/Gevolg/Waarom/Slechtste-reactie-format (zie [Deel F](#deel-f) #14, exact het
Observation-Action-Consequence-Why/Worst-case-patroon) met per-probleem bronvermelding en een
eerlijke "bevestigd"/"deels bevestigd"/"nog geen bron gevonden"-labeling per claim. Eerste
poging: dit document gewoon door de bestaande woordenteller-chunker (`CHUNK_MAX_WORDS=220`)
halen — **fout gebleken**, want de gebruiker wees er direct op: een los probleem komt soms net
boven de 220 woorden uit, waardoor de packer een probleem MIDDENIN zijn eigen tekst afkapte en
het vervolg (inclusief de bij dát probleem horende bronnenregel) in het VOLGENDE chunk
belandde — het risico dat een bron bij het verkeerde probleem komt te staan. De gebruiker was
hier scherp en terecht over: "dan hostaan de verkeerde bronnen bij de verkeerde problemen"
en gaf de opdracht niet een eigen, ad-hoc regex-fix te verzinnen, maar letterlijk Auto Pilot's
eigen, al-werkende chunker over te nemen.

**Volledige herbouw, gekopieerd van Auto Pilot (niet opnieuw ontworpen)**:
- `core/text_segmentation.py` uitgebreid met Auto Pilot's volledige topic-boundary-toolkit
  (near-verbatim overgenomen): `split_sentences()`, `cosine_similarities()`, `depth_scores()`
  (Hearst 1997 TextTiling, aangepast van bag-of-words naar zinsembeddings — dezelfde aanpak als
  LangChain's SemanticChunker/LlamaIndex's SemanticSplitterNodeParser/GraphSeg), `percentile()`,
  `semantic_split_sentence_indices()` (adaptieve percentiel-drempel + absolute
  minimum-depth-score om ruis op korte/eentonige teksten niet als "topic shift" te zien).
- `pipeline/ingest/parse_orchard_documents.py` volledig herzien: elk document levert nu een
  lijst **secties** (niet langer losse pagina's) — `{"section_id", "title", "type", "text",
  "pages"}`. PDF → één `"prose"`-sectie per pagina; HTML → één `"prose"`-sectie voor het hele
  document; Markdown → splitst eerst op `## `-koppen (groepsniveau), en detecteert BINNEN elke
  groep een genuine reeks genummerde `**N. Titel**`-items (minimaal 3 treffers, anders blijft
  het gewoon één `"prose"`-sectie — voorkomt dat een incidenteel vetgedrukt zinnetje verkeerd
  wordt herkend). Elk gevonden item wordt een eigen **STANDALONE**-sectie met `type="probleem"`
  — exact Auto Pilot's `STANDALONE_TYPES`-mechanisme (daar `"rule"`/`"chirp_report"`/
  `"moos_case"`), hier hernoemd naar het eigen domein.
- `pipeline/ingest/build_orchard_rag.py` volledig herschreven rond
  `pipeline.ingest.parse_orchard_documents.STANDALONE_SECTION_TYPES`: een `"prose"`-sectie mag
  eerst op topic-boundary gesplitst worden (`_split_section_by_topic`, nooit voor STANDALONE),
  dan indien nog te lang verder op zinsgrens (`_split_oversized_section`), en vervolgens worden
  kleine, verwante buursecties samengevoegd tot een token-budget
  (`CHUNK_TARGET_TOKENS=400`/`CHUNK_MAX_TOKENS=500`/`CHUNK_MIN_TOKENS=40`, Auto Pilot's eigen
  defaults overgenomen), geblokkeerd door een adaptieve ondergrens op de
  boundary-embedding-gelijkenis (`MERGE_FLOOR_PERCENTILE=25.0`) — maar een STANDALONE-sectie
  (`"probleem"`) wordt NOOIT gesplitst of samengevoegd, wat ook de vorm van zijn tekst is. Twee
  bewuste, gedocumenteerde vereenvoudigingen t.o.v. Auto Pilot: (1) geen "hoofdstukken"-laag
  (Orchard-documenten zijn niet hoofdstuk-gestructureerd — de adaptieve samenvoeg-drempel wordt
  over het hele document berekend, equivalent aan Auto Pilot's "één hoofdstuk"-geval), (2) geen
  keyword-topic-Jaccard-poort op samenvoegingen (Auto Pilot's domeinen hebben een opgebouwde
  concept-/topic-tagging-infrastructuur die dit project nog niet heeft, zie
  [Deel F](#deel-f) #16 — de adaptieve embedding-gelijkenis-drempel doet in de tussentijd al het
  meeste semantische-samenhang-werk).
- `pipeline/orchard_rag.py`: `format_context()`/`format_sources()` aangepast van een los
  `page_num`-veld naar een `pages`-lijst (een samengevoegd chunk kan nu over meerdere pagina's
  lopen) — rendert "p.2", "p.2-4" (aaneengesloten reeks) of "p.2, 5" (niet-aaneengesloten).

**Resultaat, geverifieerd**:
- Het 200-probleem-document levert nu **exact 201 chunks** (200 STANDALONE `"probleem"`-chunks
  + 1 `"prose"`-chunk voor de inleiding) — elk probleem precies ÉÉN chunk, met zijn EIGEN
  bronvermelding altijd correct erbij, nooit gesplitst of vermengd met een buurprobleem
  (automatisch geverifieerd: 0 van de 200 "probleem"-chunks bevat meer dan 1 sectie).
- Kennisbank-index van 383 → 644 chunks (22 documenten totaal, inclusief het nieuwe document).
- Hernieuwde perplexity-kwaliteitscontrole ([G.17](#sec-g17)) bevestigt: geen kolom-
  interleaving-garbage meer aanwezig; de resterende hoogst-scorende chunks zijn nu losse, korte
  maar grammaticaal correcte zinsfragmenten (een bekende, acceptabele makke van perplexiteit-
  op-korte-tekst, geen inhoudelijke fout) — 12 extra, zuiver-ruis HTML-chrome-chunks (cookie-
  banners, winkelwagen-besturing, fruit-categorie-navigatiemenu's, opnieuw gevonden met de
  nieuwe chunk-id's) expliciet uitgesloten via `EXCLUDED_CHUNK_IDS`.
- Een volledige end-to-end test (`ask_orchard_advisor()` op "Mijn perceel ligt in een
  vorstgat...") retourneerde een correct, groen-gegrond antwoord dat letterlijk de juiste
  bronnen van probleem #1 citeerde (NIAB/Alabama Extension/Michigan State) — bevestigt de hele
  keten (parsen → sectie-structuur → STANDALONE-chunking → retrieval → promptopbouw → antwoord)
  werkt zoals bedoeld.
- Herhaalde retrieval-test op alle tien oorspronkelijke praktijkonderwerpen ([G.16](#sec-g16))
  bevestigt geen regressie — elk onderwerp scoort nog steeds (sterk) positief met de juiste
  bron, en drie extra, zeer specifieke testvragen uit het nieuwe document ("perceel ligt in een
  vorstgat", "stikstoftekort", "wortelknobbel agrobacterium") scoren alle drie de juiste,
  exacte probleem-chunk als nummer 1 resultaat.
- Testsuite uitgebreid: `tests/test_build_orchard_rag.py` volledig herschreven (fake-embedder-
  patroon, zelfde techniek als Auto Pilot's eigen `test_build_rag_chunking.py`, geen echt model
  nodig in de geautomatiseerde suite), nieuw `tests/test_parse_orchard_documents.py` voor de
  markdown-structuurdetectie. 184 tests totaal, allemaal groen.

<a id="sec-g19"></a>
## G.19 Logboek-scans niet zichtbaar op de pod: absoluut pad gefixt + Verifiëren-pagina heractiveerd

**Twee gerelateerde, maar los opgeloste problemen** rond de Logboek Verifiëren-pagina
(zie ook [G.1](#sec-g1) voor de heractivatie van de pagina zelf op de publieke pod):

1. **De Verifiëren-pagina ontbrak in het menu op de pod** — bleek geen bug, maar de oorspronkelijke,
   bewuste "publieke demo is read-only"-keuze ([G.1](#sec-g1)/[G.13](#sec-g13)): het bestand stond
   als `_6_Logboek_Verifieren.py.disabled` (Streamlit negeert bestanden die met `_` beginnen) en de
   database was `chmod 444`. Op expliciet verzoek van de gebruiker heractiveerd (zie [G.1](#sec-g1)
   voor de precieze stappen en hoe terug te draaien).
2. **Nadat de pagina weer zichtbaar was, bleken de originele scan-afbeeldingen zelf niet te laden**
   op de pod (wel lokaal) — een apart, dieperliggend probleem. Oorzaak: de `image_path`-kolom in
   `orchard_logbook.db` bevat een ABSOLUUT pad dat ooit eenmalig is weggeschreven tijdens de
   OCR/vision-transcriptie-stap, altijd op Windows uitgevoerd (bv.
   `C:/Users/jcsch/Documents/Python/Orchard/Data/Orchard/OrchardLogbooks/_raw_page_images/
   jaar_2013/page_01.png`) — dat exacte pad lost alleen op DIE ene machine op. Twee aparte fixes
   nodig:
   - **Code**: nieuwe gedeelde helper `app/orchard_common.py::resolve_logbook_image_path()` --
     behoudt alleen het deel van het opgeslagen pad vanaf de `_raw_page_images`-marker en voegt
     dat weer samen onder DEZE machine's eigen `PATHS.logbooks_dir`, ongeacht Windows- (`\`) of
     POSIX-paden (`/`) in de opgeslagen string en ongeacht welke machine het pad oorspronkelijk
     wegschreef. Puur een lees-tijd-normalisatie, geen database-herbouw nodig. 5 nieuwe unit
     tests (`tests/test_orchard_common.py`).
   - **Data**: `Data/Orchard/OrchardLogbooks/_raw_page_images/` (39 MB, 179 bestanden) is
     GITIGNORED (eigen scans, zie [G.13](#sec-g13)) en stond daardoor realiter nog niet op de
     pod — alleen de database zelf was ooit gesynchroniseerd. Handmatig tar+scp'd, zelfde
     werkwijze als de database-sync zelf. **Les voor volgende keren**: een gitignored map wordt
     door geen enkel automatisch mechanisme gesignaleerd als "ontbreekt op de pod" — dit moet
     bij elke pod-sync expliciet gecontroleerd worden, niet aangenomen.
   - Geverifieerd met een screenshot op de publieke pod: de originele handgeschreven
     logboekpagina (jaar 2013, pagina 1) is nu daadwerkelijk zichtbaar.

<a id="sec-g20"></a>
## G.20 Menu-volgorde herschikt naar logische groepering

De sidebar-paginavolgorde (door Streamlit automatisch afgeleid uit het numerieke
bestandsnaam-voorvoegsel in `app/pages/`) volgde tot nu toe puur de chronologische
bouwvolgorde, niet een voor de teler logische gebruiksvolgorde. Op verzoek van de gebruiker
herschikt naar een functionele groepering — **alleen bestanden hernoemd** (`git mv`, geschiedenis
behouden), geen URL's veranderen (Streamlit's pagina-URL is de bestandsnaam ZONDER het
numerieke voorvoegsel, dus bestaande links/bookmarks blijven werken):

1. Boomgaard Dashboard — status in één oogopslag (sinds 2026-10-10 onderaan ook de **waterbalans**: delta per dag, bodemvocht, te droog/te nat, zie [G.29](#sec-g29))
2. Waarschuwingen — directe vervolgvraag op de status ("en wat moet ik NU doen?")
3. Vraag de Adviseur — interactief
4. Seizoensplanning — kalenderreferentie
5. Logboek — eigen geschiedenis doorzoeken
6. Logboek Verifiëren — correctie, hoort direct bij Logboek
7. Patroonherkenning — afgeleide analyse over het logboek
8. Gebruik van Middelen — idem, andere invalshoek
9. Bibliotheek — externe kennisbank (referentie, geen eigen data)
10. Help — gebruikersdocumentatie
11. Instellingen — meta, bewust altijd onderaan (zelfde conventie als de meeste apps)

Geverifieerd: 189/189 tests, volledige 12-pagina AppTest-sweep, en een live check van de
daadwerkelijke sidebar-volgorde op de lokale server — klopt met bovenstaande lijst. Geen
code buiten de bestandsnamen zelf hoefde aangepast te worden (geen `st.page_link`/
`switch_page`-aanroepen die een vast pad-met-nummer verwachten).

<a id="sec-g21"></a>
## G.21 Inference-snelheid: migratie naar vLLM (AWQ), streaming, adaptieve thinking-budget

**Aanleiding**: de gebruiker vroeg hoe Qwen3-8B sneller én beter gemaakt kon worden. Vijf
concrete verbeteringen afgesproken en alle vijf doorgevoerd:

**1. vLLM i.p.v. `transformers.generate()`** — het grootste deel van het werk. Oorspronkelijk
voorstel was FP8-kwantisatie, maar de A30 is Ampere (compute capability 8.0) — geen native
FP8-tensor-cores; **AWQ 4-bit** (`Qwen/Qwen3-8B-AWQ`, officieel Qwen-kwant) is hier de juiste
keuze, bevestigd via vLLM's eigen Marlin-kernel-ondersteuning.

**Python-versie/CUDA-blokkade, grondig uitgezocht vóór een workaround**: vLLM ondersteunt
Python 3.13 pas vanaf v0.20.0 — maar diezelfde release schakelde het standaard PyPI-wheel om
naar CUDA 13.0-binaries. De pod-driver (570.133.07) initialiseert CUDA 13 niet
("driver is too old"), **hard geverifieerd** (niet aangenomen): zelfs met de juiste
bibliotheekpaden (`libcudart.so.13` wél vindbaar) weigerde `torch.cuda` te initialiseren.
Onderzochte en afgewezen alternatieven, in volgorde:
- NVIDIA's `cuda-compat-13`-forward-compatibility-pakket — bestaat niet voor Ubuntu 20.04 in
  NVIDIA's eigen repo (stopt bij `cuda-compat-12-9`).
- Driver-upgrade via NVIDIA's officiële Ubuntu-20.04-apt-repo — biedt maximaal driver
  575.57.08, en die ondersteunt bevestigd (NVIDIA's eigen release notes) nog steeds alleen
  CUDA 12.x, niet 13.0. Driver 580 (wél CUDA 13) staat niet in die repo; alleen via een losse
  `.run`-installer buiten apt om, op een EOL-distro — als risico te groot beoordeeld en niet
  uitgevoerd (geen kernelmodule/driver-wijziging op de pod).
- Overstappen naar een andere LeafCloud-GPU (A100/H100/RTX 6000 Blackwell gecheckt via
  `leaf.cloud/products/gpu`) — zou het probleem structureel oplossen (nieuwere GPU-generaties
  komen met een moderne driver), maar betekent een volledig nieuwe pod: nieuw IP (de huidige
  publieke URL `45-135-57-59.sslip.io` IS het huidige pod-IP), volledige herimplementatie, en
  3-5× hogere kosten voor een model dat ruim in 24 GB past. In overleg met de gebruiker
  afgewezen; **blijft wel een optie voor later** als de training-fase (Deel E stap 5/7) toch
  een grotere GPU nodig heeft.
- **Gekozen oplossing**: één losse `.venv-vllm` (Python 3.12, `vllm==0.19.0` — de laatste
  release vóór de CUDA-13-omschakeling) specifiek voor déze systemd-service
  (`cloud/qwen_inference_server.py`'s eigen ExecStart), naast de normale, projectbrede
  `.venv` (Python 3.13) die ongewijzigd blijft voor app/tests/trainingspijplijn. Zie
  `cloud/qwen_inference_server.py`'s eigen docstring voor de exacte heropbouwstappen.

**Herbouw**: `cloud/qwen_inference_server.py` volledig herschreven rond vLLM's
`AsyncLLM`/`AsyncEngineArgs` (`enable_prefix_caching=True` — scheelt vooral bij het
steeds-identieke systeemprompt+tool-catalogus), met een kleine `_EngineLoop`-brug (eigen
asyncio-event-loop-thread) om vLLM's async-native engine te laten samenwerken met de
bestaande synchrone `http.server`-opzet (bewust geen nieuwe dependency zoals FastAPI
toegevoegd — zelfde "stdlib-only waar mogelijk"-conventie als de rest van dit project). De
`weights`-contractsemantiek van `core/qwen_loader.py` (ongewijzigd gelaten, nog nodig voor
toekomstige QLoRA-training) is zo goed mogelijk overgenomen (`"W0_base"`/`"MERGED:<dir>"`),
met één bewuste vereenvoudiging: vLLM's LoRA-ondersteuning bedient één actieve adapter per
request, geen PEFT-stijl sequentiële merge-keten van meerdere adapters — niet relevant
zolang er nog geen getrainde adapter bestaat (Deel E stap 5/7 nog niet gestart), expliciet
gedocumenteerd als toekomstig aandachtspunt i.p.v. stilzwijgend iets anders te doen.

**Gemeten resultaat** (A30, steady-state na eerste model-load): **~108 tokens/s**, tegen
een sterk prefix-cache-voordeel bij herhaalde identieke prompts (eerste aanroep inclusief
engine-opbouw ~45s, erna binnen 1-5s voor 150-500 tokens) — een orde van grootte sneller dan
de oude bitsandbytes-NF4-transformers-route.

**2. Streaming naar Streamlit** — `cloud/qwen_inference_server.py` kreeg een nieuwe
`/generate_stream`-endpoint (newline-delimited JSON over een close-delimited HTTP-respons,
bewust geen handmatige HTTP-chunked-encoding-framing — eenvoudiger en net zo robuust).
`pipeline/qwen_remote.py::stream_remote()` is de client-kant. `pipeline/orchard_agent.py`
kreeg een streaming-tweeling `ask_orchard_advisor_stream()` (+ `StreamingAdvisorAnswer`,
`_stream_hop()`): tussentijdse ReACT-tool-hops worden NIET gestreamd (de volledige tekst is
meteen nodig om een tool-call-JSON te herkennen), maar zodra een hop zich niet als tool-call
gedraagt en het `<think>`-blok gesloten is, streamt de rest van die hop live naar de
gebruiker. De ruwe `<think>`-inhoud zelf wordt nooit live getoond (blijft voorbehouden aan de
inklapbare "Redenering"-sectie, zoals voorheen). `app/pages/3_Vraag_de_Adviseur.py` gebruikt
nu `st.write_stream()` voor het LLM-pad; de deterministische tool-routes (vorst/regen/
koude-uren/...) blijven ongewijzigd instant (geen streaming nodig, was al <1s).

**3. Idle-unload-timeout verhoogd** — van 180s naar standaard **300s (5 minuten)**,
instelbaar via `ORCHARD_QWEN_IDLE_UNLOAD_S` (0 = volledig uit). AWQ-gewichten + KV-cache
passen ruim naast de rest op de A30 (24 GB), dus een langere drempel voorkomt onnodige
koude starts tijdens een lopend gesprek zonder de GPU blijvend bezet te houden.

**4. Adaptieve thinking-budget** — `pipeline/orchard_agent.py::_needs_deep_thinking()`, een
simpele, expliciet NIET-veiligheidskritische heuristiek (woordaantal + markers als "en",
"rekening houdend", "waarom"): een korte, enkelvoudige vraag die net niet door de
Streamlit-pagina's eigen keyword-router werd opgevangen krijgt `enable_thinking=False`
(Qwen3's snellere, non-thinking modus), een echte meerfactor-adviesvraag krijgt
`enable_thinking=True`. Na de EERSTE tool-aanroep wordt het token-budget voor volgende hops
gehalveerd (`_POST_TOOL_MIN_TOKENS`-ondergrens) — het model synthetiseert dan een antwoord
uit al aangeleverde feiten, geen nieuwe verkenning nodig.

**5. Sampling-parameters herzien** — de oude `do_sample=False` (greedy decoding) +
`repetition_penalty=1.15`-noodgreep vervangen door Qwen's eigen officieel aanbevolen
sampling (bevestigd via Qwen's model card): **thinking-modus** temperature=0.6/top_p=0.95/
top_k=20/repetition_penalty=1.0, **non-thinking-modus** temperature=0.7/top_p=0.8/top_k=20/
repetition_penalty=1.0 — greedy decoding wordt door Qwen zelf afgeraden voor Qwen3 (kan de
`<think>`-modus laten vastlopen/herhalen, precies het symptoom dat de oude
`repetition_penalty=1.15`-noodgreep probeerde te maskeren). Elke parameter blijft
per-aanroep overschrijfbaar (`pipeline/qwen_remote.py`'s `**sampling`-doorgave) voor een
toekomstige kwaliteitsevaluatie tegen een gouden eval-set (Deel E stap 9, nog open).

**Geverifieerd, niet alleen gebouwd**: live getest op de echte pod (systemd-herstart-cyclus,
`/health`/`/status`/`/generate`/`/generate_stream` via curl) EN end-to-end vanaf de laptop via
de SSH-tunnel (`ask_orchard_advisor_stream()` tegen de echte server, twee vragen met
verschillende complexiteit) — streaming leverde correct 71-112 losse tekstfragmenten op,
en `assess_grounding()` ving daarbij terecht een geval op waarin het model een
"Bronnen:"-regel verzon zonder een echte tool aan te roepen (bestaand, gedocumenteerd
basismodel-gedrag — geen regressie, zie Deel F #12). 198/198 tests groen, inclusief een
nieuwe `tests/test_vraag_de_adviseur_page.py`-AppTest-smoke-check (eerste voor deze pagina)
en nieuwe unit tests voor `_needs_deep_thinking()`/`_build_payload()`.

<a id="sec-g22"></a>
## G.22 Gouden eval-set + meetharnas en de eerste baseline

**Waarom eerst dit**: zonder meting is verbeteren gokken (Deel E stap 9, volgorde in de roadmap:
eerst eval, dan logboek-RAG, dan hybride retrieval/KG, dan SFT/DPO).

- **Gouden set** `Data/Orchard/Orchard_Eval/orchard_gold_qa.json` (GETRACKT, held-out: nooit voor
  training of prompt-afstelling): 83 vragen — 69 `kennisbank` (parafrasen van 69 van de 200
  genummerde problemen, met verwachte bron `doc_id#probleemnr` en kernfeiten), 10 `praktijk` (de
  tien klassieke kersenteelt-problemen, meerdere geldige bronnen) en 4 `guardrail` (mag GEEN
  concrete dosering noemen, moet naar Ctgb/etiket verwijzen). Logboek-vragen komen pas na
  logboek-RAG (Deel F #19) — het logboek is lokaal-only. Kernfeiten zijn alternatieven-lijsten van
  accentloze subtekenreeksen; `validate_gold()` controleert dat elke verwachte bron bestaat én dat elk
  kernfeit letterlijk in het verwachte bronfragment staat (de set kan dus geen feiten eisen die de bron
  niet bevat).
- **Harnas** `pipeline/orchard_eval.py` (+ CLI `pipeline/run_orchard_eval.py`): retrieval hit@k/MRR
  (per categorie), gemiste vragen met top-docs, antwoord-metrics (grounding-%, feitendekking,
  guardrail-slagingspercentage, dosering-overtredingen) en latency (gem./p50/p95). Matching is
  lexicaal (eerlijke ondergrens, geen LLM-rechter). Ablaties: `--no-rerank`, `--no-rag`.
  Resultaten in `Orchard_Eval/_runs/` (gitignored).
- **Baseline oude index (644 chunks), retrieval, 79 vragen met bron**:

  | Configuratie | hit@1 | hit@3 | hit@6 | MRR | latency/vraag |
  |---|---|---|---|---|---|
  | dense + cross-encoder-rerank (huidige instelling) | 77% | 81% | 87% | 0,81 | 3,8 s (CPU) |
  | alleen dense | 46% | 58% | 62% | 0,52 | 0,03 s |

  De reranker doet dus het zware werk; zonder hem mist dense retrieval een derde van de vragen —
  consistent met de 128-token-afkapping van de embedder (Deel F #21). Gemiste vragen met reranker: o.a.
  laagte/vorstgat, snoeitijd, spreeuwen, wachttijd, mestregels, residu-rapport, biologisch omschakelen.
  De antwoord-nulmeting (`--answers`, vraagt de Qwen-server) is nog niet gedraaid.

<a id="sec-g23"></a>
## G.23 Documenten → gestructureerde JSON → chunk-definitie in de JSON

**Aanleiding (gebruiker)**: de RAG-code was te simpel. Eis: documenten (PDF/HTML/MD/TXT) eerst naar
een GOEDE JSON met de structuur van het document, en de chunks daar al in definiëren op basis van die
structuur — pagina-breaks overslaan, tekst over twee pagina's in één chunk, GEEN gebroken chunks,
GEEN door elkaar lopende kolommen, GEEN tabellen of grafieken in chunks, GEEN chunks van vaste
lengte. Daarna RAG, KG én PG uit diezelfde JSON.

**Onderzoek in Auto Pilot** (`../Auto Pilot`): de OOW-/VHF-/Captain-/Chief-Engineer-parsers
(`build_oow_json.py`, `build_vhf_json.py`, `build_captain_json.py`, `build_chief_engineer_json.py`)
zetten elke bron om in `chapters → sections` (met `type`, `pages`, `concepts`) volgens de ECHTE
structuur (Part/Rule/Annex, kop-detectie op lettergrootte/bold), nooit een flush op een paginagrens
(pagina = metadata), de-hyphenation op elk tekst-assemblagepunt, en een STANDALONE-type (één regel/
één casus = één chunk) dat nooit gesplitst of samengevoegd wordt; pas daarna volgen `build_rag.py`,
`build_kg.py` en `build_pg.py`. Orchard had dat maar half overgenomen: PDF = nog steeds één sectie per
pagina, HTML = één sectie voor de hele pagina, geen koppen/tabellen/figuren.

**Gebouwd** (`pipeline/ingest/build_orchard_json.py` + pure `orchard_structure.py`; vervangt
`parse_orchard_documents.py`):
- **Extractors → blokken** (heading/paragraph/list_item/caption/table/figure): PDF via PyMuPDF (niet
  pdfplumber) met inhoudsstroom-volgorde, tabellen via `find_tables()`, figuren via afbeeldingen/
  vector-clusters (volledige-pagina-scan-achtergrond telt niet), kop-detectie op BLOK-niveau
  (lettergrootte t.o.v. de echte lopende-tekstgrootte, bold, bold run-in labels als "Probleem …"),
  OCR-boeken (de gescande USDA-handbook, lettergroottes zijn ruis) via HOOFDLETTER-koppen,
  lopende kop-/voetteksten fuzzy herkend en weggehaald, Symbol-font-bullets/zachte koppeltekens
  genormaliseerd; HTML via semantische tags (h1–h6/p/li/table/figure), navigatie-/cookie-/link-lijsten
  weg; Markdown via koppen + de genummerde `**N. Titel**`-kaarten (STANDALONE `probleem`). Het manifest-
  `file_path` is een absoluut pad van de acquisitie-machine en wordt per machine opnieuw geroot
  (`resolve_source_path`, dezelfde les als `resolve_logbook_image_path`).
- **Structuur (`orchard_structure.py`)**: `merge_continuations` (alinea over kolom-/paginagrens = één
  alinea; tabellen/figuren ertussen zijn transparant), `build_sections` (koptree → secties met
  `heading_path`), `define_chunks`: een chunk is een STRUCTURELE eenheid (sectie/kaart), nooit een
  aantal woorden. Alleen stubs (< 30 woorden) worden samengevoegd met een broer onder dezelfde
  ouder, en alleen een sectie > 600 woorden wordt gesplitst — op topic-grens (Auto Pilot's
  Hearst/GraphSeg-methode, nu op alineaniveau) of anders op gebalanceerde alinea-grenzen.
- **Tabellen/figuren**: apart in `tables`/`figures` (bijschrift, sectie, pagina, rijen); chunks
  verwijzen er alleen naar met id. Nooit in chunktekst.
- **JSON-schema per document**: `chapters`, `sections` (met `blocks`), `tables`, `figures`, `chunks`
  (`text`, `text_with_context`, `heading_path`, `pages`, `table_ids`, vlaggen), `quality`,
  `parsing_notes`.

**Resultaat** (eindstand 2026-10-09): 472 chunks in 21 documenten (oude index: 644; elk document één of
meer échte structuur-eenheden), waarvan **416 door de QC** (ok 404 / warn 12), 18 afgekeurd en 38
bibliografie. De USDA-handbook ging van 256 → 144 chunks en het aantal chunks dat midden in een zin
begint van 55 → 1. Bij het controleren op de echte documenten zijn deze concrete oorzaken van kapotte
chunks herkend en in de parser opgelost:
- **Tekstgrootte-mediaan vertekend door kleine letters** (bijschriften, tabelcellen) → elke 11pt-regel leek
  een kop; nu wordt de lopende-tekstgrootte bepaald uit meerregelige alinea's buiten tabellen/figuren,
  en koppen worden op BLOK-niveau beoordeeld (kop-regels vóór niet-kop-regels).
- **OCR-regels met overlappende kaders** werden tot één regel samengevoegd ("ser- rulata") → samenvoegen
  alleen als het latere stuk rechts van het vorige aansluit.
- **Twee-koloms gescande pagina's**: de OCR-volgorde leest de bovenste helft van beide kolommen vóór de
  onderste helft van de linker → een zin van linksonder naar rechtsboven werd uit elkaar getrokken.
  Nu expliciete kolomvolgorde (volledige-breedte-/gootbrekende blokken splitsen de pagina in banden).
- **Figuurbijschriften** die midden in een alinea staan ("FIGURE 5.—…", ook als het bijschrift over
  meerdere OCR-blokken loopt of inline in een regel begint) → bijschrift-detectie op regel- en
  blokniveau; hun regels breken de omlopende alinea niet meer.
- **Voetnoten, foto-nummers (PN-3067), OCR-puntjes, tabellen in een gescand boek** (geen lijnen, dus geen
  `find_tables`): voetnoot-detectie, tabel-zones rond een "TABLE n"-bijschrift, junk-blok-filter.
- **Alinea die een andere alinea voortzet over tussenliggende voetnoten/bijschriften heen**:
  `merge_continuations` laat een kleine-letter-alinea aansluiten op de dichtstbijzijnde open alinea
  (binnen 8 blokken, nooit over een kop).
- **Drop-caps** ("T" + "he distribution"), **Wingdings-bullets**, **zachte koppeltekens**, **nul-breedte-
  tekens**, **regelafbrekingen met koppelteken** (Engels: "long-distance" blijft staan, "contin-ued"
  wordt "continued", via woordenboek), **bold run-in koppen** ("Probleem …").
- **Website-chroom**: commentaar-widgets, offerte-formulieren, "Terug"/"Lees meer", tag-wolken,
  template-placeholders, `<!doctype>`-resten, nieuws-/colofon-secties (QC-categorie `chrome`).
- **Ontbrekende punt** bij webtekst ("… voor nieuwe infecties"): alleen de punt wordt toegevoegd bij
  een afgeronde alinea (≥ 6 woorden, gevolgd door een nieuwe zin/kop), nooit woorden.
Nog open: gescande-boek-chunks met OCR-fouten en tabel-/kolomresten (zie Deel F #20) en de tabellen zelf
(bestuivingslijst, rassentabel, onderstammen): die staan wel in `tables` maar niet als zinnen in de
index — een "tabel → zinnen"-stap is een voor de hand liggende vervolgstap.

<a id="sec-g24"></a>
## G.24 Chunk-kwaliteitscontrole (QC) als poort voor RAG/KG/PG + knop "Controleer RAG Chunks"

**Eis (gebruiker)**: in de context alleen keurige, complete, afgemaakte zinnen — geen afgebroken
zinnen, losse tekstfragmenten, tabellen, grafieken, OCR-fouten of pagina-/kolomresten; detecteren en
inbouwen als QC.

**`pipeline/ingest/orchard_qc.py`** geeft elke chunk `chunk["qc"] = {verdict, reasons, issues,
scores}`: `ok` / `warn` (wel geïndexeerd) / `fail` / `references` (bibliografie; niet geïndexeerd).
Signalen: zinsstructuur (aandeel woorden in complete zinnen; een chunk mag ALLEEN complete zinnen
bevatten — begin/einde midden in een zin, onvolledige zin, dwaal-fragmenten = fail), tabel-/cijferdichtheid,
korte fragmenten, lexicale ruis (onbekende woorden t.o.v. woordenboek + vaktermen/namen/herhaling in
het corpus + Nederlandse samenstellingen; onmogelijke tekens zoals `ñ` in Engelse woorden),
bibliografie-score, taalmatigheid, afbreek-restanten ("regen- kappen"), herhaalde pagina-kopteksten,
en optioneel (`--lm`, ± 4 min CPU) per-zin taalmodel-loss (GPT-2 NL/EN; robuuste outlier via
mediaan/MAD) voor door elkaar lopende kolommen. Zinsdetectie kent afkortingen/initialen (spp., vs.,
M. laxa, et al.) en laat een zin die met een kleine letter begint bewust NIET aan de vorige vastplakken
(dat ís hoe een chunk-/paginagrens door een zin eruitziet). Handmatig overrulen: `Data/Orchard/
orchard_qc_overrides.json` per `chunk_id` (hash van de tekst → verloopt vanzelf bij tekstwijziging).

**OCR-correctie met next-word prediction — bewust NIET gedaan.** Gemeten op de USDA-handbook: 5,6% van
de woorden is "onbekend", maar vrijwel alles daarvan is legitiem (vaktermen als Mahaleb/pollinizer,
namen als Bing/Lewelling, bibliografie-afkortingen); een taalmodel dat "corrigeert" zou juist
goede termen/doseringen kapot maken. Daarom: breed DETECTEREN, hooguit later conservatief corrigeren
met audit-spoor (`text_raw`).

**Repair-stap** (`--repair`, standaard bij het bouwen uit de JSON): verwijdert uitsluitend wat geen
volledige zin is aan de RANDEN van een chunk (leidende voortzetting met kleine letter, afgebroken
slotzin) en losse labelfragmenten ("Terug", "Lees meer"). Er wordt niets herschreven of geraden; het
origineel staat in `text_raw`, de weggehaalde stukken in `repairs`.

**Beleid — één poort voor alles**: RAG, KG én PG worden uitsluitend gebouwd uit chunks met oordeel
`ok`/`warn` (`orchard_qc.indexable()`), zodat ook de grafen automatisch schoon zijn. Kapotte teksten
blijven in de JSON voor een volgende reparatieronde (Deel F #20); wat dan slaagt doet vanzelf mee.

**Knop** op de Instellingen-pagina: "Controleer RAG Chunks" draait de QC over alle chunks van de
LIVE index (`qc_rag_index()`; ook de oude layout met `section_titles`/`types`) en toont totalen,
probleemtypes, per-document-tabel, elke problematische chunk met begin/einde, plus downloads (.md/.csv);
vinkje voor de taalmodel-stage. `pyspellchecker` staat in `requirements.txt` (ook op de pod nodig).
AppTest-smoke-check + 12 unit-tests (213 tests totaal, groen).

**Metingen**: oude live index (644 chunks, met LM-stage): ok 310 / warn 23 / fail 266 / bibliografie 45
(207 chunks met onvolledige zinnen, 205 met begin/einde midden in een zin, 45 tabel/cijferdata,
10 OCR-ruis, 2 door elkaar lopende kolommen). Nieuwe JSON na de parser-fixes van [G.23](#sec-g23)
(472 chunks, met LM-stage en repair): ok 404 / warn 12 / fail 18 / bibliografie 38. De 18 fails zijn
vrijwel allemaal terecht: voorwerk/inhoudsopgave van de handbook, colofons, productlijsten van een
webshop, tabellen. Van de woorden in geïndexeerde chunks is ± 3% weggehaald door de repair (vooral
OCR-beschadigde zinnen en losse bijschrift-/voetnootresten in de USDA-handbook); alles staat in
`text_raw`/`repairs`.

**Repair, uitgebreid**: naast randfragmenten haalt de repair nu ook (a) zinnen met ondubbelzinnige
OCR-schade weg (letters met een verdwaald symbool erin zoals `developn^ent`, of onmogelijke letters
zoals `ñ` in een Engels woord) en (b) kapotte zinnen midden in een chunk zolang die een minderheid zijn
(≤ 30%). Een "ver van een woordenboek-woord"-regel is bewust UIT: die raakt in een tuinbouwboek ook
correcte vaktermen (disked, rotovated, Latijnse soortnamen). QC is idempotent (`reset_repairs`: de repair
begint altijd bij de tekst zoals de parser hem gaf).

**Status**: de oude RAG-index is op verzoek van de gebruiker verwijderd en opnieuw gebouwd uit de
QC-geslaagde JSON-chunks, zie [G.25](#sec-g25). KG (`build_kg.py`-port met aliassen als hagelschot →
Stigmina carpophila) en PG (procedurestappen uit de Observatie/Actie-kaarten) volgen en gebruiken
dezelfde geslaagde chunks (`build_orchard_rag.load_indexable_chunks()` is de gedeelde ingang).
`parse_orchard_documents.py`, `check_rag_chunk_quality.py` (vervangen door `orchard_qc.py`) en hun tests
zijn verwijderd.

<a id="sec-g25"></a>
## G.25 RAG herbouwd uit de gestructureerde JSON: bge-m3, geen reranker

**`pipeline/ingest/build_orchard_rag.py` herschreven**: doet zelf geen chunking meer; neemt alle chunks uit
`Orchard_JSON/*.json` met QC-oordeel ok/warn, embedt `text_with_context` ("Bron: …\nSectie: …\n\ntekst",
zodat een genummerde kaart op zijn titel gevonden wordt) en schrijft naast chunks/embeddings/ids ook
`orchard_rag_meta.json` (embedder, `max_seq_length`, prefixes) — `orchard_rag.load_index()` gebruikt exact
dezelfde embedder. `format_context()` toont nu ook de sectie ("sectie: Groep > 21. Nachtvorst …"), want de
kaarttitel zit niet meer in de zinnen zelf. 240 tests groen (nieuw: `test_build_orchard_rag.py`,
`test_orchard_structure.py`, `test_build_orchard_json.py`, uitgebreid `test_orchard_qc.py`).

**Embedder- en reranker-keuze, gemeten met de gouden set van [G.22](#sec-g22)** (79 vragen met bron):

| Configuratie | hit@1 | hit@6 | MRR | latency/vraag |
|---|---|---|---|---|
| OUDE index (644 chunks), mpnet + rerank | 77% | 87% | 0,81 | 3,8 s |
| OUDE index, alleen dense | 46% | 62% | 0,52 | 0,03 s |
| NIEUWE index (416 chunks), mpnet (128 tokens) + rerank | 65% | 75% | 0,69 | 5,1 s |
| NIEUWE index, **bge-m3 (512 tokens), alleen dense** — gekozen | **89%** | **95%** | **0,92** | **0,07 s** |
| NIEUWE index, bge-m3 + rerank | 82% | 92% | 0,87 | 3,6 s |

Conclusies: (1) met de oude embedder werd de nieuwe, rijkere chunk-tekst juist slechter gevonden (de
contextregel eet een deel van het 128-tokenvenster op) — dat is Deel F #21; (2) met bge-m3 haalt de
nieuwe structuur-index de beste score tot nu toe, zonder reranker; (3) de stock-cross-encoder
(mmarco-mMiniLM) **verslechtert** de resultaten én kost 3,5 s per vraag, dus staat standaard uit
(`load_index(use_reranker=False)`, `run_orchard_eval --rerank` als ablatie). Eerlijke kanttekening: de
gouden set is hier gebruikt om de configuratie te kiezen; voor een onafhankelijke meting later een
tweede, nog nooit gebruikte set (bv. met de logboek-vragen) toevoegen. Op de pod moet bge-m3 (± 2,2 GB)
eenmalig gedownload worden.

<a id="sec-g26"></a>
## G.26 Procedure: hoe we RAG bouwen en QC doen, en de Code Library

**Procedure (volgorde is bindend)**
1. `python -m pipeline.ingest.build_orchard_json` — bronnen (`OrchardKnowledge/` + manifest) → `Orchard_JSON/*.json`
   (structuur, chunks, tabellen/figuren apart; zie [G.23](#sec-g23)).
2. `python -m pipeline.ingest.orchard_qc [--lm]` (of de knop "Controleer RAG Chunks") — QC met repair (alleen weghalen);
   elke chunk krijgt `ok`/`warn`/`fail`/`references` ([G.24](#sec-g24)).
3. `python -m pipeline.ingest.build_orchard_rag` — index uit `load_indexable_chunks()` (alleen `ok`/`warn`), bge-m3 op
   `text_with_context` ([G.25](#sec-g25)). KG en PG gebruiken dezelfde `load_indexable_chunks()`.
4. `python -m pipeline.run_orchard_eval` — meten tegen de gouden set ([G.22](#sec-g22)); pas daarna conclusies trekken.
Altijd de JSON **opnieuw bouwen** vóór je een QC-uitkomst beoordeelt (repairs staan in de JSON). Na elke nieuwe bron:
een steekproef van de geparste tekst lezen. Gefaalde chunks blijven in de JSON; verbetert de parser, dan doen ze vanzelf mee.

**Code Library** (`C:\Users\jcsch\Documents\Python\Code Library`): de parsing- en QC-procedure is generiek gemaakt en daar
ondergebracht, mét tests en een volledige handleiding:
- `Parsing2JSON\parsing2json\` — PDF (PyMuPDF, nooit pdfplumber/`sort=True`), DOCX, HTML, Markdown, TXT, XML, EPUB, CSV/XLSX → JSON.
- `QC\doc_qc\` — signalen, oordelen, repair, perplexity-stage, OCR-diagnostiek (tekstlaag, next-character-model, verwarbare tekens).
- `Docs\Parsing2JSON_en_QC.md` — principes, JSON-schema, per-formaat-aanpak, pagina-scheidingen, normalisatie, OCR-detectie en
  -correctie (en waarom niet automatisch corrigeren), een catalogus van 67 valkuilen, werkwijze en Orchard-metingen.
Validatie van de port: dezelfde bronnen geven met `make_topic_splitter` exact Orchard's 184 USDA-chunks; 44 + 36 tests groen.
Orchard zelf gebruikt voorlopig nog zijn eigen modules (`build_orchard_json.py`, `orchard_qc.py`); het is een bewuste vervolgstap om
die op de library te laten leunen als die in een eigen repo/pakket staat.

<a id="sec-g27"></a>
## G.27 KG, PG, OAC, logboek-RAG, trainingsdata, antwoord-eval en analyse (2026-10-10)

Deploy-status: de RAG-herbouw is gecommit/gepusht (6478791) en op de pod gezet (tar-sync, geen git-repo daar; bge-m3 gedownload,
`pyspellchecker` geïnstalleerd, `orchard-streamlit` herstart; de knop "Controleer RAG Chunks" draait op de pod: 407 ok / 9 warn).
Daarna kwamen KG, PG, OAC, logboek-RAG en trainingsdata erbij (hieronder), eveneens op de pod gezet — behalve alles wat logboekdata is.

**1. Kennisgraaf + hybride retrieval** (`pipeline/orchard_concepts.py`, `orchard_kg.py`, `ingest/build_orchard_kg.py`; port van Auto Pilot's
`build_kg.py`). Deterministisch lexicon van 70 concepten (ziekten, plagen, klimaat, bodem/bemesting, snoei, onderstammen, rassen, regelgeving,
met NL/EN/Latijnse aliassen en spreektaal: "bronskleurig + webjes" → spint, "noteren bij bespuiting" → spuitregistratie). Gebouwd uit dezelfde
416 QC-geslaagde chunks (65/70 concepten gebruikt, gem. 4,2 concepten/chunk, 9 chunks zonder concept). `retrieve_hybrid` = dense cosine +
concept-boost (× IDF-gewicht, × 1,5 bij concept in de titel, + kleine co-occurrence-boost). `retrieve()` is nu standaard hybride zodra de index
een KG heeft; een verouderde KG (andere chunk-ids) wordt genegeerd.

| Retrieval, gouden set (79 vragen met bron) | hit@1 | hit@3 | hit@6 | hit@10 | MRR |
|---|---|---|---|---|---|
| dense (G.25) | 89% | 95% | 95% | 99% | 0,92 |
| **hybride (KG), concept-boost 0,10** | **91%** | **97%** | **100%** | **100%** | **0,95** |
| (boost 0,05: gelijk; boost 0,20: hit@1 87%) | | | | | |
| Onafhankelijke synthetische set (200 observatie-regels → kaart), dense | 98% | 98% | 100% | 100% | 0,98 |
| idem, hybride | 97% | 99% | 100% | 100% | 0,98 |

Twee bevindingen. (a) **De per-document-cap (3 per bron) knelde juist het kaartendocument af**: de 200 kaarten zijn 200 losse antwoorden in
één bestand; de goede kaart stond voor 2 van 79 vragen op rank 5–6 en viel eraf. Kaarten (`type == "probleem"`) zijn nu van de cap vrijgesteld
(proza houdt cap 3). (b) **Eerlijk**: de gouden set is ook gebruikt om de cap en enkele aliassen te kiezen (kb024 is na het toevoegen van de
spint-aliassen opgelost), dus de stap 95% → 100% is gedeeltelijk in-sample. Op de onafhankelijke observatie-set (lexicaal makkelijk) doet
hybride niets extra's maar ook geen kwaad. De KG helpt dus vooral bij vocabulaire-gaten; voor een zuivere meting is een nieuwe, nooit gebruikte
set nodig (zie stap 8).

**2. OAC-extractie** (`ingest/extract_orchard_oac.py`, Deel F #14): de 200 "100 problemen"-kaarten hebben de OAC-structuur al (Observatie /
Actie / Gevolg / Waarom / Slechtste reactie / Bronnen) — voor deze bron is "extractie" een deterministische parse, elk veld een letterlijk stuk
van de chunk: 200/200 kaarten geparsed, 198 met ≥ 2 actiestappen. **Verificatiestatus van de kaarten**: 74 "bevestigd", 63 "deels
bevestigd", 1 "bevestigd voor spint", **62 "nog geen bron gevonden"** — dat laatste mag niet ongezien in training (zie 5). De prozachunks
(USDA-handbook, webpagina's) hebben geen OAC-structuur; daarvoor is een LLM-extractie met verificatie nodig (nog niet gedaan).

**3. Procedurele graaf** (`orchard_pg.py`, `ingest/build_orchard_pg.py`; port van `build_pg.py`): stappen uit de Actie-regel (zinnen → `;` → komma's),
canonicalisatie met bge-m3 (cos ≥ 0,893, nooit samenvoegen bij verschillende getallen of ontkenning), NEXT-edges met `condition` ← Observatie,
`guidance` ← Waarom, `pitfalls` ← Slechtste reactie, support-telling. Resultaat: 198 traces, 634 stappen → 611 nodes (23 samengevoegd), 435 edges,
**slechts 1 edge met support > 1**. Conclusie: elke kaart is een eigen procedure; de PG voegt boven op de kaarten zelf weinig toe zolang er geen
andere bronnen (prozatraces) en geen logboek-procedures in zitten. Hij is gebouwd en getest (`next_steps`, `nearest_node`, `sample_path`) maar nog
niet in de agent geschakeld — bewust, tot er meer-bron-support is.

**4. Logboek als RAG-bron** (`orchard_logbook_rag.py`, Deel F #19): hybride (harde tijdsfilter op "11 mei 2013" / "mei 2013" / "2019", lexicaal
op middelnaam en opmerking, dense als tiebreak), elk fragment gelabeld met datum en "[onzeker gelezen handschrift]" / "[nog niet geverifieerd]".
**Lokaal-only**: de tool `logboek_zoeken` en de upfront-retrieval voor "eigen historie"-vragen bestaan alleen met `ORCHARD_LOGBOOK_RAG=1`
(NIET gezet op de pod; het logboek lekt dus niet via de publieke chat). Meting op 598 synthetische vragen uit het logboek zelf: dag 100%,
maand 100%, "tegen X" 90% (de rest is ambigu: meerdere regels noemen hetzelfde doel). Live gecontroleerd met Qwen (op drie typen vragen: één dag, één maand, een datum zonder regel): het model citeert de juiste regels uit het
logboek en meldt bij een datum zonder regel "staat niet in het logboek, dichtstbijzijnde regel is ..." (de concrete antwoorden staan bewust
niet in dit document: het zijn bedrijfsgegevens).
Het model riep de tool zelf niet aan (kennisbank-upfront volstond in zijn ogen), vandaar de deterministische upfront-retrieval.

**5. Trainingsdata** (`ingest/build_orchard_training_data.py`; alleen data, er is niets getraind). Uit de kaarten, deterministisch:
`sft_cards` (vraag = observatie of probleemtitel, context = wat de live retriever teruggeeft, antwoord = Actie + Effect + Waarom + Vermijd +
"Bronnen"), `dpo_cards` (chosen = dat antwoord, rejected = de "Slechtste reactie" van de kaart zelf als advies — een door de bron gedocumenteerd
fout antwoord, geen synthetische negatieven), `reflection_cards` (draft = slechtste reactie → critique = het Waarom → revisie = antwoord).
Beveiligingen: **72 kaarten zijn uitgesloten omdat de gouden set ze als bron verwacht** (nooit op de eval-set trainen; ook de synthetische
observatie-set is dus ongeldig na training op die kaarten), 1 kaart noemt een dosering (uitgesloten), 3 niet terug te vinden door de retriever,
62 "nog geen bron gevonden"-kaarten staan in een apart `*_unverified`-bestand. Resultaat: **145 verified SFT-/DPO-/Reflectie-voorbeelden**
(118 train / 27 val, split per kaart), 106 unverified. **Logboek (LOKAAL-ONLY, `LOCALONLY_*`)**: 467 open-book SFT-voorbeelden (retrieved
logboekregels in de prompt, antwoord citeert alleen die; incl. 40 "staat niet in je logboek"-voorbeelden); het logboek kent alleen acties en weer,
nooit uitkomsten, dus daar is geen DPO/Reflectie uit te halen. Van de 487 logboekregels zijn er **0 menselijk geverifieerd** en 163 als onzeker
gemarkeerd; 304 bruikbare regels → alles is `silver`. **Feedback**: de pod heeft 4 duim-records (3 omhoog, 1 omlaag, 0 paren per vraag) — dat is
nog geen DPO-materiaal (Deel F #11).

**6. Antwoord-evaluatie** (83 vragen, Qwen3-8B via de pod; sampling-ruis tussen runs ≈ ±5 pt, dus verschillen < 5 pt zijn niet significant):

| Configuratie | Grounding | Feitendekking gem. / volledig | Guardrail | Latency |
|---|---|---|---|---|
| geen kennisbank | 45% | 10% / 3% | 100% | 4,7 s |
| kennisbank + KG, 700 tokens, korte prompt | 98% | 82% / 65% | 75% (1 dosering-lek) | 4,4 s |
| idem, 700 tokens, "volledige" prompt | 83% | 87% / 75% | 100% | 5,5 s |
| korte prompt, 1500 tokens | 100% | 83% / 68% | 100% | 4,3 s |
| volledige prompt, 1500 tokens | 98% | 89% / 78% | 75% (geen Ctgb-verwijzing) | 6,2 s |
| **eindconfiguratie: volledige prompt + Ctgb-regel, 1500 tokens** | **98%** | **84% / 70%** | **100%** | **5,3 s** |

**7. Analyse en conclusies**
- **De kennisbank doet het werk**: zonder kennisbank 10% feitendekking en 45% grounding; met kennisbank 82–89% en 98–100%.
- **Het knelpunt zit in generatie, niet in retrieval**: van de 29 gemiste feiten (28 vragen) stond **elk** feit in de opgehaalde context.
  De antwoorden zijn te kort/selectief ("Antwoord kort"). Een "beknopt maar volledig"-prompt geeft +1…6 pt (binnen de ruis); de grote
  stap is niet met een prompt te halen → dit is waar SFT op de OAC-kaarten (antwoord uit ALLE relevante velden van het fragment) kan helpen.
- **Afkappen was een echt productie-defect**: met 700 nieuwe tokens (incl. thinking) werden antwoorden midden in een woord afgekapt vóór de
  "Bronnen:"-regel (10 van de 14 rode grounding-gevallen). Standaard `max_new_tokens` is nu 1500 (app én eval); effect op latency klein.
- **Compliance-lek gevonden en gefixt**: een in de bron staande productdosering ("5 liter per hectare, Vitalosol Gold") werd door het model
  herhaald voordat het naar Ctgb verwees. Fix volgens het deterministische-kern-principe: `redact_doses()` haalt per-oppervlak-doseringen uit
  de context (`format_context`); plus een promptregel (nooit een toelatingsstatus beweren, altijd naar Ctgb/etiket verwijzen). Guardrail 4/4,
  maar het zijn maar 4 vragen en de metriek is lexicaal: hij ving niet dat het model "Decis is niet toegelaten" beweerde (zonder basis).
- **Hybride retrieval**: +2…5 pt op de gouden set (deels in-sample), neutraal op de onafhankelijke set; goedkoop (0,1 s) en deterministisch.
- **PG** levert nog weinig (zie 3); **logboek-RAG** werkt en is veilig lokaal; **trainingsdata** is dun (145 verified kaart-voorbeelden) en
  het logboek is niet geverifieerd.

**8. Volgende stappen (in volgorde van verwachte waarde)**
1. **Meetbetrouwbaarheid**: elke antwoord-eval 3× draaien (of temperatuur vast) en rapporteren als gemiddelde ± spreiding; een nieuwe, nooit
   gebruikte held-out set (bv. 40 logboek- en 40 praktijkvragen) vóór er getraind wordt. Guardrail-set uitbreiden (4 → 20+) en een toelatingsstatus-
   claim als overtreding meetellen.
2. **Reward-functie ontwerpen (Deel F #17) — nu concreet te maken**: de onderdelen bestaan al deterministisch: feitendekking (sleutelwoorden uit
   de kaart-velden), grounding (citeert een aangeleverd fragment), compliance (geen dosering, wel Ctgb-verwijzing), afkap-straf, lengte-straf.
3. **SFT-ronde 1 (QLoRA, op de pod)** op `sft_cards_train` (118) met `sft_cards_val` als stop-criterium, evalueren op de gouden set (de 72 kaarten
   zijn uitgesloten, dus geen contaminatie). Verwachting eerlijk laag houden: 118 voorbeelden zijn weinig; doel is antwoord-volledigheid, geen kennis.
   Eerst de 62 "nog geen bron gevonden"-kaarten laten verifiëren (of per kaart zoeken) om de set te vergroten.
4. **Meer verified data zonder handwerk**: rejection sampling met de reward uit 2 (N antwoorden per niet-gold kaart, beste = chosen, slechtste =
   rejected) levert veel DPO-paren; plus LLM-extractie van OAC/procedures uit de prozachunks met letterlijke-span-verificatie (Deel F #14, vult ook de PG).
5. **Logboek eerst verifiëren** (Verifieren-pagina: 0/487 gedaan, 163 onzeker) vóór logboek-SFT of -analyse; daarna open-book SFT en patronen
   (bv. Observatie→Actie uit "Tegen X"-regels met weer als context). Het logboek heeft geen uitkomsten: voor Reflectie/DPO uit eigen data is een
   outcome-signaal nodig (oogst/schade per seizoen, Deel F #17).
6. **Duim-feedback** is te dun (4 records); verzamelen blijft aan, maar paren komen vooral uit stap 4.
7. Pod: de publieke app draait nu hybride + nieuwe prompt + 1500 tokens + dosering-redactie; de logboek-tool staat daar uit.

<a id="sec-g28"></a>
## G.28 Meetbetrouwbaarheid, held-out set, reward, rejection sampling en SFT-rondes (2026-10-10)

Dit voert de aanbevelingen van [G.27](#sec-g27) uit (volgorde: meting → held-out → reward → rejection sampling → SFT).

**1. Meetbetrouwbaarheid.** `run_orchard_eval --repeats N` draait de antwoordmeting N× (parallel) en rapporteert gemiddelde ± sd per maat
(`aggregate_answer_runs`); `--set gold|heldout|both`, `--weights <adapter>`, `--ids`, `--rep-penalty`. De baseline (basismodel, 114 vragen, 3×):
grounding 96,8 ± 1,3 %, feitendekking 86,8 ± 3,6 %, **volledig 74,1 ± 7,8 %**, guardrail 86,7 ± 7,6 %; 29% van de vragen geeft van run tot run een andere
feitendekking. Dus: verschillen onder ± 5–8 pt zijn ruis; alleen herhaalde runs tellen. Een mid-run wegvallende SSH-tunnel gaf 228 "fouten"
(ConnectionError) in één run; de client heeft nu keepalive en de eval verbindt opnieuw en herhaalt (2×).

**2. Held-out set v2** (`Orchard_Eval/orchard_heldout_qa.json`, committed): 15 inhoudsvragen over kaarten die NIET in de gouden set zitten en nooit
in trainingsdata komen (de bouwer sluit ze uit), in eigen formulering, plus 16 extra guardrail-vragen (doseringen, toelating, spuitschema's,
"hogere dosering dan op het etiket"). Guardrail-controle is uitgebreid met `DOSE`, `DOSE2` (per volume) en `CLAIM`: een ongekwalificeerde uitspraak dat een
middel (niet) is toegelaten — het advies kan dat niet weten (Ctgb-lookup is een gedocumenteerde stub); "ik kan niet zeggen of X is toegelaten" is
géén claim (voorbehoud-detectie per zin). Beperking: n = 15, en de controle heeft false positives (een antwoord dat de vraag letterlijk herhaalt,
"…welk middel is toegelaten…", wordt als claim gevlagd).

| Basismodel | gouden set (in-sample voor keuzes) | held-out v2 |
|---|---|---|
| feitendekking gem. / volledig | 88,8 / 77,6 % | **75,9 / 55,6 %** |
| guardrail | 91,7 % | 85,4 % |

De gouden set overschat dus het echte niveau (≈ 13 pt op dekking): alle conclusies uit [G.25](#sec-g25)/[G.27](#sec-g27) moeten tegen de held-out set gelezen worden.

**3. Reward-functie** (`pipeline/orchard_reward.py`, Deel F #17 — nu concreet): volledig deterministisch, geen model. `reward = gate × gewogen som` van
*coverage* (0,35; sleutelfeiten), *focus* (0,20; aandeel inhoudswoorden in het antwoord dat in de bronkaart of de vraag staat — straft meeslepen van
buurfragmenten), *grounding* (0,10; "Bronnen:"-regel), *numeric* (0,15; getallen in het antwoord die ook in vraag/context staan — vangt verzonnen getallen),
*complete* (0,10; niet afgekapt), *concise* (0,10). De **poort** is 0 bij een dosering per oppervlak/volume of een ongekwalificeerde toelatings-claim: een lek is
nooit goed te maken met volledigheid. Gewichten staan op één plek (`RewardConfig`). Sleutelfeiten voor kaarten zijn een ruwe proxy (langste inhoudswoord per actiestap, 7-letter-stam).

**4. Rejection sampling** (`ingest/build_orchard_rs_pairs.py`): per verified trainingsprompt N = 4 antwoorden van het basismodel (T = 0,8) + het kaart-referentieantwoord,
gescoord met de reward; chosen = beste met schone poort, rejected = slechtste, mits verschil ≥ 0,15. Basismodel op 95 trainings- en 22 validatieprompts
(468 samples): reward 0,83–0,85 vs referentie 0,96–1,0; **focus 0,48** (het model kopieert de juiste kaart maar vult aan uit buurfragmenten),
coverage 0,92, **14 toelatings-claims (CLAIM)**, geen afgekapte of lege antwoorden. Dit leverde 54 + 15 on-policy DPO-paren (`dpo_rs_*.jsonl`, in 50+15 gevallen is chosen de
kaart-referentie). **DPO is niet gedraaid**: na SFT v2 scoort het model op de validatieprompts overal 1,0 (88/88 samples), dus er zijn geen paren meer
om van te leren, en 69 paren zijn te weinig voor een zinvolle DPO-ronde. De paren blijven bewaard voor als de promptverdeling verbreedt (bv. met prozachunks).

**5. SFT** (`cloud/train_sft_qlora.py`, op de pod: QLoRA r = 16, 4-bit NF4 op bf16-basis, lr 1e-4, 3 epochs, loss alleen op het antwoord, prompt = exact het live-formaat
inclusief tool-instructie en `enable_thinking=False`; ~ 18 min op de A30 met de Qwen-service tijdelijk uit). Geserveerd door vLLM als LoRA op de AWQ-basis
(`weights=<mapnaam>`): de evaluatie meet dus de adapter zoals hij echt draait. Resultaten, 114 vragen, 3 runs, gemiddelde ± sd (punten):

| Configuratie | gouden set dekking / volledig | held-out dekking / volledig | guardrail gouden / held-out | grounding | gem. lengte | latency |
|---|---|---|---|---|---|---|
| basismodel | 88,8 / 77,6 | 75,9 / 55,6 | 91,7 / 85,4 | 97 / 93 % | 875 / 937 tekens | 7,4 s |
| **SFT v1** (alleen 95 kaarten) | 86,9 / 83,5 | 87,0 / 84,4 | **25,0 / 31,2** | 94 / 93 % | 1062 / 814 | 8,8 s |
| **SFT v2** (+ 48 compliance-voorbeelden) | 88,4 / 85,2 | **86,7 / 86,7** | **100 / 91,7** | 99,6 / 97,8 % | 584 / 652 | 5,7 s |

- **v1 faalde zoals verwacht en leerzaam**: de kaarten bevatten geen enkele vraag naar een dosering of product, dus het model beantwoordde zulke vragen als kaart,
  zonder Ctgb-verwijzing (guardrail 87 → 30%: "catastrofaal vergeten" van de weigering) en lekte mijn bronregel-formaat ("(kaart N, bron-status: …)") in antwoorden.
- **v2**: 48 compliance-voorbeelden (dosering / toelating / middelkeuze; trainings-producten bewust disjunct van elk product in de evalsets, getest;
  het antwoord verwijst naar Ctgb + etiket, geeft nooit een getal of toelatingsstatus, en voegt een verified, dosis-vrije kaart-actie toe als er een is) en de bronregel zonder kaartnummer.
  Resultaat: **held-out volledige dekking 55,6 → 86,7 %** (+31 pt, niet in-sample), gouden set volledig 77,6 → 85,2 %, guardrail ≥ basismodel, antwoorden 33% korter en 25% sneller.
- **Eerlijke kanttekeningen**: (a) de held-out set heeft 15 inhoudsvragen (sd 0,0 = alle drie de runs gelijk: de adapter is bijna deterministisch); (b) guardrail-held-out
  91,7 % deelt de *vorm* met de compliance-trainingsvragen (andere producten, vergelijkbare sjablonen) — de 100% op de gouden set is zuiverder dan de 91,7%;
  (c) de gouden-set-dekking (gemiddeld) is niet verbeterd (88,8 → 88,4): de winst zit in *volledigheid* (alle feiten) en op onbekende kaarten; (d) eenvoudige
  eenmalige vragen — meerstaps-gesprekken, tool-aanroepen met weersnapshot en lange chatgeschiedenis zijn niet gemeten.
- **Bijwerking: herhalings-lussen.** Eén zin die ≥ 3× herhaald wordt: basismodel 0/342 antwoorden, v1 11/342, v2 5/342. Een repetition penalty loste het niet betrouwbaar op
  (1,05: geen effect, 1,1: minder lussen maar 1 dosering-lek). Oplossing in de agent (`has_repetition_loop` / `collapse_repetition`): bij een lus één keer opnieuw genereren met penalty 1,1,
  daarna herhaalde zinnen weghalen (alleen weghalen, nooit toevoegen). Op de 13 lus-gevoelige vragen × 6: **6/78 → 0/78 antwoorden met lus**, guardrail 100%. In het
  streaming-pad is de al getoonde tekst niet terug te halen; daar wordt alleen het opgeslagen antwoord opgeschoond.
- **Besluit uitrol**: de adapter staat op de pod (`_models/Orchard/sft_v2`, lokale back-up in `_models/` — gitignored) en is te kiezen met `ORCHARD_ADVISOR_WEIGHTS=sft_v2`
  (terugdraaien: variabele weghalen). De **standaard blijft het basismodel**: de adapter is nog alleen getest op losse vragen, het streaming-pad kan nog een lus tonen, en de publieke pod is niet meer
  read-only. Aanbeveling: eerst een korte gebruikerstest (chatgesprek met vervolgvragen en tools) en dan pas de variabele op de pod zetten.

**6. Serverfix (naar aanleiding van "Engine core initialization failed" op de pod).** De inferentieserver hield per gewichtsset een eigen vLLM-engine (elk 85% van de A30) zonder de andere te
verwijderen: het laden van een tweede model (adapter naast basis) faalde. Nu bevat de GPU één engine: een ander model vervangt het huidige nadat lopende verzoeken klaar zijn;
`shutdown()` werkt met de huidige vLLM; `/status` blokkeert niet tijdens een laadbeurt en meldt `loading` + de gemeten `typical_load_s` (25–40 s warm, tot ± 80 s koud). De chatpagina toont vooraf
"het taalmodel wordt geladen: ongeveer N seconden; het antwoord duurt daarna 5–30 s" (ook "kan even duren" als het model al geladen is), de zijbalk toont de modelstatus.

**7. Volgende stappen.**
1. Gebruikerstest van `sft_v2` in de chat (vervolgvragen, weersnapshot, tool-aanroepen); streaming-lusbeveiliging (afbreken bij ≥ 3 herhalingen); daarna standaard aanzetten.
2. Held-out set vergroten (nu 15 inhoudsvragen) en een *tweede*, onafhankelijke guardrail-set met andere zinsbouw; de promptverdeling van de training verbreden (prozachunks, meerstaps, vervolgvragen) en dan opnieuw rejection sampling op de adapter voor een eerste echte DPO-ronde.
3. 62 kaarten met "nog geen bron gevonden" laten verifiëren (nu uit de training gehouden) en LLM-OAC-extractie uit proza met letterlijke-span-verificatie.
4. Logboek eerst verifiëren (0/487) vóór logboek-SFT; het logboek heeft geen uitkomsten, dus voor DPO/Reflectie uit eigen data is een uitkomstsignaal (oogst/schade per seizoen) nodig.
5. Reward uitbreiden met een extern signaal (oogst/kwaliteit) en een echte sleutelfeiten-set per kaart in plaats van de proxy.

<a id="sec-g29"></a>
## G.29 Waterbalans: dag-tot-dag delta neerslag minus verdamping, te droog of te nat (2026-10-10)

**Vraag (teler)**: bestaan er modellen die uitrekenen of er genoeg neerslag is geweest, na verrekening van de verdamping en wat het gewas nodig heeft en wat er op
andere manieren bij komt of afgaat — een delta over een periode, zoals de landbouw gebruikt om te bepalen of het te droog of te nat is? Overzicht per dag, alleen de delta
van de afgelopen periode, ook onderaan het Boomgaard Dashboard.

**Antwoord: ja.** De gangbare benaderingen, van eenvoudig naar uitgebreid:
1. **Neerslagoverschot/-tekort (klimatologisch)**: neerslag min referentieverdamping, cumulatief. In Nederland het **KNMI-neerslagtekort**: som van (verdamping − neerslag) vanaf 1 april, nooit onder 0
   (bron: <https://www.knmi.nl/kennis-en-datacentrum/achtergrond/achtergrondinformatie-neerslagtekort>). Eenvoudig, landelijk bekend, maar kent geen gewas en geen bodem.
2. **FAO-56-bodemwaterbalans** (Allen e.a. 1998, *FAO Irrigation and Drainage Paper 56*): een "emmer" in de wortelzone. Gewasverdamping ETc = Kc × ET0; water erin = regen + beregening; water eruit =
   opname door het gewas + afvoer naar diepere lagen; de voorraad bepaalt of de boom stress heeft (te droog) of dat het overschot wegloopt (te nat). **Dit hebben we gebouwd.**
3. **Uitgebreide dynamische modellen** (genoemd, hier niet gebruikt of gemeten): o.a. AquaCrop (FAO), WOFOST en SWAP (Wageningen) — nodig als je grondwater, bodemlagen en gewasgroei
   mee wilt modelleren; vragen bodem- en gewasgegevens die we voor dit perceel (nog) niet hebben.

**Gebouwd** (`pipeline/orchard_water_balance.py`, deterministisch en zonder model, zoals de rest van de rekenkern; weergave in `app/waterbalance_view.py`):
- Per dag: `ETc = Kc·ET0` (FAO eq. 58); **`delta = neerslag + beregening − ETc`** (de gevraagde delta); bodemvoorraad `Dr` (eq. 85), stressfactor `Ks` (eq. 84), afvoer `DP` (eq. 88),
  `TAW = 1000·(θFC−θWP)·Zr` (eq. 82), `RAW = p·TAW`. De massabalans klopt exact (getest): ingaand − opname − afvoer = verandering van de voorraad.
- **Water erbij**: regen (Open-Meteo-archief) en beregening (door de teler in te voeren, per dag in mm; het logboek bevat geen beregening). **Water eraf**: gewasverdamping en afvoer onder de wortelzone.
  Verwaarloosd (gedocumenteerd): oppervlakte-afvoer en capillaire opstijging uit het grondwater.
- **Status per dag**: `te droog` (Dr > RAW, dus Ks < 1: de boom neemt minder op), `droog (let op)` (Dr > 75% van RAW), `nat` (≥ 5 mm afvoer in 3 dagen), anders `ok`.
- Ernaast het **KNMI-stijl neerslagtekort** (vanaf 1 april, referentiegewas) als bekende maat; met FAO-56 ET0 van Open-Meteo in plaats van Makkink (kleine afwijking, zelfde betekenis).
- **Dashboard (onderaan)**: staafgrafiek van de delta per dag (blauw = overschot, oranje = tekort) met de cumulatieve lijn over de gekozen periode (7–120 dagen), een tweede grafiek met het bodemvocht
  (% van het beschikbare water, met de stresslijn), zes kerngetallen, een dagtabel en instellingen (grondsoort, wortelzone, ondergroei). De bodemvoorraad loopt vanaf 1 maart mee (opwarmperiode), zodat de
  getoonde periode een betekenisvolle beginstand heeft. Weerdata 3 uur gecachet; bij een storing een foutmelding, nooit verzonnen data.

**Wat is echt (gecit.) en wat illustratief** (zelfde discipline als [Deel B.1](#sec-b1)):
| Onderdeel | Status | Bron |
|---|---|---|
| Vergelijkingen 58, 82, 84, 85, 88 | echt | FAO-56 hfst. 6 en 8 |
| Kc 'stone fruit', klimaat met vorst: 0,45 / 0,90 / 0,65 (kaal), 0,50 / 1,15 / 0,90 (actieve ondergroei) | echt, maar benadering voor kers (FAO noemt abrikoos, perzik, peer, pruim, pecan; kers staat er niet apart) | FAO-56 tabel 12 |
| Beschikbaar bodemwater per grondsoort (zand 0,05–0,11 … klei 0,12–0,20 m³/m³; midden gebruikt) | echt | FAO-56 tabel 19 |
| Kers: p = 0,50, wortelzone 1,0–2,0 m | echt | FAO-56 tabel 22 |
| KNMI-neerslagtekort | echt (definitie), ET0 anders dan KNMI | KNMI |
| Kalender van de Kc-curve (1 april → 1 juni oplopend, tot 15 sept vlak, dalend tot 1 nov) | **illustratief** | eigen benadering van de FAO-stadiumlengtes |
| Standaard grondsoort (leem), wortelzone 1,0 m, begin op veldcapaciteit op 1 maart | **illustratief** | aanname |
| Drempels van de status (75% van RAW; 5 mm afvoer in 3 dagen) | **illustratief** | aanname |

**Controle met echte data** (Open-Meteo, 1 maart – 9 oktober 2026, 223 dagen, geen ontbrekende ET0): neerslag 456 mm, gewasverdamping 706 mm (Kc 1,15 met ondergroei), delta −251 mm, afvoer 39 mm,
KNMI-stijl neerslagtekort piekt op 287 mm (eind september 268 mm). Plausibel voor een droog seizoen (ter vergelijking: 2018 had landelijk > 300 mm). De laatste 30 dagen: delta +0,5 mm (neerslag 64 mm,
verdamping 64 mm); op 9 oktober +15,8 mm. Tests: 14 voor de rekenkern (handberekende dag, exacte massabalans, stress, nat, ontbrekende ET0, KNMI-reset op 1 april) en 6 voor de pagina (nepbron, geen netwerk);
331 → 351 tests.

**Beperkingen / eerlijk**: (1) **Zonder grondwater-opstijging en zonder beregening is de schatting pessimistisch** — veel Nederlandse kersenpercelen krijgen water uit het grondwater; dit staat ook in de
pagina. (2) Grondsoort en wortelzone zijn aannames; een bodemanalyse (Deel C.4/C.7) en bij voorkeur een vochtsensor maken er een echte meting van. (3) Het verleden loopt tot gisteren (de archief-API heeft vandaag nog niets); de 7-daagse vooruitblik gebruikt de forecast (zie hieronder). (4) Kc voor kers is een benadering; de curve is niet gekalibreerd op dit perceel. (5) Eén emmer, geen bodemlagen of grondwaterstand.

**Volgende stappen** (bijgewerkt hieronder, zie "Vooruitblik en adviseur-tool"): bodemanalyse of vochtsensor invoeren (TAW echt maken) en grondwater/opstijging modelleren; beregening uit de praktijk vastleggen
(nu alleen sessie-invoer); koppeling met barstrisico rond de oogst ([Deel B](#sec-b1), `evaluate_rain_crack_risk`) en met ziektedruk (bladnatperiode).

### Vooruitblik en adviseur-tool (2026-10-10)

- **Vooruitblik 7 dagen**: `orchard_tools.get_forecast_water_inputs()` haalt neerslag en `et0_fao_evapotranspiration` uit de Open-Meteo-forecast. `pipeline/orchard_water_service.py::compute_water_state()` rekent
  de bodemvoorraad door tot en met gisteren (archief) en gaat daarna **verder met de forecast vanaf de werkelijke eindstand** (dagen die al in het archief staan worden niet dubbel geteld). Op het dashboard staan de
  verwachte dagen gearceerd/lichter in een grijs vlak "verwachting", met vier eigen getallen (verwachte neerslag, gewasverdamping, delta, bodemvocht aan het eind) en een melding bij eerste stress-/natte dag.
  Mislukt de forecast, dan blijft het verleden gewoon staan met een korte melding. De verwachting is richting, geen exact getal (dagelijkse neerslag is onzeker).
- **Adviseur-tool `waterbalans`** (alleen in de catalogus met weer-snapshot, dus de SFT-prompts met `snapshot=None` veranderen niet): geeft via dezelfde service een Nederlandse feitentekst — delta laatste 7 en 30 dagen, bodemvocht en
  status, KNMI-stijl tekort, verwachting, aannames en het "indicatief"-label. Het model rekent niets zelf; bij weerstoring zegt de tool dat en geeft hij geen getallen. Bron: "Waterbalans (FAO-56, Open-Meteo; indicatief)".
  De tool gebruikt de standaardinstellingen (leem, 1,0 m, gras); de aangepaste instellingen van het dashboard zijn sessie-invoer en bereiken de adviseur (nog) niet.
- **Echte controle** (9 oktober 2026, 52,0/5,5): laatste 7 d neerslag 24 mm, ETc 11 mm, delta +13 mm; laatste 30 d delta +1 mm; bodemvocht 47% (te droog); verwachting 10 mm regen tegen 8 mm verdamping.
- **Kalibratie op het logboek: niet haalbaar.** Het logboek (484 opmerkingen) bevat geen beregening en geen opbrengst- of droogte-uitkomst; "droog" komt 8× voor, "gieter" 1× (2013) en er is geen vochtmeting.
  Kalibreren van Kc, wortelzone of drempels vraagt een uitkomst (vochtsensor, stressscore, opbrengst) per seizoen; die kan de teler gaan vastleggen. Tot dan blijft de status een FAO-56-indicatie.
- Tests: 362 groen (nieuw: service met continuering/dubbele dagen/forecast-storing/uitblik, tool, pagina met forecast en storing).

---

<a id="sec-g30"></a>
## G.30 Logboek-kalender: "wat deed ik rond deze tijd?" en wat het logboek over de nazorg zegt (2026-10-10)

**Vraag (teler)**: welke inzichten kunnen we nog uit de logboeken halen, hoe gebruiken we ze bij de oogst van 2027, en wat is er nu te doen in de nazorg/rust — een advies per periode, week of maand op basis van de logboeken?

**Gebouwd** (alles deterministisch geteld, het taalmodel rekent of verzint niets):
- `pipeline/orchard_logbook_calendar.py`: per referentiedatum en venster (±7–30 dagen) per middel *in hoeveel jaren van het eigen logboek het voorkwam*, aantal toepassingen, gebruikelijk interval (mediaan) en doel uit de opmerkingen ("Tegen pseudomonas"; weerzinnen
  als "beetje wind" tellen niet als doel). Daarnaast de vergelijking met dit jaar: "gebruikelijk rond deze tijd (in ≥ 50% van de jaren), maar dit jaar nog niet in het logboek" — alleen als het lopende jaar genoeg regels heeft
  (anders staat er eerlijk dat vergelijken niet kan; 2026 heeft nog 0 regels). Namen via de bestaande `orchard_middelen.canonicalize_middel` (Zinc = Zink e.d.).
- **Adviseur-tool `logboek_kalender`** (alleen met `ORCHARD_LOGBOOK_RAG=1` en de database aanwezig, dus net als `logboek_zoeken` niet op de publieke pod): argument leeg = vandaag, een maandnaam ("november") of een datum. Bron wordt vermeld.
- **Pagina-sectie** "Wat deed ik rond deze tijd?" bovenaan *Gebruik van Middelen* (`app/logbook_calendar_view.py`): datum + venster, tabel per middel, waarschuwing voor wat dit jaar ontbreekt.
- **Compliance-guardrail** ([B.11](#sec-b11)): hoeveelheden staan bewust **nergens** in de uitvoer (de tool kan dus geen dosering "uit eigen gewoonte" suggereren), en elke uitvoer sluit af met: eigen historie, geen advies, geen toelatingsstatus, controleer Ctgb/kennisbank.

**Twee datakwaliteitsbevindingen die de tellingen vertekenden** (nu gecorrigeerd bij het lezen, de database zelf blijft ongemoeid):
1. **2020 is twee keer ingescand** (`jaar 2020.pdf` en `jaar 2020-2.pdf`): 45 identieke regels (zelfde datum, middelen en hoeveelheden) stonden dubbel, daarom had 2020 90 regels tegen ~40 in andere jaren. `dedupe_entries` telt identieke regels van
   *verschillende pagina's* één keer (42 verwijderd; een dezelfde regel twee keer op één pagina blijft staan, dat kan echt twee bespuitingen op één dag zijn). *Gebruik van Middelen* gebruikt dit nu ook, dus de eerdere totalen in [G.9](#sec-g9) waren voor 2020 te hoog.
2. **Geen enkele van de 487 regels is handmatig geverifieerd** (en 2024 heeft maar één regel). Een jaar met < 8 regels telt niet mee als "jaar met logboek" (anders lijkt elk middel in 2024 "niet gedaan"). De verificatie-pagina blijft de belangrijkste openstaande kwaliteitsstap.

**Wat het logboek zegt over nu (oktober tot december; eigen historie 2013–2025)**:
- *Oktober*: bladvoeding (Ureum met Borium, Mangaan, Kalifosfaat, Epso Microtop), meestal 1–4 rondes met 4–14 dagen ertussen; Ureum komt in 8 jaar voor.
- *Eind oktober tot half november*: **koper + zink (soms ureum) tegen pseudomonas rond de bladval**: koper in 8 van de 12 jaren in het venster rond half november, vaak 2–4 rondes met ~1 week ertussen; in 2019 expliciet "zink voor bladvertering".
  In 2025 hetzelfde patroon (koper 15 okt en 1 nov, zink 20 okt en 4 nov, bitterzout 20 okt, 1 en 7 nov).
- *December*: hooguit één of twee koperrondes (2017, 2021); daarna niets tot maart (dan koper, borium, zwavel, patentkali, kalk).
- Dit zegt **wat de teler deed, niet of het werkte**: het logboek bevat geen uitkomsten. Daarom is Deel H nodig.

**Wat we er nog meer mee kunnen** (volgende stappen, nog niet gebouwd): (a) ingrepen op **fenologie/graaddagen** zetten in plaats van kalenderdatum (koud en warm jaar eerlijk vergelijken); (b) **koperbelasting per jaar** optellen en toetsen aan de wettelijke grens
(de grenswaarde eerst uit de kennisbank halen, hier staat bewust geen getal); (c) **spuitmoment tegenover weer**: hoe vaak viel er regen of veel wind vlak na een bespuiting (het weer staat al per regel in het logboek); (d) naamvarianten die we nu niet met zekerheid
samenvoegen (Tracor/Tracer) door de teler laten bevestigen; (e) de kalender combineren met de actuele fenofase, het weer en de waterbalans tot één "deze week"-overzicht, met dezelfde guardrails.

Tests: 377 groen (nieuw: 15 voor de kalender, dubbele regels, jaar-met-logboek, Feb-29, tool met/zonder vlag, database, pagina).

---

<a id="sec-g31"></a>
## G.31 Middel opzoeken: Ctgb-voorschrift (open API) + eigen logboek + agentic tool, multi-hop-ontwerp (2026-10-10)

**Vraag (teler)**: kunnen we een agentic tool maken waarmee de juiste dosering en toepassingsfrequentie worden opgezocht in de Ctgb-databank en op het etiket — of heb je daarvoor een abonnement nodig? En kan het een opzoektool zijn vanuit de eigen omgeving: welk merk heb je, en wat zou je volgens je logboeken en eerdere ervaring moeten doen? Ook een pagina/knop (bij Middelen), en een tool die we later in het multi-hop-redeneren kunnen meenemen.

**Antwoord: nee, geen abonnement nodig.** Het Ctgb biedt een **open API** (MST public API, `https://public.mst.ctgb.nl/public-api/1.0/`, JSON:API, geen sleutel; de Toelatingendatabank zelf gebruikt dezelfde API; het Ctgb geeft er geen ondersteuning op) en de data zijn open (CC-0 op data.overheid.nl).
De oude bulk-export (`ctgb.blob.core.windows.net/...xls`) is wel dood (opnieuw bevestigd), maar dat is niet meer nodig. Gecontroleerd met echte antwoorden voor Syllit, Movento, Switch, Signum, Pirimor, Calypso, Thiovit, Folicur en Rovral.

**Wat de API per gebruik (per gewas) levert** (`/authorisations?filter[productName]=…`, dan `/authorisations/{id}`): maximale dosis (`maximumProductDose`, bv. 1,25 L/ha of 0,75 kg/ha), aantal toepassingen (`perCropSeason` en/of `perUse`), minimaal interval in dagen,
veiligheidstermijn (`phiDays`), periode (maanden), groeistadium (BBCH), watervolume, doelorganismen (met EPPO-codes), teeltomstandigheden, opmerkingen en beperkingen in vrije tekst, en de links naar de **officiële gebruiksaanwijzing en het toelatingsbesluit** (PDF). Ook werkzame stof(fen) met gehalte, toelatinghouder, geldigheid.

**Ontwerpkeuze: twee kanalen** (deterministische kern eerst, [B.1](#sec-b1)/[B.11](#sec-b11)):
| Kanaal | Voor wie | Inhoud |
|---|---|---|
| **Kaart** (`ToolResult.card` → `AdvisorResponse.cards`, `format_card`) | de teler, door de app getoond (uitklapper "Officiële gegevens (letterlijk uit de bron, niet door het model geschreven)") | de getallen **letterlijk** uit de API, met links naar de PDF's en de disclaimer "wettelijk maximum, geen spuitadvies; gebruiksaanwijzing/etiket is leidend" |
| **Facts** (`format_model_facts`) | het taalmodel | alleen status ("geldige/verlopen toelating", "voorschrift voor kers aanwezig") en de opdracht om naar de kaart te verwijzen; **geen doseringen of limieten** |
Zo kan het model nooit een dosis "verbeteren" of verzinnen, blijft de SFT-/eval-houding (nooit een dosis noemen; `DOSE`/`CLAIM`-guards in `orchard_eval`/`orchard_reward`) geldig en is toch elke getoonde waarde herleidbaar tot de bron. De beschrijving van `ctgb_toelating` in de toolcatalogus is **ongewijzigd**, dus de bestaande SFT-prompts blijven kloppen.

**Gebouwd**
- `pipeline/orchard_ctgb.py`: client met schijf-cache (7 dagen, `Data/Orchard/Ctgb/`, gitignored), terugval op oudere cache met melding bij storing, `CtgbUnavailable` zonder cache (nooit een verzonnen status); parser (`CtgbUse`/`CtgbProduct`); `lookup(naam)` (geldige toelatingen eerst; verlopen toelatingen alleen als ze een kers-voorschrift hebben, de rest wordt geteld
  en genoemd); `format_card`, `format_model_facts`, `use_rows` (tabel), `detect_product_names`. Details die de echte data afdwong: kers-gebruik = hele gewasnamen (**"Tuinkers" is geen kers**); "Boomkwekerijgewassen" bevat ook kers maar is kwekerijgebruik, dus alleen expliciet *Kers* of de groepen *Vruchtbomen*/*Steenvruchten*;
  Ctgb-datums zijn middernacht Nederlandse tijd als UTC (22:00Z/23:00Z) en worden op de Nederlandse dag afgerond; `perUse` en `perCropSeason` worden allebei letterlijk getoond met hun eigen label.
- `pipeline/orchard_middel_lookup.py`: **`middel_opzoeken(logboek, merknaam)`** combineert (1) het Ctgb-voorschrift, (2) het eigen gebruik uit het logboek (`product_history`: aantal, per jaar, maanden, interval, doel, laatst gebruikt, "rond deze tijd in X van Y jaar") en (3) een **praktijkcontrole** tegen de ruimhartigste limiet van de geldige kers-voorschriften
  (aantal per seizoen, interval, toegestane maanden; alleen vergelijken als alle limieten bekend zijn, geen beschuldiging bij een ruimere tweede gebruiksvoorschrift). De waarschuwing heeft twee teksten: met getallen voor de kaart, **zonder getallen voor het model**. Bij een verlopen middel staat er expliciet waarom er niet vergeleken is.
- **Tools**: `ctgb_toelating(merknaam)` is nu echt (kaart + status); `middel_opzoeken(merknaam)` (alleen waar het logboek lokaal aan staat, `ORCHARD_LOGBOOK_RAG=1`, dus niet op de publieke pod) geeft kaart + eigen gebruik + praktijkcontrole. `check_ctgb_toelating()` in `orchard_tools` retourneert nu een gestructureerd antwoord.
- **Chat** ("Vraag de Adviseur"): middel-/dosering-/toelatingsvragen met een herkenbare merknaam tonen direct de officiële kaart (deterministisch, zonder het model); zonder merknaam vraagt de app om de merknaam (guardrail blijft); bij storing geen getallen.
- **Pagina** *Gebruik van Middelen → Middel opzoeken* (`app/ctgb_lookup_view.py`): kies een middel uit je logboek (alleen gewasbeschermingsmiddelen; meststoffen vallen niet onder het Ctgb) of typ een merknaam, knop "Zoek op": tabel per product en gebruik, volledige kaart in een uitklapper, je eigen gebruik (metrics, grafiek per jaar, doel) en de praktijkwaarschuwing.

**Echte bevindingen op jouw logboek** (peildatum 10 oktober 2026; indicatief, zie de voorbehouden hieronder):
- **Syllit** (35 toepassingen, 2013–2023): in 8 van de 11 jaren staan 3–5 toepassingen in het logboek, terwijl het huidige kers-voorschrift (Syllit 544 SC en Syllit Flow 400 SC) maximaal 2 per teeltseizoen toestaat; de logboek-intervallen (~12 dagen) liggen ook ver onder het minimale interval van het voorschrift. Waarschuwing met voorbehoud: een regel kan een deelbehandeling of ander perceel zijn en de voorschriften waren vroeger mogelijk anders.
- **Movento** (11 toepassingen, tot 2022): de toelating onder die naam, met het voorschrift voor kers (zwarte kersenluis), is **verlopen op 30 april 2024**; er is onder de naam "Movento" geen geldig kers-voorschrift meer (er kan een opgebruiktermijn hebben gegolden; een opvolger onder een andere naam is hier niet nagegaan). **Calypso** (laatst gebruikt april 2020) is in 2020 verlopen.
- **Signum**: geldig voor kers, geen afwijking van het voorschrift gevonden in het logboek.

**Multi-hop-ontwerp (volgende stap, nog niet gebouwd)**: de tools zijn zo gebouwd dat ze als stappen in een keten passen (`ToolResult = facts + sources + card`; elke stap is deterministisch, getest en citeerbaar):
1. *Situatie*: `waterbalans`, weer/vorst/Suzuki-risico, fenofase, `logboek_kalender` (wat deed je rond nu?).
2. *Probleem*: kennisbank (probleemkaarten, OAC) of de teler benoemt het (bv. bladvlekkenziekte).
3. *Kandidaten*: eigen historie (welke middelen gebruikte je tegen dit doel) → `middel_opzoeken` per kandidaat.
4. *Poort (deterministisch)*: geldige toelating, kers-voorschrift aanwezig, **toegestane maand en BBCH nu**, interval t.o.v. je laatste toepassing in het logboek, aantal toepassingen dit seizoen versus het maximum, **veiligheidstermijn tegen de verwachte oogstdatum**, bestuivers-/bloeifase ([B.11](#sec-b11)). Alleen kandidaten die de poort passeren worden getoond, elk met kaart.
5. *Uitleg*: het taalmodel verwoordt keuzes en afwegingen (waarom nu, wat is het alternatief) zonder getallen te noemen.
Uitbreidingen die de API al toelaat: werkzame stof per toepassing bijhouden voor **resistentiemanagement** (zelfde stof meerdere keren per seizoen), alternatieve middelen met hetzelfde doel (`filter[pppTargetOrganisms]`, `filter[pppTargetCrops]`), bijenindicatie per gewas (`attractiveToHoneybees`). **Compliance-poort (aanbevolen)**: elk antwoord dat een middelnaam noemt moet in dezelfde beurt een `ctgb_toelating`/`middel_opzoeken`-aanroep hebben (anders disclaimer), zoals [B.11](#sec-b11) al eiste.

**Beperkingen / eerlijk**: (1) de API is niet door het Ctgb ondersteund en kan wijzigen; de cache en de storingsmelding vangen dat op, de parser is gecontroleerd tegen echte antwoorden maar niet tegen alle ~1000 toelatingen. (2) Gebruiksaanwijzingen en besluiten worden alleen **gelinkt**, niet geparsed (vrije tekst met o.a. bijenregels en mengadviezen staat daar); een label-corpus voor de RAG is een logische vervolgstap.
(3) Het watervolume heeft in de API geen vermelde eenheid; de kaart zegt dat. (4) Verlopen toelatingen kunnen een opgebruik-/afleveringstermijn hebben; de kaart wijst naar het besluit. (5) De praktijkcontrole vergelijkt met de huidige voorschriften en telt kalenderjaren als teeltseizoen.
(6) **Eval**: het gedrag van `ctgb_toelating` is veranderd (echte status in plaats van altijd een guardrail-tekst). Gecontroleerd met `sft_v2` op de guardrail-vragen (gouden + held-out, 20 vragen) na de wijziging: **19/20 geslaagd, 0 doseringen genoemd**; de ene afwijking (gh02) is de al bekende `CLAIM`-vals-positief
(het model weigert, maar schrijft "toegelaten" in de zin, zie [G.28](#sec-g28)). Aanvullend horen er merknaam-vragen bij die via de kaart beantwoord worden en een herhaling met meer runs.
Dit is geen spuitadvies: de app toont wat Ctgb toestaat en wat jij deed; de keuze en de verantwoordelijkheid blijven bij de teler.
Tests: 411 groen (nieuw: 16 voor client/parser/cache/kaart, 17 voor de combinatie, tools, agent-kaartstroom en pagina-sectie, 2 voor de chatroute; alles met een nep-API in dezelfde vorm als de echte antwoorden, zonder netwerk).

---

<a id="deel-h"></a>
# Deel H — Aanbevelingen voor de teler: wat meten en vastleggen vanaf 2027

*Dit deel is zo geschreven dat het los te lezen is en aan de teler gegeven kan worden. Alles in "Moeite/kosten" is een relatieve schaal (laag/midden/hoog) en geen prijsopgave; vraag voor sensoren en camera's altijd offertes en advies van een leverancier of adviseur.
Agronomische richtwaarden zijn indicatief en komen uit VS-extensiebronnen (OSU, WSU, Cornell) en de Nederlandse praktijk; laat streefwaarden per grondsoort en ras door je lab of adviseur bevestigen.*

<a id="sec-h0"></a>
## H.0 Waarom dit nodig is

Het logboek van 2013–2025 vertelt **wat** er gebeurde (middel, datum, weer), maar niet **wat eruit kwam**. Daardoor kan de adviseur zeggen "dit deed je meestal in november", maar niet "dit werkte" of "dat heeft de opbrengst gekost". Voor een adviseur die echt aan
opbrengst en kwaliteit werkt, ontbreken vier dingen: **uitkomsten** (kilo's, klasse, barst, schade), **metingen van de omstandigheden** (bodem, bodemvocht, weer op het perceel), **waarnemingen in het seizoen** (bloei, plagen, schade, met foto) en
**een vaste structuur** (per boom/rij/ras, op een vast moment). Dit deel zegt wat je daarvoor kunt vastleggen, in volgorde van belang, zodat je klein kunt beginnen en kunt uitbreiden.

**Wat je ervoor terugkrijgt**: een adviseur die kan zeggen "vorig jaar spoot je op 6 mei en kreeg je 4% barst; dit jaar valt de bloei 9 dagen eerder, de bodem is droger dan toen, en de vliegenval staat al op 5" — met jouw eigen cijfers in plaats van gemiddelden uit boeken.

<a id="sec-h1"></a>
## H.1 Vijf spelregels (belangrijker dan welke sensor je koopt)

1. **Altijd datum + plaats**: elke meting krijgt een datum, een perceel/blok, bij voorkeur een rij- of boomnummer (hang nummerplaatjes; het ras en de onderstam staan vast per nummer).
2. **Elk jaar op hetzelfde moment en dezelfde plek**: bodem- en bladmonster, foto's, vaste telbomen. Alleen dan zijn jaren vergelijkbaar.
3. **Ook "niets gezien" en "niets gedaan" noteren**: nul plagen op een val is informatie; een lege regel is dat niet.
4. **Eén eenheid per grootheid** (kg per boom of per rij, liter per ha, mm water). Schrijf de eenheid erbij.
5. **Uitkomst noteren, ook als het tegenvalt**: dit is precies wat in de huidige logboeken ontbreekt.

<a id="sec-h2"></a>
## H.2 De korte lijst: wat het meeste oplevert (begin hier)

| # | Wat | Hoe vaak | Waarom (wat de adviseur ermee doet) | Moeite/kosten |
|---|---|---|---|---|
| 1 | **Oogstregistratie per ras en perceel**: datum, kilo's (per kist wegen), klasse/maat in mm, % barst, % made/Suzuki, % hagel/vogel | elke pluk | Het ontbrekende "resultaat". Zonder dit is optimaliseren op opbrengst niet mogelijk ([C.7](#sec-c7)); het is ook het signaal voor latere training | laag |
| 2 | **Bodemanalyse** (pH, organische stof, nutriënten, kalk/EC; vermeld de methode, bv. pH-KCl of pH-CaCl2) | 1× per jaar, zelfde tijd (najaar of vroeg voorjaar) | pH richtwaarde voor kers ca. **6,0–7,0**; buiten die band worden o.a. ijzer en zink slecht opneembaar. Maakt ook de waterbalans ([G.29](#sec-g29)) echt (nu is de grondsoort een aanname) | laag |
| 3 | **Bladanalyse** | 1× per jaar in **juli**, zelfde bomen | Toont of de bemesting en bladvoeding (ureum, borium, zink, mangaan, magnesium) echt aankomen; stuurt de bemesting van het volgende jaar. Past bij de vele bladvoedingsrondes in het logboek | laag |
| 4 | **Bodemvochtsensoren** (2 dieptes, in de boomstrook, op een representatieve plek) + **regenmeter op het perceel** + **watermeter bij beregening** | continu (log elk uur) | Kalibreert de waterbalans (TAW, wortelzone, drempel voor stress) en zegt of beregenen nodig was | midden |
| 5 | **Weerstation/loggers op het perceel**: temperatuur op boomhoogte (vooral min.-temperatuur in de bloei), neerslag, wind, bladnatduur | continu | Echte vorst in jouw perceel (kouplekken), echte bladnat-uren voor ziektemodellen, en controle op de weer-API | midden |
| 6 | **Fenologie-waarnemingen** (BBCH of simpel: knopzwelling, begin / volle / einde bloei, vruchtzetting, kleuren, oogstbegin) per ras | wekelijks in het seizoen | Kalibreert de koude-uren-/graaddagen-modellen en voorspelt bloei en oogst voor jouw rassen | laag |
| 7 | **Plaagmonitoring met vallen**: Suzuki-vallen (rood/donker + lokmiddel), gele plakplaten voor de kersenvlieg; telling met datum | wekelijks, **vanaf vóór de vruchten kleuren tot de oogst** (kersenvlieg: vóór het verwachte begin van de vlucht) | Maakt de Suzuki-/kersenvlieg-risicomodellen meetbaar en bepaalt het spuitmoment | laag |
| 8 | **Digitale spuit- en bemestingsregistratie** (zie H.3 G) | bij elke behandeling | Eén structuur voor alle jaren; verplicht om bij te houden (EU 1107/2009, art. 67: gegevens minimaal 3 jaar bewaren, controleer de actuele eis) | laag |
| 9 | **Schadefoto's en -scores** bij vorst, hagel, regen/barst, vogels | bij elk incident, + 1–2 dagen later | Maakt "wat was de schade" koppelbaar aan weer en handelen | laag |
| 10 | **Camera's** (zie H.4) op 1–2 vaste plekken | dagelijks | Automatische fenologie, groei, kleuring en schadetijdlijn; later schatting van bloem- en vruchtaantal | midden |

<a id="sec-h3"></a>
## H.3 Volledig overzicht per onderwerp

**A. Bodem**
| Meting | Moment | Opmerking |
|---|---|---|
| pH (+ methode), organische stof, kalktoestand, EC/zoutgehalte | 1× per jaar, zelfde moment | mengmonster van meerdere steken per perceel of grondsoort (VS-adviezen: 10–20 steken per blok, bovenste ~30 cm; vraag je lab om het protocol); niet vlak na bemesting of beregening |
| Nutriënten (P, K, Mg, Ca, S) en sporenelementen (B, Zn, Mn, Fe, Cu) | 1× per jaar | borium, zink en mangaan staan elk jaar in het logboek: hiermee zie je of het nodig is |
| Stikstof-mineraal (N-min) | voorjaar | voor de stikstofgift (ureum is de meest gebruikte meststof in het logboek) |
| Grondsoort en profiel (zand/leem/klei, laagopbouw, verdichting, doorwortelbare diepte) | eenmalig (profielkuil of boor), daarna om de paar jaar | bepaalt TAW en wortelzone in de waterbalans |
| Grondwaterstand / drainage | eenmalig + bij nat of droog seizoen | grondwater-opstijging is de grote onbekende in de waterbalans |
| Eventueel: bodemleven, regenwormen, grondbedekking (gras/kaal), onkruidstrook-breedte | jaarlijks, korte notitie | grondbedekking verandert de verdamping (Kc) |

**B. Water en beregening**: bodemvocht op 2 dieptes (capacitieve sensoren of tensiometers), regenmeter, watermeter, beregeningsduur en mm per beurt, en of het uit grondwater of sloot komt. Ook droogtestress zien en noteren (bladrollen, schorsscheuren), met foto.

**C. Weer op het perceel**: luchttemperatuur op boomhoogte (en in de laagste hoek van het perceel voor vorst), neerslag, windsnelheid/-richting, instraling of zonuren, bladnat; elk uur loggen. In de bloei elke 10–15 minuten voor vorst. Dit valideert ook de koude-uren (rustperiode) en de graaddagen.

**D. Fenologie en groei**: data van knopzwelling, begin/volle/einde bloei, vruchtzetting (% bloemen die een vrucht worden: tel op vaste takken), kleuren, oogstbegin en -einde, bladval. Groeikracht: scheutlengte aan vaste bomen en stamomtrek (stamdoorsnede) jaarlijks. Snoeidatum en wat er gesnoeid is.

**E. Plaag en ziekte (scouting)**: score 0–3 per vaste telboom, wekelijks: luis (zwarte kersenluis), spint, monilia, schimmelziekten van blad en vrucht, **bacterie/pseudomonas (kanker, gomvloed, afsterven)**, "hagelschot" (Stigmina), vogelschade. Vallen: Suzuki-valtelling (mannetjes met vlek op de vleugel), gele plakplaten kersenvlieg. Noteer ook de plek.

**F. Bestuiving**: aantal bijen-/hommelvolken en wiens kasten, plaatsingsdatum, bijenvlucht bij bepaalde temperatuur, overlap met de bloei; vruchtzetting als uitkomst ([C.7](#sec-c7)).

**G. Spuit- en bemestingsregistratie (per behandeling)**: datum + begin/eindtijd; perceel/rijen; middel en toelatingsnummer; dosis **per ha** en spuitvolume; doel (plaag/ziekte); fenologisch stadium; **windsnelheid en -richting, temperatuur, regen binnen 24 uur (ja/nee)**; spuitdoppen/driftreductie; wachttijd/veiligheidstermijn; partijnummer; *en achteraf: werkte het (0–3)*. Bij meststoffen: N-P-K/spoor per ha en of het bladvoeding of strooien was. (Hoeveelheden komen nooit als advies uit de adviseur; ze zijn wel nodig om je eigen koperbelasting en middelengebruik per jaar te kunnen tellen.)

**H. Oogst en kwaliteit (per pluk)**: datum, ras, perceel/rij, kilo's, aantal kisten, klasse en maat (mm), vaste stof (°Brix), stevigheid, kleur, % barst, % made/Suzuki, % hagelschade/vogelschade/dubbele vruchten, uitval; arbeidsuren en prijs/afzet per klasse. Dit is de basis om te rekenen welke ingreep zich terugbetaalt.

**I. Economie**: kosten per ingreep (middel, arbeid, machine), opbrengst per klasse, prijs. Dan kan de adviseur straks zeggen wat een ingreep per hectare opleverde.

**J. Boom- en perceelgegevens (eenmalig, dan bijhouden)**: ras, onderstam, plantjaar, plantafstand, rij-/boomnummers, kaartje, overkapping/regenkappen ja/nee, windscherm, hellingen en kouplekken, aanvullende bomen (bestuivers).

<a id="sec-h4"></a>
## H.4 Camera's: wat ze opleveren, hoe je ze plaatst

**Wat het oplevert (in volgorde van haalbaarheid)**
1. **Een tijdlijn per boom/rij**: bloeibegin, volle bloei, vruchtzetting, kleuren, schade (vorst, hagel, vogels, barst na regen) met datum. Dit is waardevol zelfs zonder analyse, omdat je terug kunt kijken en uitkomsten kunt koppelen aan weer en handelingen.
2. **Fenologie automatisch scoren** uit de foto's (bloeistadium, vruchtkleur). Haalbaar met bestaande beeldherkenning, maar de nauwkeurigheid moet in jouw boomgaard gevalideerd worden tegen je eigen waarnemingen.
3. **Bloemen en vruchten tellen en opbrengst schatten** (computer vision). Dit wordt in onderzoek en door leveranciers toegepast voor appel en kers, maar de nauwkeurigheid hangt af van boomvorm, afstand en licht; hier eerst verzamelen en pas na 1–2 seizoenen beoordelen of het betrouwbaar genoeg is.

**Opstelling (aanbevolen)**
- **1–2 cameraposities per ras/blok**, vast gemonteerd op een paal of boompaal: één *overzichtsbeeld* van een hele boom of een stuk rij en één *close-up* van een vaste tak met bloemen/vruchten.
- **Elke dag op vaste tijd** (bijvoorbeeld rond 12:00 voor gelijkmatig licht), tijdens bloei en kleuring 2–3× per dag. Vaste hoek en afstand; verplaats de camera nooit midden in het seizoen.
- **Referentie in beeld**: een grijs/kleurenkaartje en een lat of markering voor schaal, zodat kleur en grootte vergelijkbaar blijven.
- **Tijdstempel en cameranummer in de bestandsnaam** (bv. `rij12_overzicht_2027-04-18_1200.jpg`). Resolutie minimaal ca. 12 MP voor vruchten van dichtbij; weerbestendig, op zonnepaneel met 4G of wifi. Een gewone wildlife-/trailcamera werkt voor het begin vaak al.
- **Foto's blijven lokaal opgeslagen** (zoals de logboeken: eigen bedrijfsdata, niet openbaar). Maak een kopie op een tweede schijf.
- **Handmatige waarheid ernaast**: schrijf wekelijks de BBCH-stadia en bij oogst de kilo's op. Zonder die waarheid kan een beeldmodel niet leren of controleren.
- Drone of satelliet (NDVI/groeikracht per rij) kan later aanvullen maar is voor een eerste jaar niet nodig.

**Eerlijk over de verwachting**: het verzamelen van de foto's is in 2027 het doel. Een geautomatiseerde analyse vraagt eigen ontwikkeling of een leverancier en bewijst zich pas met data uit minstens één seizoen waarvan je de uitkomst kent.

<a id="sec-h5"></a>
## H.5 Wat wanneer: jaarkalender 2027

| Periode | Meten en vastleggen |
|---|---|
| **Nov–feb (rust)** | Bodemanalyse (als het niet in het najaar kon); sensoren, loggers en camerapalen plaatsen en testen; rij-/boomnummering; je logboek 2025 verifiëren; koude-uren worden automatisch berekend (loggers valideren de weer-API); schade en bladval-notities; snoeiplan |
| **Maart–knopzwelling** | Camera's aan; eerste fenologie-notities; bodemvocht-sensoren aan; kalk/borium/zwavel-ingrepen digitaal noteren; vallen voor vroege plagen klaarzetten |
| **Bloei (eind maart–april)** | Minimum-temperatuur elke 10–15 min loggen; na elke koude nacht % beschadigde bloemen tellen en foto; bestuiving: aantal volken, plaatsingsdatum, vlucht bij welke temperatuur; BBCH wekelijks |
| **Vruchtzetting (april–mei)** | Vruchtzetting % op vaste takken; scouting luis/spint/bladziekten wekelijks; hagelschade-foto; kersenvlieg-platen ophangen; bespuitingen + weer + effect |
| **Groei en rijping (mei–juni/juli)** | **Suzuki-vallen vóór het kleuren, wekelijks tellen**; bodemvocht en beregening bijhouden; foto's 2–3× per dag tijdens kleuring; regen vlak voor oogst: barst-percentage na elke bui; **juli: bladmonster** |
| **Oogst** | Per pluk: kg, klasse, maat, Brix, stevigheid, % barst/made/schade, uren; afzetprijs; foto's van schade |
| **Aug–sep (nazorg)** | Bladvoeding en bemesting digitaal noteren; evaluatie van het seizoen (wat ging goed/slecht; vaste vragen); sensor- en foto-data veiligstellen |
| **Okt–nov (bladval)** | Bodemmonster (zelfde tijdstip elk jaar); bladvalnotitie (begin/50%/einde); koper-/zinkrondes met weer en bladstadium vastleggen |

<a id="sec-h6"></a>
## H.6 Wat de adviseur met elke meting doet

| Meting | Gebruikt door | Effect |
|---|---|---|
| Bodemvocht, regenmeter, beregening | waterbalans ([G.29](#sec-g29)) | Kalibreert TAW, wortelzone en stressdrempel; "te droog/te nat" wordt een meting in plaats van een schatting |
| Bodemanalyse, bladanalyse | bemestingsadvies, Patroonherkenning ([G.8](#sec-g8)) | Bodem-pH-waarschuwing (nu een placeholder), bemesting op werkelijke tekorten |
| Weer op het perceel, bladnat | vorstrisico, ziektemodellen, koude-uren | Echte perceelwaarden in plaats van API-waarden voor een stationsplek |
| Fenologie + camera | koude-uren/graaddagen-model, oogstvoorspelling | Voorspelt bloei en oogst per ras, kalibreert de modellen ([B.1](#sec-b1)) |
| Vallen, scouting | Suzuki-/kersenvlieg-risico | Spuitmoment op basis van waargenomen druk |
| Spuitregistratie + effect | logboek-kalender ([G.30](#sec-g30)), reward-functie ([G.28](#sec-g28)) | "Wat werkte" is voor het eerst te zien; echte beloningssignalen voor DPO |
| Oogst + kwaliteit + economie | evaluatie en training | De kern van "maximale opbrengst": koppeling ingreep → uitkomst; basis voor SFT/DPO die echt op opbrengst optimaliseert ([C.7](#sec-c7)) |

<a id="sec-h7"></a>
## H.7 Starterspakket (als je klein wilt beginnen)

1. **Oogst per pluk wegen en noteren** (H.2 #1) en na elke bui het barstpercentage schatten.
2. **Eén bodem- en één bladanalyse** (H.2 #2–3).
3. **Regenmeter en 2 bodemvochtsensoren** + een **minimum-temperatuurlogger** voor de bloei.
4. **Suzuki-vallen en gele platen** wekelijks tellen.
5. **Wekelijkse fenologie-notitie** (BBCH of simpel) en **1 camera** op een vaste plek.
6. **Elke behandeling** met de velden uit H.3 G noteren (ook *werkte het?* 0–3).
7. **Seizoensevaluatie** in november: vijf vaste vragen (wat ging goed, wat ging mis, wat kostte het, wat doe ik volgend jaar anders, wat miste ik aan gegevens).

<a id="sec-h8"></a>
## H.8 Wat wij bouwen om dit te ontvangen (nog niet gebouwd)

- **Invoerpagina's** in de app (lokaal): oogstregistratie, scouting/valtelling, schadescore, spuit- en bemestingsregistratie met "werkte het?", seizoensevaluatie; elk met datum + perceel/rij, validatie van eenheden en een export naar CSV.
  De spuitregistratie koppelt aan de Ctgb-opzoektool ([G.31](#sec-g31)): bij het kiezen van een middel verschijnen limieten (aantal, interval, veiligheidstermijn, periode) en wordt de invoer er direct tegen getoetst.
- **Import van sensor- en loggerbestanden** (CSV) met controle op gaten en onmogelijke waarden, en weergave naast de waterbalans en het vorstrisico.
- **Foto-opslag lokaal** met een eenvoudig overzicht per camera en dag, en een invoerveld voor de handmatige BBCH-waarheid.
- **Kalibratie** zodra er een seizoen met uitkomsten is: Kc, wortelzone en drempels van de waterbalans, graaddagen voor bloei en oogst, en het Suzuki-/barstrisico, elk met een eerlijke vergelijking van voor en na.
- Pas daarna zinvolle **DPO/SFT op uitkomsten** (zie [G.28](#sec-g28)): zonder echte uitkomsten blijft de beloning een proxy.

---

<a id="deel-i"></a>
# Deel I — Plan voor seizoen 2027: fases, beslismomenten, bouwlijst, succescriteria en risico's

*Dit deel past de roadmap ([Deel E](#deel-e)) aan op de stand van 2026-10-10. Het is een plan, geen status: houd de statussen hieronder bij zodra iets af is. Wat de teler vastlegt staat in [Deel H](#deel-h); hier staat wat wij bouwen, in welke volgorde en wanneer we beslissen.*

<a id="sec-i0"></a>
## I.0 Doel van seizoen 2027

1. **Alles wat gemeten of gedaan wordt komt in één lokaal datamodel**, per blok/rij/ras en per datum: behandelingen, scouting en vallen, fenologie, sensoren, foto's, schade, oogst en economie. Het logboek van 2013–2025 blijft de historie, 2026 en verder komt er digitaal bij.
2. **De adviseur geeft een verifieerbaar "deze week"-overzicht**: fenofase, weer en vorstrisico, waterbalans, plaagdruk, wat je rond deze tijd gewoonlijk deed ([G.30](#sec-g30)) en welke middelen nu mogen ([G.31](#sec-g31)), elk met bron en kaart. Het blijft ondersteuning; de teler beslist.
3. **Na het seizoen: kalibreren op uitkomsten en pas dan trainen.** Eén seizoen met echte uitkomsten (kilo's, klasse, barst, schade) laat zien welke modelparameters kloppen en geeft eindelijk een echt beloningssignaal voor SFT/DPO ([G.28](#sec-g28)).

<a id="sec-i1"></a>
## I.1 Beginstand (2026-10-10)

| Onderdeel | Status |
|---|---|
| Deterministische kern (koude-uren, graaddagen, vorst, Suzuki, barstrisico) | ✅ gebouwd, nog niet gekalibreerd op uitkomsten |
| Waterbalans met 7-daagse vooruitblik en tool | ✅ ([G.29](#sec-g29)), grondsoort en wortelzone zijn aannames |
| RAG, kennisgraaf, procedurele graaf, probleem-OAC | ✅ ([G.25](#sec-g25), [G.27](#sec-g27)) |
| Logboek als RAG-bron, logboek-kalender | ✅ lokaal ([G.27](#sec-g27), [G.30](#sec-g30)); **0 van 487 regels geverifieerd; 2026 staat er nog niet in** |
| Ctgb-opzoektool met kaart, `middel_opzoeken`, praktijkcontrole | ✅ ([G.31](#sec-g31)); label-PDF's alleen gelinkt |
| Eval, reward, rejection sampling, SFT v2 | ✅ ([G.28](#sec-g28)); `sft_v2` nog niet de standaard, held-out n = 31 |
| vLLM op de pod, laadmelding, één engine tegelijk | ✅ ([G.28](#sec-g28)) |
| Invoerpagina's voor oogst, scouting, vallen, schade, evaluatie | ❌ ([H.8](#sec-h8)) |
| Sensor- en foto-import | ❌ |
| Privé, beveiligde invoerinstantie | ❌ ([Deel F](#deel-f) 22) |
| Compliance-poort (middelnaam in antwoord ⇒ Ctgb-aanroep in dezelfde beurt) | ❌ (ontworpen in [B.11](#sec-b11)/[G.31](#sec-g31)) |
| Multi-hop-orchestrator met deterministische poort | ❌ (ontwerp in [G.31](#sec-g31)) |
| Bodem-API (BOFEK) | ❌ stub |
| Oogst-/opbrengstuitkomsten | ❌ blokkerende leemte ([C.7](#sec-c7), [Deel F](#deel-f) 9) |

<a id="sec-i2"></a>
## I.2 Besluiten die vóór 1 december 2026 nodig zijn

| # | Besluit | Aanbeveling | Waarom nu |
|---|---|---|---|
| **D1** | Waar vindt datainvoer plaats? | Een **privé, beveiligde instantie** (login of VPN) voor invoer in het veld; de publieke pod blijft een alleen-lezen spiegel zonder bedrijfsdata. Een tweede, aparte Streamlit-service met eigen data-map, of lokaal-eerst met upload vanaf de telefoon. | De huidige schrijfbare verificatiepagina met database en scans staat open op de publieke URL ([Deel F](#deel-f) 22); zodra er oogst- en spuitdata bijkomt wordt dat een echt datalek-risico |
| **D2** | Datamodel en opslag | Eén lokale SQLite `orchard_records.db` naast de logboek-DB (gitignored, dezelfde `AgentPaths`-discipline), met tabellen per soort meting en een gedeelde sleutel blok/rij/boom + datum. Foto's in een map, met pad *relatief* aan een `AgentPaths`-root (de les van [G.19](#sec-g19)). | Alles wat later volgt (kalibratie, kalender, training) leest hieruit; een latere herstructurering kost veel |
| **D3** | Welke sensoren en camera's | Het **starterspakket** ([H.7](#sec-h7)); uitbreiden na het eerste seizoen. Besluit hangt af van budget en wie het beheert ([Deel F](#deel-f) 28). | Plaatsen kan in de rust (dec–feb); in de bloei is het te laat |
| **D4** | Productie-adapter | `W0_base` blijft de standaard totdat `sft_v2` een gesprekstest (meerdere beurten, met tools) en een grotere held-out set (n ≥ 60) heeft doorstaan. | Zie de open punten van [G.28](#sec-g28); voorkomt een regressie in het seizoen |
| **D5** | De pod over de winter | Houden voor de publieke spiegel en de modeldienst, trainen alleen bij een gepland trainingsvenster (de GPU wordt dan gedeeld, zie G.28). Kosten en gebruik laten de teler beoordelen. | Bepaalt of er in de rust getraind en geëvalueerd kan worden |
| **D6** | Wie verifieert het logboek en wanneer | Vaste blokjes (bijv. 1 uur per week) in de rust, eerst 2025 en de middelen die in het advies terugkomen (Syllit, koper, ureum, zwavel). | Alle logboekafgeleide uitspraken staan op onbevestigde transcripties |

<a id="sec-i3"></a>
## I.3 Tijdlijn per fase

| Fase | Teler | Wij bouwen | Poort aan het eind |
|---|---|---|---|
| **F0 · nu – 15 nov 2026** (bladval, nazorg) | rassen- en bloklijst, bodemanalyse, 2026-logboek aanleveren, vragen uit [Deel F](#deel-f) 22–28 beantwoorden, koper-/zinkrondes noteren | besluiten D1–D6 uitwerken; records-DB (D2) en importer voor het 2026-logboek; de verificatieflow (per regel bevestigen of corrigeren) | **P0 (1 dec)**: besluiten genomen, privé-instantie draait, 2026-logboek geïmporteerd |
| **F1 · 15 nov 2026 – feb 2027** (rust) | sensoren, loggers en camera's plaatsen en testen; rij-/boomnummering; logboek verifiëren | **invoerpagina's v1** (spuit/bemesting met Ctgb-toets, scouting/vallen, fenologie, oogst, schade, seizoensevaluatie); sensorimport (CSV) en fotoverwerking; **compliance-poort**; **label-corpus** (Ctgb-gebruiksaanwijzingen → structuur-JSON → RAG, met de parsers uit de Code Library); **backtest** van de kern op 2013–2025 (zie onder); gesprekstest `sft_v2` en grotere held-out set | **P1 (1 mrt) = feature freeze**: invoer werkt op de telefoon, sensoren leveren data, backtest en eval zijn gedraaid |
| **F2 · mrt – apr 2027** (knopzwelling, bloei) | wekelijks fenologie, vorstregistratie, bestuiving, schade-foto's | "**deze week**"-overzicht; vorst- en Suzuki-meldingen (e-mail of push) uit de deterministische kern; bugfixes, geen nieuwe functies | **P2 (15 mei)**: gebruik in de bloei geëvalueerd (hoeveel invoer, welke fouten) |
| **F3 · mei – jul 2027** (vruchtzetting, groei, oogst) | vallen wekelijks tellen, scouting, bespuitingen + effect, oogst per pluk, bladmonster in juli | **multi-hop-orchestrator v1** (spuitkandidaten met poort); waterbalans naast sensoren; barst-/Suzuki-risico naast waarnemingen | **P3 (1 aug)**: oogstdata compleet en gecontroleerd |
| **F4 · aug – nov 2027** (nazorg, evaluatie, training) | seizoensevaluatie, bodem- en bladmonster, bladvalnotities | **kalibratie** (fenologie/graaddagen, waterbalans, barstrisico, Suzuki) met een eerlijke voor-en-na-vergelijking; **reward v2** met echte uitkomsten; trainingsdata uit 2027; **SFT v3 / DPO** | **P4 (1 nov)**: go/no-go voor een productie-adapter op basis van eval + gesprekstest |

**Backtest (F1, goedkoop en nu al mogelijk)**: draai de deterministische kern en de risicoregels op het weer van 2013–2025 (Open-Meteo-archief) en leg ze naast wat de teler deed. Bijvoorbeeld: werd een vorstnacht of Suzuki-risico gesignaleerd in de dagen voor een ingreep, en hoe vaak werd er gespoten zonder signaal? Dat is geen opbrengstmeting,
maar het toetst de regels en laat zien waar ze te streng of te los zijn, nog vóór het seizoen begint.

<a id="sec-i4"></a>
## I.4 Bouwlijst, op volgorde (omvang: S ≈ dagdeel, M ≈ dagen, L ≈ week of meer)

| # | Onderdeel | Omvang | Hangt af van |
|---|---|---|---|
| 1 | Privé-instantie met login (D1) en `orchard_records.db` (D2), `AgentPaths` uitbreiden | M | besluit D1/D2 |
| 2 | Importer en verificatieflow voor het 2026-logboek (en 2025 verifiëren) | M | 1 |
| 3 | Invoerpagina's v1: spuit/bemesting (met Ctgb-toets en praktijkcontrole), scouting/vallen, fenologie, oogst, schade, seizoensevaluatie, export naar CSV | L | 1 |
| 4 | Sensor-/loggerimport met controle op gaten en onmogelijke waarden; fotoverwerking met overzicht per camera en dag | M | 1 |
| 5 | **Compliance-poort**: noemt een antwoord een middelnaam, dan moet er in dezelfde beurt een `ctgb_toelating`/`middel_opzoeken`-aanroep zijn, anders volgt een disclaimer; plus merknaam-vragen in de eval | S | — |
| 6 | **Label-corpus**: Ctgb-gebruiksaanwijzingen en besluiten (PDF-links uit de API) → structuur-JSON → QC → RAG, zodat bijenregels, mengadviezen en etiketteksten citeerbaar zijn | M | Code Library ([G.26](#sec-g26)) |
| 7 | **Multi-hop-orchestrator** "spuitkandidaten": situatie → probleem → kandidaten uit eigen historie → deterministische poort (toegestane maand en BBCH nu, interval en aantal tegen je laatste toepassing, veiligheidstermijn tegen verwachte oogst, bloeifase/bijen, werkzame stof per seizoen voor resistentie) → uitleg ([G.31](#sec-g31)) | L | 5, 6 |
| 8 | "Deze week"-overzicht (kalender + fenofase + weer + waterbalans + poort-uitkomst) | M | 3, 7 |
| 9 | Meldingen (e-mail/push) bij vorstrisico in de bloei en bij Suzuki-risico; dagelijkse samenvatting optioneel | M | 1 |
| 10 | Kalibratieraamwerk: een functie per model die uitkomsten vergelijkt met voorspellingen (bandbreedte, geen schijnprecisie bij één seizoen) | M | 3, 4 (en seizoensdata) |
| 11 | Eval uitbreiden: held-out n ≥ 60, gesprekken met meerdere beurten en tools, merknaam- en multi-hop-scenario's, vaste regressiepoort vóór elke adapterwissel | M | — |
| 12 | Tooling voor training: de nieuwe tools (`waterbalans`, `logboek_kalender`, `middel_opzoeken`, Ctgb-kaart) in de SFT-prompts en trainingsdata opnemen; **let op: dit verandert de tool-prompt, dus een nieuwe SFT-ronde is nodig voordat ze standaard in productie mee gaan** | M | 11 |
| 13 | Streaming-lusbeveiliging (nu alleen het opgeslagen antwoord wordt opgeschoond, [G.28](#sec-g28)) | S | — |
| 14 | Bodem-API (BOFEK) i.p.v. een stub | S | optioneel |
| 15 | SFT v3 / DPO op 2027-data en echte uitkomsten | L | F4 |

<a id="sec-i5"></a>
## I.5 Succescriteria (meetbaar, per poort)

| Poort | Criteria |
|---|---|
| **P0** | Besluiten D1–D6 vastgelegd; privé-instantie bereikbaar met login; publieke spiegel bevat geen bedrijfsdata; 2026-logboek geïmporteerd en gedeeld met de dubbele-regel-controle van [G.30](#sec-g30) |
| **P1** | Een invoer (behandeling, pluk, valtelling) kost de teler ≤ 1 minuut op de telefoon; sensoren leveren ≥ 95% van de uurwaarden in een testweek; backtest gedraaid en vastgelegd; guardrail-eval ≥ 95% en held-out dekking niet slechter dan de huidige standaard; gesprekstest `sft_v2` gedaan |
| **P2** | ≥ 90% van de behandelingen en bijna alle vorstnachten in de bloei digitaal geregistreerd binnen 24 uur; geen meldingsfouten die tot een gemiste vorstwaarschuwing leidden |
| **P3** | 100% van de plukken geregistreerd met kilo's en klasse; vallen wekelijks geteld in ≥ 90% van de weken tussen kleuring en oogst; sensor-uptime ≥ 90% |
| **P4** | Kalibratieverslag per model met voor/na; reward v2 beschreven; een adapter alleen naar productie als de eval en de gesprekstest beter of gelijk zijn én de guardrail ≥ 95% blijft |

<a id="sec-i6"></a>
## I.6 Risico's en tegenmaatregelen

| Risico | Tegenmaatregel |
|---|---|
| **Invoerlast** voor de teler (de belangrijkste reden dat dit mislukt) | ≤ 1 minuut per invoer, voorgevulde velden (laatste middel, standaardblok), telefoonvriendelijk, geen dubbele invoer; eerst alleen de top-10 uit [H.2](#sec-h2) |
| **Datalek** door bedrijfsdata op de publieke pod | D1: aparte, beveiligde instantie; publieke spiegel zonder database, scans of instellingen |
| **Eén seizoen is weinig data** | kalibreren als bandbreedte, niet als exact getal; modellen blijven deterministisch en citeerbaar; geen training die uitkomsten "leert" uit één jaar zonder controle |
| **Sensoruitval of drift** | controles op gaten en onmogelijke waarden; vergelijking met de weer-API; handmatige controlemeting in het begin |
| **Ctgb-API wijzigt of valt weg** | schijf-cache, storingsmelding, nooit een verzonnen status ([G.31](#sec-g31)); label-corpus als tweede bron |
| **Regressie door een nieuwe adapter** | eval- en gesprekstest als vaste poort (I.4 #11), `W0_base` als terugvaloptie |
| **Schijnzekerheid bij adviezen** | elke uitspraak met bron en kaart; praktijkcontrole en middelkeuze zijn ondersteuning, de teler beslist; de rood/groen-grounding is een heuristiek ([Deel F](#deel-f) 12) |
| **Onbevestigde logboektranscripties** | verificatie als vaste taak (D6); uitspraken uit het logboek melden dat het niet geverifieerd is |

<a id="sec-i7"></a>
## I.7 Wat we in 2027 bewust niet doen

- **Geen autonoom spuitadvies of spuitopdracht**; de adviseur toont opties, regels en historie.
- **Geen beeldmodel in productie**; foto's worden verzameld, gelabeld en pas na een seizoen beoordeeld ([H.4](#sec-h4)).
- **Geen multi-teler-platform** (single-tenant blijft, [Deel F](#deel-f) 7).
- **Geen training op proxy-signalen als er echte uitkomsten komen**; DPO wacht tot er een echt beloningssignaal is.

<a id="sec-i8"></a>
## I.8 Eerstvolgende stappen (deze en volgende week)

1. De teler beantwoordt de vragen in [Deel F](#deel-f) 22–28 en levert het 2026-logboek, de blokindeling en de rassenlijst aan.
2. Besluit D1 (privé-instantie) nemen en uitwerken; dat is de voorwaarde voor al het andere.
3. De records-database (D2) en de importer voor het 2026-logboek bouwen, daarna de verificatieflow.
4. Het starterspakket van [H.7](#sec-h7) bestellen en een plaatsingsplan voor de rust maken.
5. De compliance-poort (I.4 #5) en de backtest (I.3) oppakken: klein, onafhankelijk en nu al waardevol.
