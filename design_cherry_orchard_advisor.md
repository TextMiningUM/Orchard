# Ontwerp: Kersenboomgaard Adviseur (Cherry Orchard Advisor) — Track 1 (Orchard domain)

**Status (2026-10-08): ONTWERP + DATA-INVENTARISATIE. Geen code geschreven.** Dit document legt het
functionele en technische ontwerp vast voordat er één regel implementatiecode wordt geschreven —
analoog aan hoe `design_captain_missions.md` en `design_chief_engineer.md` in het Auto Pilot-project
zijn opgezet (zie `C:\Users\jcsch\Documents\Python\Auto Pilot`). Dit is bewust het eerste
domein-ontwerp van het Orchard-project; latere domeinen (bijv. een appel- of perenboomgaard) zouden
dezelfde pijplijn met een ander `domain=`-argument moeten hergebruiken, precies zoals VHF/OOW/
Captain/Chief Engineer in Auto Pilot één pijplijn delen.

Bronnen voor dit ontwerp:
- `Docs/Training an Orchard Agentic Chatbot with Real-World Data - Master project 20260322.pdf` (het
  oorspronkelijke project-idee/scriptie-opdracht — leidend voor scope en onderzoeksvragen)
- `Docs/Harnessing Artificial Intelligence for Agricultural Transformation 20260713.pdf` (World Bank
  rapport — bredere context/motivatie voor AI in landbouw)
