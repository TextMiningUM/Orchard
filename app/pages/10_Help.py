"""Help (design doc Sec B.9/G.10) -- gebruikersgerichte documentatie, GEEN technische uitleg.
Puur statische tekst, geen logica; richt zich op de teler als eindgebruiker.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchard_common import render_sidebar  # noqa: E402

import streamlit as st

st.set_page_config(page_title="Help", layout="wide")
st.title("Help")
st.caption("Een overzicht van wat elke pagina doet en hoe je 'm gebruikt.")

render_sidebar(st)

st.markdown(
    """
Dit is de **Kersenboomgaard Adviseur**: een systeem dat helpt om op het juiste moment de juiste
beslissing te nemen in de boomgaard, op basis van het weer, de fenologische fase van de bomen, je
eigen logboek-geschiedenis, en vakkennis uit betrouwbare bronnen (WUR, USDA, en anderen).

Gebruik het menu aan de linkerkant om tussen de pagina's te wisselen. Hieronder per pagina wat je
ermee kunt.
"""
)

with st.expander("Boomgaard Dashboard", expanded=True):
    st.markdown(
        """
De startpagina met de actuele status van je boomgaard: hoeveel koude-uren zijn er al opgebouwd dit
seizoen, wat is het nachtvorstrisico voor de komende dagen, en wat zijn de belangrijkste cijfers in
één oogopslag.

Onderaan de pagina kun je ook het weer van de **afgelopen** periode bekijken (schuifbalk om de
periode aan te passen) — handig om terug te kijken, al is het aankomende weer meestal belangrijker.
"""
    )

with st.expander("Vraag de Adviseur"):
    st.markdown(
        """
Stel hier een vraag in gewone taal, bijvoorbeeld *"is er vorstrisico deze week?"* of *"wat zegt de
kennisbank over onderstammen bij zoete kers?"*. Veelvoorkomende vragen (vorst, regen, koude-uren,
kersenvlieg/suzuki, vruchtbarsten, middel/toelating) worden direct en betrouwbaar beantwoord op basis
van actuele data. Alle andere vragen gaan naar het AI-model, dat ook de kennisbank en dezelfde
rekentools mag raadplegen voor een onderbouwd antwoord.

**Wat je ziet bij elk antwoord:**
- **Redenering (CoT)** — een inklapbaar blokje met de stap-voor-stap-overweging van het model, als
  je wilt zien *hoe* het tot het antwoord kwam.
- **Tools gebruikt** — welke rekentools (bijv. weer of koude-uren) het model heeft geraadpleegd.
- **Groen/rood-indicator "GEGROND"/"GEEN GROUNDING GEVONDEN"** — groen betekent dat het antwoord
  aantoonbaar een bron of tool-resultaat gebruikt; rood betekent dat er geen bron/tool-resultaat aan
  te pas kwam voor dit specifieke antwoord — wees dan extra kritisch, want het model kan dan iets
  verzinnen (een "hallucinatie"). **Let op: groen is geen garantie dat het antwoord klopt, alleen dat
  het ergens op gebaseerd is** — controleer belangrijke feiten (middelen, doseringen) altijd zelf.
- **Duim omhoog/omlaag-knoppen** — geef aan of een antwoord bruikbaar was. Dit wordt opgeslagen en
  gebruikt om het model in een latere ronde te verbeteren. Na een klik verschijnt een bevestiging; je
  kunt daarna niet meer wisselen van keuze voor dat antwoord.

