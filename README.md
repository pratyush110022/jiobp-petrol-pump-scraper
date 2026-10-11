# Jio-bp Mobility Station Scraper

Python automation for collecting Jio-bp mobility-station details from configured listing pages, producing state-wise CSVs, a consolidated dataset, and a browser network log.

## How it works

1. Reads the input CSV with State and URL columns.
2. Uses Playwright with a persistent local Chrome profile to open each configured listing URL.
3. Paginates through station listings and collects unique station detail links.
4. Parses station detail pages with BeautifulSoup, preferring JSON-LD business data and falling back to page text when fields are missing.
5. Deduplicates station records, saves state-wise files and a master file, and records observed API/JSON/XHR network responses.

## Output fields

Station records can include:

- Brand and Dealer_Name
- Address, City, State, and Pincode
- Phone
- Latitude and Longitude
- Status
- Website_URL, Google_Map_URL, and Detail_URL

## Generated files

Inside the configured output folder, the script can create:

- <State>_JioBP.csv — one deduplicated file for each state with data
- All_States_JioBP.csv — consolidated station dataset
- jio_bp_network_hits.csv — captured network/API/JSON response metadata
- debug_<State>_page_<n>.html — listing-page HTML for troubleshooting when no station links are found

The repository also includes input/output examples for reference.

## Requirements and setup

- Python 3.10 or a compatible version
- Playwright
- pandas
- beautifulsoup4
- lxml
- tqdm
- Google Chrome installed

    python -m venv .venv
    .venv/Scripts/Activate.ps1
    pip install playwright pandas beautifulsoup4 lxml tqdm

## Configuration and run

Update these constants in jiobp_scraper.py before use:

- INPUT_CSV — CSV path; it must have State and URL columns
- BASE_OUTPUT_FOLDER — writable output directory
- CHROME_PATH — installed Chrome executable
- USER_DATA — local persistent Chrome profile directory
- HEADLESS, PAGE_TIMEOUT, NAV_RETRIES, and SAFETY_PAGE_CEILING — browser and pagination controls

The paths currently point to the original Windows workstation. Adjust them to match your machine and the input file in this repository.

Run:

    python jiobp_scraper.py

## Notes

- The browser is visible by default and uses a persistent profile.
- HTML parsing and page-navigation logic may need maintenance if the source website changes.
- Collected station details and network logs are snapshots of the responses seen during that run.
