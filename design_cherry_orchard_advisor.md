# Ontwerp: Kersenboomgaard Adviseur (Cherry Orchard Advisor) — Track 1 (Orchard domain)

**Status (2026-10-09): ONTWERP + GROTENDEELS GEÏMPLEMENTEERDE WALKING SKELETON.** Dit document is
begonnen als zuiver ontwerp (Deel A-F, 2026-10-08) vóórdat er één regel implementatiecode was
geschreven — analoog aan hoe `design_captain_missions.md` en `design_chief_engineer.md` in het
Auto Pilot-project zijn opgezet (zie `C:\Users\jcsch\Documents\Python\Auto Pilot`). Sindsdien is een
aanzienlijk deel van Fase 0-3 van de roadmap ([Deel E](#deel-e)) daadwerkelijk gebouwd, getest en
gedeployed (lokaal + een publieke read-only cloud-demo) — zie **[Deel G — Implementatiestatus](#deel-g)**
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
  boven voor de reden waarom dit Mistral verving.
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
| **📈 Patroonherkenning** (toegevoegd 2026-10-09) | Drie lagen: (1) seizoenswaarschuwingen (wijkt het gekozen seizoen tot nu toe af van voorgaande jaren qua weer/plaagdruk/bestuivingsweer?), (2) preventieve weer-naar-ziekte-signalen (lijkt het weer van de laatste dagen op wat vroeger een uitbraak voorafging?), (3) automatisch gerangschikte meerjaren-trendpatronen + een altijd-getoonde teeltkalender — alles met doorklik naar de onderliggende logboekregels. Logica in `pipeline/orchard_patterns.py` + `pipeline/orchard_season_watch.py` + `pipeline/orchard_disease_weather_links.py` (alle drie puur, los getest), UI in `app/pages/8_Patroonherkenning.py` | nieuw (geen directe mirror — Orchard-specifiek; vergelijkbaar in geest met Chief Engineer's `KNOWN_LIMITS`/anomaliedetectie, maar dan over het eigen episodische logboek i.p.v. vaste technische drempels) |
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
| **Track 1-kennisbank (Fase 2, zie [G.5](#sec-g5))** | `Data/Orchard/OrchardKnowledge/<categorie>/*.pdf`/`.html` + `manifest.json` | **7 documenten acquired, 3 bewust geblokkeerd-en-gedocumenteerd, 0 failed.** WUR: `wur_teelthandleidingen_139993.pdf`, `wur_onderstammenproef_zoete_kers_297528.pdf`, `biofruitnet_zoete_kers_onderstammen_nl.pdf` (EU Horizon 2020-project, niet WUR zelf maar in dezelfde map). USDA: `usda_agriculture_handbook_442_sweet_cherries_1973.pdf` (1973, GovInfo, public domain — vervangt de niet-gevonden pre-1930 Farmers' Bulletin 776). Overig: `netafim_kersen_buiten_adviesrapport_2021.pdf` (commercieel, expliciet als zodanig gelabeld), `osu_em9267_spotted_wing_drosophila.pdf` (Oregon State University Extension, Engelstalig, grondt de suzukii-risicofunctie). Geblokkeerd: Ctgb-bulk-export (dode URL), Actua Steenfruit-archief (alleen de 2 al-bezeten nummers, rest achter inlogmuur), pre-1930 USDA-bulletin (geen werkende link gevonden, niet geforceerd). **Bekend, nog open issue**: de eerst-gedownloade EU 2018/848-pagina bleek per ongeluk Engelstalig (zie [Deel F](#deel-f) punt 8) en is expliciet uitgesloten van de RAG-index. |

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

**Implementatiestatus (2026-10-09)**: geen van deze bronnen is operationeel aangesloten als live tool
— `check_ctgb_toelating()` is een bewuste `NotImplementedError`-stub (zie [B.11](#sec-b11): nooit een
verzonnen toelatingsstatus). Bij navraag (2026-10-08) bleek de veelgeciteerde Ctgb-bulk-export-URL
hieronder **dood** (DNS-fout) en `toelatingen.ctgb.nl` zelf een 403'd JS-vereiste SPA — dit blijft een
open gat. EUR-Lex is wél bevraagd voor Reg. 2018/848 ([C.1](#sec-c1)), maar leverde onbedoeld
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
- **Ctgb-toelatingsdata**: bulk-export-URL bleek dood (zie [C.5](#sec-c5)) — blijft een open gat,
  `check_ctgb_toelating()` is en blijft een expliciete stub.
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
│       ├── Orchard_JSON/                  ← GITIGNORED, regenereerbaar: geparste Track 1-documenten
│       │   (per-document JSON, output van parse_orchard_documents.py)
│       ├── Orchard_Agents_Training/       ← GITIGNORED, regenereerbaar: RAG-index
│       │   (orchard_rag_chunks.json, orchard_rag_embeddings.npy, orchard_rag_chunk_ids.json)
│       ├── Orchard_Eval/                  ← held-out gold Q&A + scenario's (NOG NIET aangemaakt)
│       └── orchard_settings.json          ← GITIGNORED: persisted lat/lon/adres (echte boomgaardlocatie)
├── _models/
│   ├── hf_cache/                          ← gedeeld, GITIGNORED
│   └── Orchard/                           ← toekomstige fine-tuned Qwen3-8B-adapters (nog leeg)
├── app/                                   ← Streamlit-app
│   ├── Home.py
│   ├── orchard_common.py                  ← gedeelde helpers: AgentPaths, sidebar, settings, weer-popup
│   └── pages/
│       ├── 1_Boomgaard_Dashboard.py
│       ├── 2_Vraag_de_Adviseur.py
│       ├── 3_Seizoensplanning.py
│       ├── 4_Logboek.py
│       ├── 5_Waarschuwingen.py
│       ├── 6_Logboek_Verifieren.py        (op de publieke pod: hernoemd naar `_6_...py.disabled`)
│       ├── 7_Bibliotheek.py
│       ├── 8_Patroonherkenning.py
│       ├── 9_Gebruik_van_Middelen.py
│       ├── 10_Help.py                     ← nieuw, zie G.10
│       └── 11_Instellingen.py             ← nieuw, zie G.15 (locatie/ras/fase, uit de zijbalk gehaald)
├── core/
│   ├── paths.py                           ← AgentPaths(domain="Orchard")
│   ├── io.py, qwen_loader.py
├── pipeline/
│   ├── orchard_phenology_spec.py          ← deterministische kern (koude-uren/GDD/vorst/suzukii/barst)
│   ├── orchard_tools.py                   ← Open-Meteo/Buienradar/geocoding/Ctgb-stub/bodem-stub
│   ├── orchard_rag.py                     ← RAG-retrieval + reranking (Fase 3)
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
│       ├── parse_orchard_documents.py     ← Track 1: PDF/HTML -> genormaliseerd JSON
│       └── build_orchard_rag.py           ← Track 1: chunken + embedden -> RAG-index
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
   geverifieerde data-ophaal-functies. — ✅ **GEDAAN voor weer/neerslag/geocoding**; Ctgb/bodem blijven
   bewuste stubs (zie [C.4](#sec-c4)/[C.5](#sec-c5)).
4. **RAG v0**: alleen Track 1 (WUR/Actua Steenfruit/Ctgb), nog zonder logboeken. — ✅ **GEDAAN**
   (7 documenten, dense retrieval + reranking, zie [G.5](#sec-g5)/[G.6](#sec-g6)).
5. **Eerste Mistral-SFT**: basis vraag-antwoord-gedrag op Track 1-data. — ⬜ **NOG NIET GESTART.**
   Qwen3-8B draait wel al live (basismodel, geen fine-tuning), met RAG+tools+CoT als tussenstap i.p.v.
   te wachten op een trainingsronde — zie de afwijking hierboven en [G.6](#sec-g6).
6. **Track 2 erbij**: zodra OCR klaar is, logboek-RAG + conversational SFT-data toevoegen. — 🟡
   **DEELS**: de logboek-data wordt al live gebruikt door Patroonherkenning/Seizoenswaarschuwingen/
   Gebruik van Middelen ([G.7](#sec-g7)-[G.9](#sec-g9)), maar nog niet als RAG-bron voor de chatbot
   zelf, en nog geen conversational-SFT-dataset gebouwd.
7. **DPO**: biologisch-vs-chemisch-voorkeur. — ⬜ **NOG NIET GESTART** als trainingsstap; wel is er nu
   een UI-mechanisme om voorkeursparen te VERZAMELEN (duim omhoog/omlaag op elk antwoord, zie
   [G.6](#sec-g6)) — de daadwerkelijke DPO-trainingsronde zelf volgt later, zodra er genoeg paren zijn.
8. **Streamlit-dashboard v0**: alleen het Boomgaard Dashboard + Chat-pagina. — ✅ **GEDAAN, en ver
   voorbij v0**: 10 pagina's totaal, zie [B.9](#sec-b9)/[G.10](#sec-g10).
9. **Evaluatie + ablaties**: pas zinvol zodra stap 1–7 staan. — ⬜ **NOG NIET GESTART** (geen gouden
   eval-set, zie [Deel F](#deel-f) punt 5/9); 139 UNIT-tests bestaan wel (zie [G.11](#sec-g11)), maar
   dat is iets anders dan een agronomische kwaliteits-evaluatie.

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
- **Publieke read-only deployment**: nginx reverse-proxy (poort 80/443 → Streamlit's interne 8501),
  twee systemd-services (`orchard-streamlit`, `orchard-qwen`) zodat beide overleven na
  SSH-disconnect/reboot. De schrijfbare Logboek-Verifiëren-pagina is op de pod uitgeschakeld door het
  bestand te hernoemen naar `_6_Logboek_Verifieren.py.disabled` (Streamlit negeert bestanden die met
  `_` beginnen — geen code verwijderd, alleen onzichtbaar voor de publieke pagina-navigatie) en de
  database-file is `chmod 444` gezet.
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
  een paar minuten een vervolgvraag stelt niet steeds opnieuw de laadtijd betaalt.

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
- `app/pages/4_Logboek.py`: doorzoekbaar op jaar/middel/zekerheid, met een weer-contextknop per entry.
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
- UI: `app/pages/8_Patroonherkenning.py`, met drill-down naar de onderliggende logboekregels per
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
- UI: `app/pages/9_Gebruik_van_Middelen.py`, met gestapelde grafieken per categorie en drill-down per
  product naar de onderliggende logboekregels.

<a id="sec-g10"></a>
## G.10 Bibliotheek, Help en overige UI-afwerking

- `app/pages/7_Bibliotheek.py`: lijst van en toegang tot de Track 1-kennisbank (download +
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
samenhangende features toegevoegd, allemaal in `app/pages/2_Vraag_de_Adviseur.py` +
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