Een antwoord duurt soms een halve minuut — zolang de melding *"De adviseur denkt na..."* zichtbaar is,
is het systeem bezig; even geduld dus. Als je een paar minuten niets gevraagd hebt, duurt de eerste
volgende vraag ook langer: het model wordt dan automatisch van het rekenproces afgehaald om geen
onnodige capaciteit vast te houden en moet bij de eerstvolgende vraag opnieuw geladen worden. Dat kost
ongeveer anderhalve minuut extra; de app laat dat dan vooraf zien ("het taalmodel wordt geladen: ongeveer
80 seconden"), en in de zijbalk staat of het model nu geladen is.

Je kunt ook **vervolgvragen** stellen (bijvoorbeeld eerst *"wat is suzuki-fruitvlieg?"* en dan *"en
is dat erg voor kersen?"*) — het model houdt rekening met wat je eerder in dezelfde chat hebt
gevraagd en geantwoord gekregen.

**Chats bewaren en teruglezen:** elke keer dat je de pagina opent, begin je met een nieuwe, lege
chat. In de zijbalk onder "Chats" staan je eerdere chats (automatisch een titel gekregen op basis van
je eerste vraag) — klik erop om die chat weer te openen en verder te gaan waar je gebleven was, of
klik op "Verwijder" om 'm weg te gooien. Klik op "Nieuwe chat" om met een schone lei te beginnen.

Het model is nog **niet** getraind op deze boomgaard specifiek — het is nog het kale basismodel, al
mét toegang tot de kennisbank en de rekentools. Controleer specifieke feiten dus altijd tegen de
genoemde bron.
"""
    )

with st.expander("Seizoensplanning"):
    st.markdown(
        """
Een overzicht van de fenologische fase waarin de boomgaard nu zit (rust, bloei, vruchtzetting, etc.)
en welke gebeurtenissen dit seizoen al zijn voorgekomen.
"""
    )

with st.expander("Logboek & Geschiedenis"):
    st.markdown(
        """
Hier kun je de 14 jaar aan handgeschreven logboeken (2013-2026) doorzoeken — op jaar, op middel, of
alleen de zekere (goed leesbare) regels. Klik op een regel om via de knop eronder het weer rond die
datum te bekijken (een week ervoor en erna): regen, wind, temperatuur — handig om te begrijpen
waarom een bepaalde ingreep toen is gedaan.
"""
    )

with st.expander("Waarschuwingen"):
    st.markdown(
        """
Een lijst van actieve risico's voor de komende week: nachtvorst, vruchtbarsten door regen,
verhoogd suzuki-fruitvlieg-risico, en een eventuele achterstand in koude-uren. Ververs de pagina om
de nieuwste stand te zien.
"""
    )

with st.expander("Logboek Verifiëren"):
    st.markdown(
        """
Hiermee kun je de automatisch overgetypte (getranscribeerde) logboekregels controleren tegen de
originele scan — met de mogelijkheid om de afbeelding te roteren/zoomen als het handschrift lastig
leesbaar is. Alleen zinvol als je de oorspronkelijke scans wilt nalopen; voor dagelijks gebruik kun je
deze pagina overslaan. (Deze pagina is niet beschikbaar op de publieke, alleen-lezen versie.)
"""
    )

with st.expander("Bibliotheek"):
    st.markdown(
        """
Een overzicht van alle vakkennis-documenten die de kennisbank voeden (WUR, USDA, en andere
betrouwbare bronnen) — je kunt elk document direct downloaden of inzien. Handig als je een advies van
de Adviseur verder wilt natrekken in de oorspronkelijke bron.
"""
    )

with st.expander("Patroonherkenning"):
    st.markdown(
        """
Deze pagina zoekt zelf naar opvallende patronen in je logboek-geschiedenis, op drie manieren:

1. **Seizoenswaarschuwingen** — wijkt dit seizoen tot nu toe af van voorgaande jaren? (te warm, te
   droog/nat, ongewoon veel meldingen van een bepaalde ziekte/plaag, slecht weer tijdens de bloei)
2. **Preventieve risico-waarschuwingen** — lijkt het weer van de laatste dagen op wat vroeger een
   ziekte-uitbraak voorafging? Dit is bedoeld om je **vóór** te waarschuwen, niet pas als het al mis
   is.
3. **Meerjaren-trends** — een gerangschikte lijst van de meest opvallende patronen over alle jaren
   heen (bijv. "de dosering van middel X stijgt elk jaar"), plus een altijd-zichtbare teeltkalender
   (wanneer in het jaar komt welk onderwerp typisch voor).

Klik op "Onderliggende logboek-regels bekijken" onder elk patroon om de exacte regels te zien
waarop dat patroon gebaseerd is.

**Kleurcodes**: HOOG, MATIG, INFO (informatief, geen actie per se nodig) staan als tekstlabel bij elk
patroon/elke waarschuwing.
"""
    )

with st.expander("Gebruik van Middelen"):
    st.markdown(
        """
Een overzicht van alle gebruikte middelen (gewasbeschermingsmiddelen én meststoffen/bladvoeding),
automatisch samengevoegd (schrijfwijzen als "Zinc"/"Zink" worden als hetzelfde product geteld) en
ingedeeld in categorieën. Kies boven de grafiek of je het per week, maand, kwartaal of jaar wilt
zien. Onderaan kun je een specifiek product kiezen om alle logboekregels te zien waarin het
voorkomt.

Sommige productnamen waren niet met zekerheid te herkennen — die staan eerlijk onder "overig" in
plaats van geraden te worden.
"""
    )

with st.expander("Instellingen"):
    st.markdown(
        """
Hier pas je de locatie, het ras en de huidige fenologische fase van je boomgaard aan — alle andere
pagina's gebruiken deze instelling (bijvoorbeeld voor het ophalen van het juiste lokale weer). Vul
een adres in en klik op "Zoek & onthoud coördinaten", of voer handmatig breedte-/lengtegraad in. De
locatie wordt onthouden na een herstart van de app; ras en fase controleer je elke sessie opnieuw.
"""
    )

st.divider()
st.subheader("Veelgestelde vragen")

with st.expander("Waarom geeft de Adviseur soms een antwoord met het rode label 'GEEN GROUNDING GEVONDEN'?"):
    st.markdown(
        """
Dat betekent dat het antwoord geen bron of tool-resultaat citeert dat je kunt natrekken. Dat wil niet
per se zeggen dat het antwoord fout is — het kan ook een algemene, voor-de-hand-liggende uitspraak
zijn die geen onderbouwing nodig had — maar wees extra alert bij feitelijke beweringen (getallen,
middelnamen, doseringen) met een rood label.
"""
    )

with st.expander("Waarom kan de Adviseur geen middel/dosering met zekerheid noemen?"):
    st.markdown(
        """
Dit is bewust zo ingebouwd: een verkeerd geadviseerde dosering kan schade of een wettelijke
overtreding veroorzaken. Het systeem is nog niet gekoppeld aan de officiële Ctgb-toelatingendatabank,
dus voor middel/dosering-vragen verwijst het je altijd door naar ctgb.nl.
"""
    )

with st.expander("Wat gebeurt er met mijn duim-omhoog/omlaag-feedback?"):
    st.markdown(
        """
Die wordt lokaal opgeslagen en gebruikt als trainingsmateriaal voor een latere verbeterronde van het
AI-model, zodat het stapsgewijs leert welke antwoorden goed en welke niet bruikbaar waren. Je
logboekgegevens zelf blijven altijd lokaal/privé — niets wordt automatisch gedeeld.
"""
    )

with st.expander("Is dit systeem een vervanging voor mijn eigen kennis/een adviseur?"):
    st.markdown(
        """
Nee. Dit systeem adviseert en legt uit, maar voert niets automatisch uit en vervangt geen formele
Ctgb-raadpleging of een erkend adviseur bij twijfel. Jij blijft eindverantwoordelijk voor elke
beslissing in de boomgaard.
"""
    )
