"""Bibliotheek -- overzicht van en toegang tot alle brondocumenten in het archief.

Toont de Track 1-kennisbank (WUR/USDA/EU-wetgeving, zie
`pipeline/ingest/build_orchard_corpus.py` en `Data/Orchard/OrchardKnowledge/manifest.json`)
-- met per document een downloadknop en, voor PDF's tot 15 MB, een inline voorbeeldweergave.
Puur lezend (geen schrijfacties), dus ook geschikt voor de publieke read-only pod-deployment.
De historische logboeken/nieuwsbrieven staan bewust NIET hier (die horen bij de
Logboek-pagina, als doorzoekbare, getranscribeerde data, niet als losse bestandenlijst).
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from orchard_common import PATHS, render_sidebar  # noqa: E402

import streamlit as st

st.set_page_config(page_title="Bibliotheek", layout="wide")
st.title("Bibliotheek")
st.caption(
    "De Track 1-kennisbank (vakkennis en regelgeving) die het archief voedt -- downloaden "
    "of direct inzien, geen aparte login nodig."
)

ctx = render_sidebar(st)

_PREVIEW_MAX_MB = 15.0


def _render_doc_row(title: str, path: Path | None, status_note: str = "", url: str | None = None) -> None:
    col1, col2 = st.columns([4, 1])
    with col1:
        st.markdown(f"**{title}**")
        if status_note:
            st.caption(status_note)
        if url:
            st.caption(f"Bron: {url}")
    with col2:
        if path and path.exists():
            size_mb = path.stat().st_size / (1024 * 1024)
            st.caption(f"{size_mb:.1f} MB")
            data = path.read_bytes()
            st.download_button("Download", data, file_name=path.name, key=f"dl_{path}")
            if path.suffix.lower() == ".pdf" and size_mb <= _PREVIEW_MAX_MB:
                with st.expander("Bekijken"):
                    b64 = base64.b64encode(data).decode("ascii")
                    st.markdown(
                        f'<iframe src="data:application/pdf;base64,{b64}" '
                        f'width="100%" height="600" style="border:1px solid #ddd;"></iframe>',
                        unsafe_allow_html=True,
                    )
        else:
            st.caption("Niet beschikbaar (zie toelichting hiernaast)")
    st.divider()


st.subheader("Vakkennis & regelgeving (Track 1)")
manifest_path = PATHS.source_dir / "manifest.json"
if manifest_path.exists():
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        manifest = []
        st.error(f"Kon manifest.json niet lezen: {exc}")
    for entry in manifest:
        path = Path(entry["file_path"]) if entry.get("file_path") else None
        note = entry.get("note", "")
        if entry["status"] == "blocked":
            note = f"NIET BESCHIKBAAR — {note}"
        elif entry["status"] == "failed":
            note = f"DOWNLOAD MISLUKT — {entry.get('error', note)}"
        _render_doc_row(entry["title"], path, status_note=note, url=entry.get("url"))
else:
    st.info(
        "Nog geen kennisbank-manifest gevonden. Bouw de kennisbank eerst met:\n\n"
        "`.venv\\Scripts\\python.exe -m pipeline.ingest.build_orchard_corpus`"
    )
