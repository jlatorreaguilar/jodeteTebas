#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_data.py
Descarga las listas de ELCANO y genera:
  - data/canales.json  → canales acestream organizados por categoría
  - data/agenda.json   → eventos deportivos del día
"""

import json
import os
import re
import sys
import urllib.request

# ---------------------------------------------------------------------------
# Fuentes ELCANO (por orden de preferencia)
# ---------------------------------------------------------------------------
BASE_IPNS = (
    "https://k51qzi5uqu5di462t7j4vu4akwfhvtjhy88qbupktvoacqfqe9uforjvhyi4wr"
    ".ipns.dweb.link"
)
URL_CANALES      = f"{BASE_IPNS}/hashes.txt"
URL_CANALES_M3U  = f"{BASE_IPNS}/hashes_acestream.m3u"
URL_CANALES_ALT  = f"{BASE_IPNS}/hashes_kodi.m3u"
# M3U con fuentes adicionales: NEW ERA, NEW LOOP, SPORT TV, etc.
URL_CANALES_MULTI = (
    "https://dweb.link/ipns/k2k4r8oqlcjxsritt5mczkcn4mmvcmymbqw7113fz2flkrerfwfps004"
    "/data/listas/lista_fuera_iptv.m3u"
)
URL_AGENDA = (
    "https://raw.githubusercontent.com/ezdakit/zukzeuk_listas/refs/heads/main"
    "/zz_eventos/zz_eventos_all_ott.m3u"
)
URL_AGENDA_ALT = f"{BASE_IPNS}/hashes_acestream.m3u"

# Canales relevantes con su categoría (nombre_base → categoría)
CANAL_CATEGORIAS = {
    "DAZN": "DAZN",
    "M+ LALIGA": "Movistar",
    "MOVISTAR": "Movistar",
    "HYPERMOTION": "LaLiga",
    "GOL PLAY": "LaLiga",
    "LIGA DE CAMPEONES": "Champions",
    "EUROSPORT": "General",
    "TELEDEPORTE": "General",
    "REAL MADRID TV": "General",
    "BEIN SPORTS": "General",
    "SKY SPORTS": "General",
    "LA 1": "General",
    "CUATRO": "General",
    "TELECINCO": "General",
    "PRIMERA FEDERACION": "LaLiga",
    "PRIMERA FEDERACIÓN": "LaLiga",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  WARN: no se pudo descargar {url}: {e}", file=sys.stderr)
        return None


def get_categoria(nombre_base):
    for key, cat in CANAL_CATEGORIAS.items():
        if key.upper() in nombre_base.upper():
            return cat
    return "General"


def prioridad(nombre):
    """Menor número = mayor prioridad (1080p > FHD > 720p > HD > resto)."""
    n = nombre.upper()
    if "1080P" in n:
        return 0
    if "FHD" in n:
        return 1
    if "720P" in n:
        return 2
    if "HD" in n:
        return 3
    return 4


# ---------------------------------------------------------------------------
# Parsear hashes.txt  (formato: cabecera + secciones === CAT === + NOMBRE\nacestream://ID)
# Devuelve lista de categorías, cada una con TODOS sus canales (sin filtrar ni deduplicar)
# ---------------------------------------------------------------------------

def build_canales(text):
    categorias = []
    cat_actual = None
    canales_actuales = []

    lines = [l.rstrip() for l in text.splitlines()]
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Nueva categoría: === NOMBRE ===
        m = re.match(r"===\s*(.+?)\s*===", line)
        if m:
            # Guardar la anterior
            if cat_actual and canales_actuales:
                categorias.append({"nombre": cat_actual, "canales": canales_actuales})
            cat_actual = m.group(1).strip().upper()
            canales_actuales = []
            i += 1
            continue

        # Par nombre + acestream://ID
        if cat_actual and line and not line.startswith("AceStream") and \
                not line.startswith("Generated") and not line.startswith("Total:") and \
                not line.startswith("====="):
            # ¿siguiente línea es acestream?  
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].strip().startswith("acestream://"):
                nombre_raw = line
                ace_id = lines[j].strip().replace("acestream://", "").strip()
                if len(ace_id) == 40 and re.fullmatch(r"[0-9a-f]+", ace_id):
                    # Limpiar nombre: quitar * y ** del final
                    nombre = re.sub(r"\s+\*+\s*$", "", nombre_raw).strip()
                    canales_actuales.append({
                        "nombre": nombre,
                        "acestream_id": ace_id,
                        "short_id": ace_id[:4],
                        "fuente": "ELCANO",
                    })
                i = j + 1
                continue
        i += 1

    # Última categoría pendiente
    if cat_actual and canales_actuales:
        categorias.append({"nombre": cat_actual, "canales": canales_actuales})

    total = sum(len(c["canales"]) for c in categorias)
    return categorias, total


# ---------------------------------------------------------------------------
# Parsear lista_fuera_iptv.m3u  (formato m3u con group-title y --> FUENTE)
# Combina los canales en el dict de categorias existente
# ---------------------------------------------------------------------------

def merge_m3u_canales(text, categorias):
    """Añade a `categorias` los canales del M3U que no sean ya de ELCANO puro."""
    # Construir índice catálogo existente para busca rápida
    cat_index = {c["nombre"]: c["canales"] for c in categorias}

    # Patrón: #EXTINF con group-title="CAT", NOMBRE --> FUENTE\nacestream://ID
    patron = re.compile(
        r'#EXTINF[^\n]*group-title="([^"]+)"[^\n]*,\s*(.+?)\s*\n\s*(acestream://[0-9a-f]+)',
        re.IGNORECASE | re.MULTILINE,
    )
    nuevos = 0
    for m in patron.finditer(text):
        cat     = m.group(1).strip().upper()
        nombre  = m.group(2).strip()
        ace_url = m.group(3).strip()
        ace_id  = ace_url.replace("acestream://", "")

        if len(ace_id) != 40 or not re.fullmatch(r"[0-9a-f]+", ace_id):
            continue

        # Extraer fuente del nombre: "CANAL --> FUENTE" → fuente
        fuente_match = re.search(r"-->\s*(.+)$", nombre)
        fuente = fuente_match.group(1).strip() if fuente_match else "ELCANO"

        # Si ya viene de ELCANO ya lo tenemos (fue añadido por build_canales)
        if fuente.upper() == "ELCANO":
            continue

        if cat not in cat_index:
            categorias.append({"nombre": cat, "canales": []})
            cat_index[cat] = categorias[-1]["canales"]

        cat_index[cat].append({
            "nombre": nombre,
            "acestream_id": ace_id,
            "short_id": ace_id[:4],
            "fuente": fuente,
        })
        nuevos += 1

    return nuevos


# ---------------------------------------------------------------------------
# Parsear m3u de agenda
# ---------------------------------------------------------------------------

def build_agenda(text):
    eventos = []
    # Formato m3u: #EXTINF:-1 tvg-id="..." title="FECHA, HORA",TITULO\nacestream://ID
    patron = re.compile(
        r'#EXTINF[^\n]*?title="([^"]+),\s*([^"]+)"[^\n]*\n([^\n]+)',
        re.IGNORECASE,
    )
    for m in patron.finditer(text):
        fecha  = m.group(1).strip()
        hora   = m.group(2).strip()
        enlace = m.group(3).strip()
        titulo_match = re.search(r',(.+)$', m.group(0).split('\n')[0])
        titulo = titulo_match.group(1).strip() if titulo_match else fecha

        ace_id = None
        if "acestream://" in enlace:
            ace_id = enlace.replace("acestream://", "").strip()
        elif re.search(r"[0-9a-f]{40}", enlace):
            ace_id = re.search(r"[0-9a-f]{40}", enlace).group(0)

        if ace_id:
            eventos.append({
                "titulo": titulo,
                "fecha": fecha,
                "hora": hora,
                "acestream_id": ace_id,
            })

    # Fallback: formato simple  title="HORA",TITULO
    if not eventos:
        patron2 = re.compile(
            r'#EXTINF[^\n]*?,(.+)\n([^\n]+)',
            re.IGNORECASE,
        )
        for m in patron2.finditer(text):
            titulo = m.group(1).strip()
            enlace = m.group(2).strip()
            ace_id = None
            if "acestream://" in enlace:
                ace_id = enlace.replace("acestream://", "").strip()
            if ace_id:
                eventos.append({
                    "titulo": titulo,
                    "fecha": "",
                    "hora": "",
                    "acestream_id": ace_id,
                })

    return eventos


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs("data", exist_ok=True)

    # --- Canales ---
    print("Descargando hashes.txt desde ELCANO...")
    texto_canales = fetch(URL_CANALES, timeout=30)
    if not texto_canales:
        print("Intentando hashes_kodi.m3u...")
        texto_canales = fetch(URL_CANALES_ALT, timeout=20)

    if texto_canales:
        categorias, total = build_canales(texto_canales)
        print(f"  ELCANO: {total} canales en {len(categorias)} categorías")
    else:
        print("  ✗ No se pudo obtener la lista de canales", file=sys.stderr)
        sys.exit(1)

    # Añadir fuentes adicionales: NEW ERA, NEW LOOP, SPORT TV, etc.
    print("Descargando lista_fuera_iptv.m3u (NEW ERA / NEW LOOP / SPORT TV)...")
    texto_multi = fetch(URL_CANALES_MULTI, timeout=30)
    if texto_multi:
        nuevos = merge_m3u_canales(texto_multi, categorias)
        print(f"  + {nuevos} canales adicionales de otras fuentes")
    else:
        print("  WARN: no se pudo obtener lista_fuera_iptv.m3u", file=sys.stderr)

    total_final = sum(len(c["canales"]) for c in categorias)
    with open("data/canales.json", "w", encoding="utf-8") as f:
        json.dump({"categorias": categorias, "total": total_final}, f,
                  ensure_ascii=False, indent=2)
    print(f"  ✓ {total_final} canales en {len(categorias)} categorías guardados en data/canales.json")

    # --- Agenda ---
    print("Descargando agenda de eventos ELCANO...")
    texto_agenda = fetch(URL_AGENDA, timeout=20)
    if not texto_agenda:
        print("Intentando agenda alternativa...")
        texto_agenda = fetch(URL_AGENDA_ALT, timeout=20)

    if texto_agenda:
        eventos = build_agenda(texto_agenda)
        with open("data/agenda.json", "w", encoding="utf-8") as f:
            json.dump({"eventos": eventos, "total": len(eventos)}, f,
                      ensure_ascii=False, indent=2)
        print(f"  ✓ {len(eventos)} eventos guardados en data/agenda.json")
    else:
        print("  WARN: No se encontraron eventos de agenda", file=sys.stderr)
        with open("data/agenda.json", "w", encoding="utf-8") as f:
            json.dump({"eventos": [], "total": 0}, f)


if __name__ == "__main__":
    main()
