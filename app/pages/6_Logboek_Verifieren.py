"""Logboek Verifiëren -- menselijke review/correctie van onzekere transcripties.

De 163 entries die de vision-transcriptie-agents niet met zekerheid konden lezen
(`onzeker = 1`, zie `pipeline/ingest/build_logbook_database.py`) staan hier één voor één
klaar om door de teler te worden gecontroleerd tegen de originele scan. Na correctie en
bevestiging verdwijnt het `onzeker`-label en wordt de entry gemarkeerd als
`geverifieerd = 1` met een tijdstempel -- dit is een audit-trail, geen stille overschrijving:
we WETEN straks welke rijen een mens heeft gecontroleerd en welke nog pure machine-
transcriptie zijn (zelfde "nooit stilzwijgend" discipline als de rest van dit ontwerp, zie
`design_cherry_orchard_advisor.md` Sec B.1/B.11).

Belangrijk: wijzigingen hier gaan direct in `orchard_logbook.db` -- een latere
`build_logbook_database.py`-herbouw weigert deze database te overschrijven zolang er
geverifieerde rijen in staan (tenzij je expliciet `--force` gebruikt).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchard_common import PATHS, get_logbook_conn, render_sidebar, render_weather_dialog_button  # noqa: E402

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Logboek Verifiëren", layout="wide")
st.title("Logboek Verifiëren")

ctx = render_sidebar(st)

DB_PATH = PATHS.logbooks_dir / "orchard_logbook.db"
conn = get_logbook_conn(st)
if conn is None:
    st.error(
        f"Database niet gevonden op `{DB_PATH}`. Bouw 'm eerst met:\n\n"
        "`.venv\\Scripts\\python.exe -m pipeline.ingest.build_logbook_database`"
    )
    st.stop()

st.markdown(
    "Bekijk de originele scan naast de machine-transcriptie, corrigeer waar nodig, en "
    "bevestig — het **onzeker**-label verdwijnt dan en de entry telt vanaf dat moment "
    "als door een mens geverifieerd."
)

# ── Voortgang ────────────────────────────────────────────────────────────────────────────
totaal_ooit_onzeker = conn.execute(
    "SELECT COUNT(*) FROM entries WHERE onzeker = 1 OR geverifieerd = 1"
).fetchone()[0]
n_geverifieerd = conn.execute("SELECT COUNT(*) FROM entries WHERE geverifieerd = 1").fetchone()[0]
n_resterend = conn.execute("SELECT COUNT(*) FROM entries WHERE onzeker = 1").fetchone()[0]

c1, c2, c3 = st.columns(3)
c1.metric("Totaal ooit onzeker", totaal_ooit_onzeker)
c2.metric("Geverifieerd", n_geverifieerd)
c3.metric("Nog te controleren", n_resterend)
if totaal_ooit_onzeker:
    st.progress(n_geverifieerd / totaal_ooit_onzeker)

st.divider()

# ── Filter + volgorde van te verifiëren entries ─────────────────────────────────────────
jaren = [r[0] for r in conn.execute(
    "SELECT DISTINCT p.jaar FROM pages p JOIN entries e ON e.page_id = p.id WHERE e.onzeker = 1 ORDER BY p.jaar"
)]
jaar_filter = st.selectbox("Filter op jaar", ["Alle jaren"] + jaren)

query = """
SELECT e.id FROM entries e JOIN pages p ON e.page_id = p.id
WHERE e.onzeker = 1
"""
params: list = []
if jaar_filter != "Alle jaren":
    query += " AND p.jaar = ?"
    params.append(jaar_filter)
query += " ORDER BY p.jaar, p.pagina, e.id"
remaining_ids = [r[0] for r in conn.execute(query, params)]

if not remaining_ids:
    st.success("Niets (meer) te verifiëren voor dit filter!")
    st.stop()

idx_key = f"verify_idx_{jaar_filter}"
idx = st.session_state.get(idx_key, 0)
idx = max(0, min(idx, len(remaining_ids) - 1))
entry_id = remaining_ids[idx]

st.caption(f"Entry {idx + 1} van {len(remaining_ids)} (dit filter) — id {entry_id}")

# ── Entry + bijbehorende pagina/toepassingen ophalen ────────────────────────────────────
entry = conn.execute(
    "SELECT e.*, p.jaar, p.bestand, p.pagina, p.image_path FROM entries e "
    "JOIN pages p ON e.page_id = p.id WHERE e.id = ?", (entry_id,),
).fetchone()
toepassingen = conn.execute(
    "SELECT middel, hoeveelheid FROM toepassingen WHERE entry_id = ? ORDER BY volgorde", (entry_id,),
).fetchall()

if entry["datum_iso"]:
    render_weather_dialog_button(st, ctx.lat, ctx.lon, entry["datum_iso"], key_suffix=f"verify_{entry_id}")
else:
    st.caption(
        "Geen weer-venster beschikbaar: deze entry heeft nog geen (zekere) ISO-datum "
        "(vul die hieronder in en sla op, dan kan de weer-popup daarna wel)."
    )

col_img, col_form = st.columns([1, 1])

with col_img:
    st.subheader(f"Bron: {entry['bestand']}, pagina {entry['pagina']}")
    if entry["image_path"] and Path(entry["image_path"]).exists():
        rot_key, zoom_key, fit_key = f"rotate_{entry_id}", f"zoom_{entry_id}", f"fit_{entry_id}"
        rotation = st.session_state.get(rot_key, 0)
        fit_to_width = st.session_state.get(fit_key, True)

        rc1, rc2, rc3, rc4 = st.columns([1, 1, 1, 2])
        if rc1.button("-90°", key=f"rot_left_{entry_id}", width="stretch"):
            rotation = (rotation - 90) % 360
            st.session_state[rot_key] = rotation
            st.rerun()
        if rc2.button("+90°", key=f"rot_right_{entry_id}", width="stretch"):
            rotation = (rotation + 90) % 360
            st.session_state[rot_key] = rotation
            st.rerun()
        if rc3.button("Reset", key=f"rot_reset_{entry_id}", width="stretch"):
            rotation = 0
            st.session_state[rot_key] = rotation
            st.session_state[zoom_key] = 100
            st.session_state[fit_key] = True
            st.rerun()
        rc4.caption(f"Rotatie: {rotation}°")

        fit_to_width = st.checkbox("Automatisch passend maken (breedte kolom)", value=fit_to_width, key=fit_key)
        zoom = st.slider(
            "Zoom (%)", min_value=25, max_value=400, value=st.session_state.get(zoom_key, 100),
            step=25, key=zoom_key, disabled=fit_to_width,
            help="Alleen actief als 'Automatisch passend maken' uit staat.",
        )

        try:
            from PIL import Image
            pil_img = Image.open(entry["image_path"])
            if rotation:
                # PIL rotates counter-clockwise for positive angles -- negate so the
                # "+90°" button visually rotates clockwise.
                pil_img = pil_img.rotate(-rotation, expand=True)
            if fit_to_width:
                st.image(pil_img, width="stretch")
            else:
                w, _h = pil_img.size
                target_w = max(50, int(w * zoom / 100))
                st.image(pil_img, width=target_w)
        except Exception as exc:
            st.error(f"Kon afbeelding niet verwerken (rotatie/zoom): {exc}")
    else:
        st.warning(f"Scan-afbeelding niet gevonden op: {entry['image_path']}")
    st.text_area("Ruwe transcriptie (ter referentie, read-only)", entry["raw_transcript"] or "", height=120, disabled=True)

with col_form:
    st.subheader("Corrigeer / bevestig")
    with st.form(f"verify_form_{entry_id}"):
        datum_ruw = st.text_input("Datum (ruw, zoals geschreven)", entry["datum_ruw"] or "")
        datum_iso = st.text_input("Datum (ISO, YYYY-MM-DD — leeg laten als echt onzeker)", entry["datum_iso"] or "")
        tijd = st.text_input("Tijd", entry["tijd"] or "")
        opmerkingen = st.text_area("Opmerkingen", entry["opmerkingen"] or "", height=80)

        st.markdown("**Toepassingen (middel + hoeveelheid)**")
        toep_df = pd.DataFrame(
            [{"middel": t["middel"], "hoeveelheid": t["hoeveelheid"]} for t in toepassingen]
        ) if toepassingen else pd.DataFrame({"middel": [], "hoeveelheid": []})
        edited_toep = st.data_editor(
            toep_df, num_rows="dynamic", width="stretch", key=f"toep_editor_{entry_id}",
            column_config={
                "middel": st.column_config.TextColumn("Middel"),
                "hoeveelheid": st.column_config.TextColumn("Hoeveelheid"),
            },
        )

        col_verify, col_skip = st.columns(2)
        verify_clicked = col_verify.form_submit_button("Geverifieerd — onzeker-label verwijderen", type="primary", width="stretch")
        skip_clicked = col_skip.form_submit_button("Overslaan (nog niet zeker)", width="stretch")

    if verify_clicked:
        conn.execute(
            "UPDATE entries SET datum_ruw=?, datum_iso=?, tijd=?, opmerkingen=?, "
            "onzeker=0, geverifieerd=1, geverifieerd_op=? WHERE id=?",
            (
                datum_ruw or None, datum_iso or None, tijd or None, opmerkingen or None,
                datetime.now().isoformat(timespec="seconds"), entry_id,
            ),
        )
        conn.execute("DELETE FROM toepassingen WHERE entry_id=?", (entry_id,))
        for i, row in edited_toep.iterrows():
            middel = (row.get("middel") or "").strip()
            hoeveelheid = (row.get("hoeveelheid") or "").strip()
            if middel or hoeveelheid:
                conn.execute(
                    "INSERT INTO toepassingen (entry_id, volgorde, middel, hoeveelheid) VALUES (?, ?, ?, ?)",
                    (entry_id, i, middel or None, hoeveelheid or None),
                )
        conn.commit()
        st.success("Opgeslagen en gemarkeerd als geverifieerd.")
        st.rerun()

    if skip_clicked:
        st.session_state[idx_key] = idx + 1
        st.rerun()

st.divider()
nav1, nav2 = st.columns(2)
if nav1.button("Vorige", disabled=idx == 0, width="stretch"):
    st.session_state[idx_key] = idx - 1
    st.rerun()
if nav2.button("Volgende", disabled=idx >= len(remaining_ids) - 1, width="stretch"):
    st.session_state[idx_key] = idx + 1
    st.rerun()
