# [hwil.de](https://hwil.de)

This repository contains the source code for my personal website.

## Setup and Usage

1. Setup a python virtual environment (optional but recommended):

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. To run the website locally, you can use Python's HTTP server:

   ```bash
   python -m http.server
   ```

   Visit `http://localhost:8000` to view the site.

## Managing Publications and Annotations

### Updating Publications

- Run `scholar_scraper.py` to fetch and process the latest data from Google Scholar, then generate `publications.js`:

  ```bash
  python scholar_scraper.py
  ```

### Managing Annotations

- To add or update annotations, modify `annotations.json` and re-run the scraper as above to regenerate `publications.js` with the latest annotations.
