# WDFW Publication Map (Client Production)

This folder contains a client-facing production map with publication coordinate points only.

## Contents

- `index.html` : Production map page (no verification tabs or internal review tools)
- `assets/wdfw_logo_horizontal_fullcolor.svg` : WDFW logo asset used in header
- `build_published_client_map.py` : Rebuild script from latest quality event dataset

## Rebuild

```bash
cd /Users/vg/vgcode/DFWPub/published_client_map
python3 build_published_client_map.py
```

## Run locally

```bash
cd /Users/vg/vgcode/DFWPub/published_client_map
python3 -m http.server 8899
```

Then open: `http://127.0.0.1:8899/index.html`
