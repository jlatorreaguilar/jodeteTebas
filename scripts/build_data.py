#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_data.py
Descarga las listas del IPFS de shickat.me y genera:
  - data/canales.json  → canales acestream organizados por categoría
  - data/agenda.json   → eventos deportivos del día
"""

import json
import os
import re
import sys
import urllib.request

# ---------------------------------------------------------------------------
# Fuentes (por orden de preferencia)
# ---------------------------------------------------------------------------
BASE_SHICKAT = (
    "https://dweb.link/ipns/k2k4r8oqlcjxsritt5mczkcn4mmvcmymbqw7113fz2flkrerfwfps004"
    "/data/listas"
)
# Lista completa con todas las fuentes (ELCANO, NEW ERA, NEW LOOP, SPORT TV…)
# en formato Kodi: plugin://script.module.horus?action=play&id=<acestream_id>
URL_CANALES_KODI  = f"{BASE_SHICKAT}/lista_kodi.m3u"
# Fallback con formato acestream://
URL_CANALES_FUERA = f"{BASE_SHICKAT}/lista_fuera_iptv.m3u"

BASE_ELCANO = (
    "https://k51qzi5uqu5di462t7j4vu4akwfhvtjhy88qbupktvoacqfqe9uforjvhyi4wr"
    ".ipns.dweb.link"
)
URL_AGENDA = (
    "https://raw.githubusercontent.com/ezdakit/zukzeuk_listas/refs/heads/main"
    "/zz_eventos/zz_eventos_all_ott.m3u"
)
URL_AGENDA_ALT = f"{BASE_ELCANO}/hashes_acestream.m3u"

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


def inferir_fuente(nombre):
    n = nombre.upper()
    if "NEW ERA" in n:
        return "NEW ERA"
    if "NEW LOOP" in n:
        return "NEW LOOP"
    if "SPORT TV" in n and "-->" in n:
        return "SPORT TV"
    return "ELCANO"


# ---------------------------------------------------------------------------
# Parsear lista_kodi.m3u  (formato: group-title + plugin://...?id=<acestream_id>)
# Parsear lista_fuera_iptv.m3u (formato: group-title + acestream://<acestream_id>)
# Devuelve lista de categorías con todos sus canales
# ---------------------------------------------------------------------------

def build_canales_from_m3u(text):
    categorias = []
    cat_index = {}   # nombre_cat -> lista canales

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            g = re.search(r'group-title="([^"]+)"', line)
            n = re.search(r',(.+)$', line)
            if g and n:
                cat = g.group(1).strip().upper()
                nombre = n.group(1).strip()
                # Línea siguiente: URL del canal
                if i + 1 < len(lines):
                    url_line = lines[i + 1].strip()
                    # Formato Kodi: plugin://script.module.horus?action=play&id=XXXXX
                    ace = re.search(r'[?&]id=([a-f0-9]{40})', url_line)
                    # Formato acestream://XXXXX
                    if not ace:
                        ace = re.search(r'acestream://([a-f0-9]{40})', url_line)
                    if ace:
                        ace_id = ace.group(1)
                        fuente = inferir_fuente(nombre)
                        if cat not in cat_index:
                            cat_index[cat] = []
                            categorias.append({"nombre": cat, "canales": cat_index[cat]})
                        cat_index[cat].append({
                            "nombre": nombre,
                            "acestream_id": ace_id,
                            "short_id": ace_id[:4],
                            "fuente": fuente,
                        })
        i += 1

    total = sum(len(c["canales"]) for c in categorias)
    return categorias, total


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
    print("Descargando lista_kodi.m3u desde shickat.me/IPFS...")
    texto_canales = fetch(URL_CANALES_KODI, timeout=60)
    if texto_canales:
        categorias, total = build_canales_from_m3u(texto_canales)
        print(f"  lista_kodi.m3u: {total} canales en {len(categorias)} categorías")
    else:
        print("  Fallback → lista_fuera_iptv.m3u...")
        texto_canales = fetch(URL_CANALES_FUERA, timeout=60)
        if texto_canales:
            categorias, total = build_canales_from_m3u(texto_canales)
            print(f"  lista_fuera_iptv.m3u: {total} canales en {len(categorias)} categorías")
        else:
            print("  ✗ No se pudo obtener ninguna lista de canales", file=sys.stderr)
            sys.exit(1)

    total_final = sum(len(c["canales"]) for c in categorias)
    with open("data/canales.json", "w", encoding="utf-8") as f:
        json.dump({"categorias": categorias}, f, ensure_ascii=False, indent=2)
    print(f"  ✓ {total_final} canales en {len(categorias)} categorías → data/canales.json")

    # --- Agenda ---
    print("Descargando agenda de eventos...")
    texto_agenda = fetch(URL_AGENDA, timeout=20)
    if not texto_agenda:
        print("Intentando agenda alternativa...")
        texto_agenda = fetch(URL_AGENDA_ALT, timeout=20)

    if texto_agenda:
        eventos = build_agenda(texto_agenda)
        with open("data/agenda.json", "w", encoding="utf-8") as f:
            json.dump({"eventos": eventos, "total": len(eventos)}, f,
                      ensure_ascii=False, indent=2)
        print(f"  ✓ {len(eventos)} eventos → data/agenda.json")
    else:
        print("  WARN: No se encontraron eventos de agenda", file=sys.stderr)
        with open("data/agenda.json", "w", encoding="utf-8") as f:
            json.dump({"eventos": [], "total": 0}, f)


if __name__ == "__main__":
    main()
