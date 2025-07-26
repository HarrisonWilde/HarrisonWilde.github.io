#!/usr/bin/env python3
"""
Google Scholar scraper for Harrison Wilde's publications.
This script fetches publication data and merges it with saved annotations.

Prerequisites:
pip install selenium beautifulsoup4 requests

For Chrome:
brew install chromedriver

Usage:
python scholar_scraper.py
"""

import json
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# Configuration
SCHOLAR_URL = "https://scholar.google.com/citations?hl=en&authuser=1&user=nkElOLUAAAAJ"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def load_annotations():
    """Load existing annotations from annotations.json."""
    try:
        with open("annotations.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print("No annotations.json found, creating empty one...")
        return {"paper_annotations": {}}


def save_annotations(annotations):
    """Save annotations back to annotations.json."""
    with open("annotations.json", "w", encoding="utf-8") as f:
        json.dump(annotations, f, indent=2, ensure_ascii=False)


def extract_stats_simple():
    """Extract basic stats from Google Scholar using requests and BeautifulSoup."""
    headers = {"User-Agent": USER_AGENT}
    try:
        print("Fetching data from Google Scholar...")
        response = requests.get(SCHOLAR_URL, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"Failed to fetch Scholar page: {response.status_code}")
            exit(1)

        soup = BeautifulSoup(response.text, "html.parser")

        # Look for the statistics table
        stat_elements = soup.find_all("td", class_="gsc_rsb_std")

        if len(stat_elements) >= 3:
            try:
                total_citations = int(stat_elements[0].text.strip())
                h_index = int(stat_elements[2].text.strip())
                i10_index = int(stat_elements[4].text.strip()) if len(stat_elements) > 4 else 0

                print(
                    f"Successfully scraped stats: {total_citations} citations, h-index: {h_index}, i10-index: {i10_index}"
                )

                return {
                    "total_citations": total_citations,
                    "h_index": h_index,
                    "i10_index": i10_index,
                    "last_updated": datetime.now().strftime("%Y-%m-%d"),
                }
            except (ValueError, IndexError) as e:
                print(f"Could not parse statistics: {e}")
        else:
            print("Statistics elements not found on page")

    except Exception as e:
        print(f"Error during scraping: {e}")

    return None


def get_page_details(pub_url, headers):
    """Fetch the complete author list from a publication's detail page."""
    try:
        response = requests.get(pub_url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"  Warning: Failed to fetch publication detail page {pub_url}: {response.status_code}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        # Look for the authors in the detail page - they're usually in a div with class="gs_scl"
        author_divs = soup.find_all("div", class_="gs_scl")
        for div in author_divs:
            label = div.find("div", class_="gsc_oci_field")
            if label and "Authors" in label.text:
                authors_div = div.find("div", class_="gsc_oci_value")
                if authors_div:
                    # Extract authors and clean up
                    authors_text = authors_div.text.strip()
                    authors = [author.strip() for author in authors_text.split(",")]

        link = soup.find("a", class_="gsc_oci_title_link").get("href", "")
        return authors, link

    except Exception as e:
        print(f"  Warning: Could not fetch page details from {pub_url}: {e}")

    return None


def scrape_publications():
    """Scrape Google Scholar profile for publications."""
    headers = {"User-Agent": USER_AGENT}
    publications = []

    try:
        print("Scraping Google Scholar for publications...")
        response = requests.get(SCHOLAR_URL, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"Failed to fetch Scholar page: {response.status_code}")
            exit(1)

        soup = BeautifulSoup(response.text, "html.parser")

        # Find each publication entry
        pub_elements = soup.find_all("tr", class_="gsc_a_tr")
        print(f"Found {len(pub_elements)} publications, fetching complete author lists...")

        for i, element in enumerate(pub_elements, 1):
            title_elem = element.find("a", class_="gsc_a_at")
            author_elems = element.find_all("div", class_="gs_gray")
            year_elem = element.find("span", class_="gsc_a_h gsc_a_hc gs_ibl")

            if title_elem and len(author_elems) >= 1 and year_elem:
                title = title_elem.text
                initial_authors = author_elems[0].text.split(", ")
                year = int(year_elem.text)
                venue = author_elems[1].text if len(author_elems) > 1 else ""

                # Extract the Google Scholar link and make it absolute
                scholar_href = title_elem["href"]
                scholar_link = (
                    f"https://scholar.google.com{scholar_href}" if scholar_href.startswith("/") else scholar_href
                )

                print(f"  [{i}/{len(pub_elements)}] Processing: {title[:60]}...")

                full_authors, link = get_page_details(scholar_link, headers)
                if full_authors:
                    authors = full_authors
                    print(f"    ✅ Got {len(authors)} complete authors")
                else:
                    # Remove the "..." but keep the partial list
                    authors = initial_authors
                    print("    ⚠️  Could not fetch full authors, using partial list")

                publications.append(
                    {
                        "title": title,
                        "authors": authors,
                        "year": year,
                        "venue": venue,
                        "link": link,
                    }
                )

        print(f"Successfully scraped {len(publications)} publications.")
        return publications

    except Exception as e:
        print(f"Error during scraping: {e}")

    return None


def merge_annotations(publications, annotations_data):
    """Merge annotations with publications based on title matching."""
    paper_annotations = annotations_data.get("paper_annotations", {})

    for pub in publications:
        pub_title = pub["title"]

        # Try exact match first
        if pub_title in paper_annotations:
            pub["annotations"] = paper_annotations[pub_title]
        else:
            # Try partial matching for flexibility
            for annotation_title, annotation_list in paper_annotations.items():
                if annotation_title.lower() in pub_title.lower() or pub_title.lower() in annotation_title.lower():
                    pub["annotations"] = annotation_list
                    break
            else:
                pub["annotations"] = []

    return publications


def generate_publications_js():
    """Generate the publications data and embed it in JavaScript."""
    print("Fetching Google Scholar statistics...")
    stats = extract_stats_simple()

    print("Loading publications...")
    publications = scrape_publications()

    print("Loading annotations...")
    annotations_data = load_annotations()

    print("Merging annotations with publications...")
    publications = merge_annotations(publications, annotations_data)

    # Create the complete data structure
    data = {"scholar_stats": stats, "publications": publications}

    # Generate JavaScript file
    js_content = f"""// Auto-generated publications data - {datetime.now().isoformat()}
// Do not edit this file directly, use scholar_scraper.py

window.PUBLICATIONS_DATA = {json.dumps(data, indent=2, ensure_ascii=False)};
"""

    # Save to publications.js
    with open("publications.js", "w", encoding="utf-8") as f:
        f.write(js_content)

    print(f"✅ Generated publications.js with {len(publications)} publications")
    print(
        f"📊 Stats: {stats['total_citations']} citations, h-index: {stats['h_index']}, i10-index: {stats['i10_index']}"
    )


def main():
    """Main function."""
    print("🔄 Updating publications data...")
    try:
        generate_publications_js()
        print("✅ Publications data updated successfully!")
        print("\nTo add/edit annotations:")
        print("1. Edit annotations.json")
        print("2. Run this script again to regenerate publications.js")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    main()
