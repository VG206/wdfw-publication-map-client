#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent
QUALITY_CSV = ROOT / "washington_publications_event_data_quality.csv"
OUT_HTML = OUT_DIR / "index.html"


def clean_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    txt = re.sub(r"\s+", " ", str(value)).strip()
    if txt.lower() in {"nan", "none", "null", "nat"}:
        return ""
    return txt


def split_pipe(value: str) -> list[str]:
    txt = clean_text(value)
    if not txt:
        return []
    return [clean_text(v) for v in txt.split("|") if clean_text(v)]


def infer_tags(categories: str, title: str) -> list[str]:
    c = clean_text(categories).lower()
    t = clean_text(title).lower()
    tags = []
    if any(k in c for k in ["fish", "shellfish", "fishing", "salmon", "hatcher"]) or any(
        k in t for k in ["salmon", "steelhead", "trout", "crab", "oyster", "walleye", "fish"]
    ):
        tags.append("Fish")
    if any(k in c for k in ["wildlife", "game", "waterfowl", "deer", "elk", "nongame"]) or any(
        k in t for k in ["bear", "deer", "elk", "wolf", "wolverine", "plover", "wildlife"]
    ):
        tags.append("Wildlife")
    if any(k in c for k in ["habitat", "riparian", "wetland", "nearshore", "instream", "ecosystem"]):
        tags.append("Habitat")
    if not tags:
        tags.append("Other")
    return tags


def primary_tag(tags: list[str]) -> str:
    for t in ["Fish", "Wildlife", "Habitat", "Other"]:
        if t in tags:
            return t
    return "Other"


def parse_int(value) -> int | None:
    txt = clean_text(value)
    if not txt:
        return None
    try:
        return int(float(txt))
    except Exception:
        return None


def build_payload() -> dict:
    if not QUALITY_CSV.exists():
        raise FileNotFoundError(f"Missing input CSV: {QUALITY_CSV}")

    df = pd.read_csv(QUALITY_CSV)
    if "human_include" in df.columns:
        mask = df["human_include"].astype(str).str.lower().map(
            lambda s: False if s in {"false", "0", "no", "n"} else True
        )
        df = df[mask].copy()

    points = []
    seen = set()

    for idx, row in df.iterrows():
        lat = row.get("lat")
        lon = row.get("lon")
        if pd.isna(lat) or pd.isna(lon):
            continue

        title = clean_text(row.get("title"))
        publication_id = clean_text(row.get("publication_id"))
        source_url = clean_text(row.get("source_url"))
        location = clean_text(row.get("water_body_canonical")) or clean_text(row.get("water_body_raw"))
        species = split_pipe(row.get("species", ""))
        publication_date = clean_text(row.get("publication_date")) or "Unknown"

        tags = split_pipe(row.get("research_tags", ""))
        if not tags:
            tags = infer_tags(row.get("categories", ""), title)
        main_tag = primary_tag(tags)

        year = parse_int(row.get("study_year_start"))
        if year is None:
            year = parse_int(row.get("publication_year"))

        point = {
            "id": clean_text(row.get("event_id")) or f"E{idx + 1:05d}",
            "publication_id": publication_id,
            "title": title,
            "source_url": source_url,
            "publication_date": publication_date,
            "study_year": year,
            "species": species,
            "tags": tags,
            "main_tag": main_tag,
            "location": location,
            "lat": round(float(lat), 6),
            "lon": round(float(lon), 6),
        }

        key = (
            point["publication_id"],
            point["location"],
            "|".join(point["species"]),
            point["study_year"],
            point["lat"],
            point["lon"],
        )
        if key in seen:
            continue
        seen.add(key)
        points.append(point)

    years = sorted({p["study_year"] for p in points if isinstance(p["study_year"], int)})
    species_options = sorted({s for p in points for s in p["species"] if s})

    payload = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "stats": {
            "points": len(points),
            "publications": len({p["publication_id"] for p in points if p["publication_id"]}),
            "species": len(species_options),
            "min_year": years[0] if years else 1900,
            "max_year": years[-1] if years else 2100,
        },
        "species_options": species_options,
        "points": points,
    }
    return payload