- `Data/Data Log Books/jaar 2013.pdf` t/m `jaar 2026.pdf` (14 jaar handgeschreven logboeken, gescand —
  tekstextractie leverde nog geen tekst op: dit zijn beeld-PDF's die OCR/multimodale verwerking nodig
  hebben, exact zoals het project-document voorspelt)
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
  - [B.7 Model & training (Mistral, SFT → DPO → Reflection)](#sec-b7)
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
- [Deel D — Mapstructuur `Data/Orchard/` (voorstel, nog niet aangemaakt)](#deel-d)
- [Deel E — Roadmap: walking skeleton eerst](#deel-e)
- [Deel F — Open vragen](#deel-f)

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
## B.7 Model & training (Mistral, SFT → DPO → Reflection)

- **Basismodel**: Mistral (open-weights, zoals gevraagd), vergelijkbare groottes als Auto Pilot's
  Qwen3-8B-aanpak (7–8B-klasse, lokaal/cloud QLoRA-fine-tunebaar).
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

Python-omgeving: **`.venv` met Python 3.13** is al aangemaakt in de projectroot
(`C:\Users\jcsch\Documents\Python\Orchard\.venv`), analoog aan Auto Pilot se eigen
project-lokale `.venv`-conventie. Er is nog geen enkel package geïnstalleerd — dat gebeurt pas zodra
een concreet script die dependency nodig heeft (regel uit de coding-instructies: packages pas
installeren ná wijziging van een dependency-manifest of bij een concrete import-fout).

<a id="sec-b9"></a>
## B.9 Streamlit-UI (mirror van Engine Room / Captain Mission dashboards)

Voorgestelde pagina's, in dezelfde stijl als `Basic Simulator/app/pages/1_Captain_Mission.py` en
`2_Engine_Room.py`:

| Pagina | Doel | Mirror van |
|---|---|---|
| **🍒 Boomgaard Dashboard** | Actuele fenologische status, koude-uren-/GDD-teller, komende verplichte acties, open waarschuwingen | `2_Engine_Room.py` (conditie-annunciator-paneel) |
| **💬 Vraag de Adviseur** | Chat-interface, ReAct-trace zichtbaar (welke tools zijn aangeroepen, welke bronnen geciteerd) | VHF/Chief Engineer chatbot-interfaces |
| **📅 Seizoensplanning** | Fase-overzicht + brown-envelope-eventlog (vorst, hagel, plaagpiek) over het lopende seizoen | `1_Captain_Mission.py` (Mission Briefing/Log) |
| **📖 Logboek & Geschiedenis** | Doorzoekbaar overzicht van 2013–2026, plus invoer van nieuwe ingrepen | nieuw (geen directe mirror — Orchard-specifiek) |
| **⚠️ Waarschuwingen** | Actieve/voorbije alerts (vorst tijdens bloei, regen vóór oogst, kersenvlieg-drempel) | Captain's "brown envelope" monitors |
| **📈 Patroonherkenning** (toegevoegd 2026-10-09) | Automatische detectie van de meest oogst-relevante patronen in het Track 2-logboek (seizoenstiming-verschuiving, behandelfrequentie- en doseringstrends per categorie, plus een altijd-getoonde teeltkalender), met doorklik naar de onderliggende logboekregels. Detectielogica in `pipeline/orchard_patterns.py` (puur, los getest), UI in `app/pages/8_Patroonherkenning.py` | nieuw (geen directe mirror — Orchard-specifiek; vergelijkbaar in geest met Chief Engineer's `KNOWN_LIMITS`/anomaliedetectie, maar dan over het eigen episodische logboek i.p.v. vaste technische drempels) |

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
  "never exceed the Chief-Engineer-declared safe speed"-shield).
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

| API | Dekking | Sleutel nodig? | Gebruik in dit ontwerp |
|---|---|---|---|
| **Open-Meteo Forecast API** (`api.open-meteo.com/v1/forecast`) | Toekomst, tot 16 dagen vooruit; uur- en dagwaarden incl. `precipitation`/`precipitation_sum`, temperatuur, wind | Nee (gratis, tot 10.000 calls/dag niet-commercieel) | **Primaire bron voor `get_weather_forecast`** — vorstwaarschuwing, oogst-/spuitplanning vooruit |
| **Open-Meteo Historical Weather API** (`archive-api.open-meteo.com/v1/archive`) | Verleden, terug tot 1940, uur-/dagwaarden | Nee | **Primaire bron voor `get_weather_history`** — koude-uren/GDD-berekening, kalibratie tegen logboekjaren 2013–2026 |
| **KNMI Open Data Platform / EDR API** (`developer.dataplatform.knmi.nl`) | Officiële NL-weerstation-waarnemingen (historisch, hoge resolutie) | API-key (gratis aan te vragen) | Secundaire/autoritatieve bron voor NL-specifieke historische kalibratie (nauwkeuriger per weerstation dan het Open-Meteo-model) |
| **Buienradar `raintext`-endpoint** (`gpsgadget.buienradar.nl/data/raintext`) | Neerslag-nowcasting, 5-min-resolutie, tot 2 uur vooruit | Nee (niet-commercieel, met bronvermelding) | **`get_rain_nowcast`** — hyperlokale beslissing "kan ik nu nog spuiten voor de bui?" |
| **Bodemdata.nl / BOFEK bodemkaart-API** | Bodemtype/bodemfysische kenmerken per coördinaat | Meestal geen key voor basisgebruik | **`get_soil_info`** — vochthoudend vermogen, bodemtype voor irrigatie-/bemestingsadvies |

> **Aanbevolen combinatie**: Open-Meteo als primaire, consistente bron voor zowel verleden (sinds 1940)
> als toekomst (16 dagen) in één simpele, sleutelloze API — ideaal voor de koude-uren-/GDD-/
> Suzukii-risico-berekeningen die lange historische reeksen nodig hebben. KNMI erbij voor
> NL-specifieke validatie/kalibratie. Buienradar specifiek voor de kortetermijn "ga ik nu wel of niet
> het veld in"-beslissing.

<a id="sec-c5"></a>
## C.5 Juridische/regelgeving-bronnen

| Bron | Wat | Link |
|---|---|---|
| **Ctgb MST Public API** | Programmatische toegang tot toegelaten/vervallen middelen, doseringen, gewasindicaties | docs.mstpublicapi.apiary.io, open source API-spec: github.com/trivento/ctgb-mst-public-api |
| **Ctgb dagelijkse bulk-export** | Volledige Excel-export van alle toelatingen (CC-0-licentie, vrij herbruikbaar) | ctgb.blob.core.windows.net/documents/public-authorisations-report.xls |
| **data.overheid.nl dataset "Bestrijdingsmiddelendatabank"** | Open-datacatalogus-ingang naar dezelfde Ctgb-data | data.overheid.nl |
| **EUR-Lex / ELI** | Reg. (EU) 2018/848 (biologische productie) + overige EU-landbouwrichtlijnen, machine-leesbaar via ELI-links en (beperkt) XML/RDF | eur-lex.europa.eu |

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
- **Bijenvolken-/bestuiverregistratie**: geen historische data hierover aangetroffen; nodig voor het
  bestuiver-shield ([B.11](#sec-b11)).
- **Oogst-/opbrengstcijfers**: het masterproject-document noemt dit expliciet als aparte categorie
  ("Harvest and Yield Records") — nog niet aangetroffen in `Data/`; nodig om advies daadwerkelijk aan
  opbrengst te kunnen koppelen (de kern van "maximale opbrengst" uit de opdracht).

---

<a id="deel-d"></a>
# Deel D — Mapstructuur `Data/Orchard/` (voorstel, nog niet aangemaakt)

Mirror van Auto Pilot's `AgentPaths`-conventie (zie [B.8](#sec-b8)); dit is puur een **voorstel** —
er wordt in deze ontwerpfase nog niets aangemaakt:

```
Orchard/
├── Docs/                                  (bestaand — project-briefings)
├── Data/
│   ├── Data Log Books/                    (bestaand — ruwe PDF/MSG-bronnen, ongewijzigd laten)
│   └── Orchard/                           ← nieuw, data_root
│       ├── OrchardKnowledge/              ← source_dir: WUR/Actua Steenfruit/USDA/EU-wetgeving (vertaald NL)
│       ├── OrchardLogbooks/                ← OCR-output van de 14 jaar scans, gestructureerd JSON
│       ├── Orchard_Eval/                   ← held-out gold Q&A + scenario's (nooit trainen op)
│       │   ├── orchard_gold_qa.json
│       │   └── orchard_scenarios.json
│       ├── Orchard_JSON/                   ← gestructureerde tussen-output (§8-equivalent)
│       └── Orchard_Agents_Training/        ← RAG/KG/PG-index, reasoning traces, SFT/DPO/Reflection-bestanden
├── _models/
│   ├── hf_cache/                          ← gedeeld
│   └── Orchard/                           ← fine-tuned Mistral-adapters/merges
└── .venv/                                  (reeds aangemaakt, Python 3.13)
```

---

<a id="deel-e"></a>
# Deel E — Roadmap: walking skeleton eerst

Mirror van Captain's eigen aanpak (§14 `design_captain_missions.md`, "Approach: walking skeleton
first") — niet alles tegelijk bouwen, maar in deze volgorde:

1. **Data gereedheid**: OCR van de logboeken + JSON-structurering (hoogste prioriteit, blokkeert
   Track 2 volledig).
2. **Deterministische kern v0**: koude-uren + GDD-berekening, gevalideerd tegen 1–2 bekende seizoenen
   uit de logboeken.
3. **Tool-laag v0**: Open-Meteo (verleden+toekomst) + Ctgb-opzoekfunctie, zonder LLM — puur
   geverifieerde data-ophaal-functies.
4. **RAG v0**: alleen Track 1 (WUR/Actua Steenfruit/Ctgb), nog zonder logboeken.
5. **Eerste Mistral-SFT**: basis vraag-antwoord-gedrag op Track 1-data.
6. **Track 2 erbij**: zodra OCR klaar is, logboek-RAG + conversational SFT-data toevoegen.
7. **DPO**: biologisch-vs-chemisch-voorkeur.
8. **Streamlit-dashboard v0**: alleen het Boomgaard Dashboard + Chat-pagina.
9. **Evaluatie + ablaties**: pas zinvol zodra stap 1–7 staan.

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