def build_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"""<!doctype html>
<html lang=\"en\"> 
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>WDFW Publication Map</title>
  <link rel=\"icon\" type=\"image/svg+xml\" href=\"./assets/wdfw_logo_horizontal_fullcolor.svg\" />
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
  <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
  <link href=\"https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&family=Roboto+Slab:wght@700&display=swap\" rel=\"stylesheet\" />
  <link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.css\" />
  <link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css\" />
  <link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css\" />
  <style>
    :root {{
      --bg: #f3f6f4;
      --panel: #ffffff;
      --ink: #163746;
      --muted: #4b6672;
      --line: #cad7dd;
      --brand: #0f7f65;
      --brand-dark: #0a5e4b;
      --fish: #c1121f;
      --wildlife: #f77f00;
      --habitat: #1d4ed8;
      --other: #5a6773;
    }}

    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; height: 100%; background: var(--bg); color: var(--ink); font-family: 'Roboto', sans-serif; }}
    body {{ display: flex; flex-direction: column; }}

    .wdfw-header {{ background: #fff; border-bottom: 1px solid var(--line); }}
    .brand-row {{ max-width: 1440px; margin: 0 auto; padding: 12px 18px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }}
    .brand-link img {{ height: 58px; width: auto; display: block; }}
    .brand-actions {{ display: flex; gap: 10px; align-items: center; color: var(--muted); font-size: 13px; }}
    .brand-actions a {{ color: var(--ink); text-decoration: none; }}
    .brand-actions a:hover {{ text-decoration: underline; }}

    .menu-row {{ border-top: 1px solid #e7eef1; background: linear-gradient(180deg, #fbfdfd, #f5f8f9); }}
    .menu-inner {{ max-width: 1440px; margin: 0 auto; padding: 0 18px; display: flex; gap: 24px; overflow-x: auto; }}
    .menu-inner a {{ white-space: nowrap; padding: 12px 0; color: #213a45; text-decoration: none; font-weight: 500; border-bottom: 3px solid transparent; }}
    .menu-inner a.active {{ border-bottom-color: var(--brand); color: var(--brand-dark); }}

    .content {{ flex: 1; min-height: 0; max-width: 1440px; width: 100%; margin: 0 auto; padding: 16px 18px 18px; display: flex; flex-direction: column; gap: 14px; }}

    .hero {{ background: linear-gradient(120deg, #ffffff 0%, #eef5f4 100%); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; }}
    .hero h1 {{ margin: 0 0 6px; font-family: 'Roboto Slab', serif; font-size: 30px; line-height: 1.15; color: #173d4b; }}
    .hero p {{ margin: 0; color: var(--muted); font-size: 14px; line-height: 1.45; }}

    .controls {{ background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 12px; display: grid; gap: 10px; grid-template-columns: 2.2fr 1.2fr 0.9fr 0.9fr auto; align-items: end; }}
    .field label {{ display: block; font-size: 11px; letter-spacing: 0.05em; text-transform: uppercase; color: #355766; margin-bottom: 5px; }}
    .field input, .field select {{ width: 100%; border: 1px solid #b8c8cf; border-radius: 8px; padding: 9px 10px; font-size: 14px; background: #fff; }}
    .field input:focus, .field select:focus {{ outline: none; border-color: #4f7f91; box-shadow: 0 0 0 3px rgba(79,127,145,0.15); }}
    .btn {{ border: 1px solid #8ba7b2; border-radius: 9px; background: #e7f0f4; color: #173542; padding: 9px 12px; cursor: pointer; font-weight: 600; }}
    .btn:hover {{ background: #dcebf1; }}

    .stats {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
    .chip {{ background: #fff; border: 1px solid var(--line); border-radius: 999px; padding: 7px 12px; font-size: 13px; color: #254756; }}
    .chip-filter {{ cursor: pointer; border-width: 2px; font-weight: 700; transition: transform 120ms ease, box-shadow 120ms ease, background 120ms ease; display: inline-flex; align-items: center; gap: 7px; }}
    .chip-filter:hover {{ transform: translateY(-1px); box-shadow: 0 3px 8px rgba(16, 61, 77, 0.14); }}
    .chip-filter.active {{ background: #fff; border-color: #8fa8b3; color: #173542; }}
    .chip-filter.inactive {{ background: #fff; border-color: #c7d6dd; color: #56717d; }}
    .chip-dot {{ width: 10px; height: 10px; border-radius: 50%; border: 1px solid #b8c7ce; background: #d5e0e5; display: inline-block; flex: 0 0 auto; }}
    .chip-filter.active .chip-dot {{ background: var(--chip-color, #294955); border-color: rgba(0,0,0,0.28); }}

    .map-shell {{ flex: 1; min-height: 480px; border: 1px solid var(--line); border-radius: 14px; overflow: hidden; background: #dfe8eb; box-shadow: 0 10px 24px rgba(13, 55, 69, 0.12); }}
    #map {{ width: 100%; height: 100%; }}

    .leaflet-popup-content-wrapper {{ border-radius: 10px; }}
    .leaflet-popup-content {{ margin: 12px 14px; font-size: 13px; line-height: 1.45; }}
    .leaflet-popup-content a {{ color: #0f5c8e; }}

    @media (max-width: 1024px) {{
      .hero h1 {{ font-size: 25px; }}
      .controls {{ grid-template-columns: 1fr 1fr; }}
      .controls .field.search {{ grid-column: 1 / -1; }}
      .controls .field.reset {{ grid-column: 1 / -1; }}
      .map-shell {{ min-height: 62vh; }}
    }}
  </style>
</head>
<body>
  <header class=\"wdfw-header\">
    <div class=\"brand-row\">
      <a class=\"brand-link\" href=\"https://wdfw.wa.gov/\" target=\"_blank\" rel=\"noopener noreferrer\">
        <img src=\"./assets/wdfw_logo_horizontal_fullcolor.svg\" alt=\"Washington Department of Fish & Wildlife\" />
      </a>
      <div class=\"brand-actions\">
        <a href=\"https://wdfw.wa.gov/publications\" target=\"_blank\" rel=\"noopener noreferrer\">Publications</a>
        <span>Client Edition</span>
      </div>
    </div>
    <div class=\"menu-row\">
      <nav class=\"menu-inner\" aria-label=\"Primary\">
        <a href=\"https://wdfw.wa.gov/\" target=\"_blank\" rel=\"noopener noreferrer\">Home</a>
        <a href=\"https://wdfw.wa.gov/species-habitats\" target=\"_blank\" rel=\"noopener noreferrer\">Species &amp; Habitats</a>
        <a href=\"https://wdfw.wa.gov/fishing\" target=\"_blank\" rel=\"noopener noreferrer\">Fishing &amp; Shellfishing</a>
        <a href=\"https://wdfw.wa.gov/hunting\" target=\"_blank\" rel=\"noopener noreferrer\">Hunting</a>
        <a href=\"https://wdfw.wa.gov/licenses\" target=\"_blank\" rel=\"noopener noreferrer\">Licenses &amp; Permits</a>
        <a href=\"https://wdfw.wa.gov/places-to-go\" target=\"_blank\" rel=\"noopener noreferrer\">Places to go</a>
        <a class=\"active\" href=\"#\">Publication Map</a>
      </nav>
    </div>
  </header>

  <main class=\"content\">
    <section class=\"hero\">
      <h1>WDFW Publication Map</h1>
      <p>Interactive public map of publication-linked coordinate points across Washington. This production view includes map exploration only and excludes internal verification tooling.</p>
    </section>

    <section class=\"controls\" aria-label=\"Map filters\">
      <div class=\"field search\">
        <label for=\"searchInput\">Search</label>
        <input id=\"searchInput\" type=\"text\" placeholder=\"Search publication title, ID, species, or location\" />
      </div>
      <div class=\"field\">
        <label for=\"speciesSelect\">Species</label>
        <select id=\"speciesSelect\"><option value=\"\">All species</option></select>
      </div>
      <div class=\"field\">
        <label for=\"yearMin\">Year from</label>
        <input id=\"yearMin\" type=\"number\" />
      </div>
      <div class=\"field\">
        <label for=\"yearMax\">Year to</label>
        <input id=\"yearMax\" type=\"number\" />
      </div>
      <div class=\"field reset\">
        <button class=\"btn\" id=\"resetBtn\" type=\"button\">Reset</button>
      </div>
    </section>

    <section class=\"stats\" id=\"stats\"></section>

    <section class=\"map-shell\">
      <div id=\"map\"></div>
    </section>
  </main>

  <script src=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.js\"></script>
  <script src=\"https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js\"></script>
  <script>
    const payload = {data_json};
    const points = payload.points || [];

    const colors = {{
      Fish: '#c1121f',
      Wildlife: '#f77f00',
      Habitat: '#1d4ed8',
      Other: '#5a6773',
    }};

    const map = L.map('map', {{ zoomControl: true }}).setView([47.45, -120.7], 7);
    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      attribution: '&copy; OpenStreetMap &copy; CARTO'
    }}).addTo(map);

    const clusters = L.markerClusterGroup({{
      showCoverageOnHover: false,
      spiderfyOnMaxZoom: true,
      maxClusterRadius: 42,
    }});
    map.addLayer(clusters);

    const searchInput = document.getElementById('searchInput');
    const speciesSelect = document.getElementById('speciesSelect');
    const yearMin = document.getElementById('yearMin');
    const yearMax = document.getElementById('yearMax');
    const resetBtn = document.getElementById('resetBtn');
    const statsEl = document.getElementById('stats');

    const typeOrder = ['Fish', 'Wildlife', 'Habitat', 'Other'];
    const activeTypeFilters = new Set(typeOrder);

    const minYear = Number(payload.stats?.min_year || 1900);
    const maxYear = Number(payload.stats?.max_year || 2100);
    yearMin.value = minYear;
    yearMax.value = maxYear;
    yearMin.min = minYear;
    yearMin.max = maxYear;
    yearMax.min = minYear;
    yearMax.max = maxYear;

    for (const s of (payload.species_options || [])) {{
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = s;
      speciesSelect.appendChild(opt);
    }}

    function markerColor(point) {{
      return colors[point.main_tag] || colors.Other;
    }}

    function pointMatches(point, q, species, yMin, yMax) {{
      if (species && !(point.species || []).includes(species)) return false;
      const yr = Number(point.study_year);
      if (Number.isFinite(yr) && (yr < yMin || yr > yMax)) return false;

      if (!q) return true;
      const hay = [
        point.title,
        point.publication_id,
        point.location,
        (point.species || []).join(' '),
        point.publication_date,
      ].join(' ').toLowerCase();
      return hay.includes(q);
    }}

    function updateStats(baseRows, shownRows) {{
      const pubCount = new Set(shownRows.map(r => r.publication_id)).size;
      const typeCounts = {{
        Fish: baseRows.filter(r => r.main_tag === 'Fish').length,
        Wildlife: baseRows.filter(r => r.main_tag === 'Wildlife').length,
        Habitat: baseRows.filter(r => r.main_tag === 'Habitat').length,
        Other: baseRows.filter(r => r.main_tag === 'Other').length,
      }};
      statsEl.innerHTML = '';
      const summaryChips = [
        `Points: ${{shownRows.length}}`,
        `Publications: ${{pubCount}}`,
      ];
      for (const text of summaryChips) {{
        const chip = document.createElement('span');
        chip.className = 'chip';
        chip.textContent = text;
        statsEl.appendChild(chip);
      }}

      for (const t of typeOrder) {{
        const b = document.createElement('button');
        b.type = 'button';
        b.className = `chip chip-filter ${{activeTypeFilters.has(t) ? 'active' : 'inactive'}}`;
        b.style.setProperty('--chip-color', colors[t] || '#294955');
        const dot = document.createElement('span');
        dot.className = 'chip-dot';
        const label = document.createElement('span');
        label.textContent = `${{t}}: ${{typeCounts[t] || 0}}`;
        b.appendChild(dot);
        b.appendChild(label);
        b.title = `Toggle ${{t}}`;
        b.addEventListener('click', () => {{
          if (activeTypeFilters.has(t)) activeTypeFilters.delete(t);
          else activeTypeFilters.add(t);
          render();
        }});
        statsEl.appendChild(b);
      }}
    }}

    function render() {{
      const q = searchInput.value.trim().toLowerCase();
      const species = speciesSelect.value;
      const yMin = Number(yearMin.value) || minYear;
      const yMax = Number(yearMax.value) || maxYear;

      const baseFiltered = points.filter(p => pointMatches(p, q, species, yMin, yMax));
      const filtered = baseFiltered.filter(p => activeTypeFilters.has(p.main_tag));

      clusters.clearLayers();
      for (const p of filtered) {{
        const marker = L.circleMarker([p.lat, p.lon], {{
          radius: 5,
          color: '#184a59',
          weight: 1,
          fillColor: markerColor(p),
          fillOpacity: 0.86,
        }});

        const speciesTxt = (p.species && p.species.length) ? p.species.join(', ') : 'Unknown';
        marker.bindPopup(
          `<b>${{p.title || 'Publication'}}</b><br>` +
          `<b>Publication ID:</b> ${{p.publication_id || 'Unknown'}}<br>` +
          `<b>Location:</b> ${{p.location || 'Unknown'}}<br>` +
          `<b>Species:</b> ${{speciesTxt}}<br>` +
          `<b>Study year:</b> ${{p.study_year || 'Unknown'}}<br>` +
          `<b>Publication date:</b> ${{p.publication_date || 'Unknown'}}<br>` +
          `<b>Type:</b> ${{p.main_tag || 'Other'}}<br>` +
          (p.source_url ? `<a href="${{p.source_url}}" target="_blank" rel="noopener noreferrer">Open publication</a>` : '')
        );
        clusters.addLayer(marker);
      }}

      updateStats(baseFiltered, filtered);

      if (filtered.length) {{
        const bounds = L.latLngBounds(filtered.map(p => [p.lat, p.lon]));
        map.fitBounds(bounds.pad(0.04));
      }}
    }}

    searchInput.addEventListener('input', render);
    speciesSelect.addEventListener('change', render);
    yearMin.addEventListener('change', render);
    yearMax.addEventListener('change', render);

    resetBtn.addEventListener('click', () => {{
      searchInput.value = '';
      speciesSelect.value = '';
      yearMin.value = minYear;
      yearMax.value = maxYear;
      activeTypeFilters.clear();
      for (const t of typeOrder) activeTypeFilters.add(t);
      render();
    }});

    render();
  </script>
</body>
</html>
"""


def main() -> None:
    payload = build_payload()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html = build_html(payload)
    OUT_HTML.write_text(html, encoding="utf-8")
    print(
        f"Wrote {OUT_HTML} with "
        f"{payload['stats']['points']} points across {payload['stats']['publications']} publications"
    )


if __name__ == "__main__":
    main()
