#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Jio-bp Mobility Station Scraper - Corrected State-wise Version

Key fixes:
- Correctly saves one final CSV per state.
- Handles multiple input rows for the same state without overwriting.
- Keeps one consolidated All_States_JioBP.csv.
- Saves network/API/XHR log.
- Uses persistent Chrome profile.
- Parses detail pages using JSON-LD first, then visible text fallback.

Requirements:
    pip install playwright pandas beautifulsoup4 lxml tqdm
    playwright install chromium

Input CSV columns:
    State,URL

Example:
    Odisha,https://mobilitystation.jiobp.com/location/odisha
    Maharashtra,https://mobilitystation.jiobp.com/location/maharashtra

Output folder:
    State_Wise_Output

Output files:
    Odisha_JioBP.csv
    Maharashtra_JioBP.csv
    All_States_JioBP.csv
    jio_bp_network_hits.csv
"""

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlsplit, urlunsplit
from tqdm import tqdm
import pandas as pd
import json
import re
import time
import random
import os


# =========================
# CONFIG
# =========================

INPUT_CSV = r"C:\Users\prdas4\Downloads\2025_Projects\2025_H1\H1_2025\2-Junks Check\Petrol Pump\JioBP_Scraper\sample_input -city.csv"

BASE_OUTPUT_FOLDER = r"C:\Users\prdas4\Downloads\2025_Projects\2025_H1\H1_2025\2-Junks Check\Petrol Pump\JioBP_Scraper\State_Wise_Output"

NETWORK_LOG_CSV = os.path.join(
    BASE_OUTPUT_FOLDER,
    "jio_bp_network_hits.csv"
)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

USER_DATA = r"C:\Users\prdas4\AppData\Local\Google\Chrome\User Data\JIOBP"

HEADLESS = False
PAGE_TIMEOUT = 60000
NAV_RETRIES = 3
SAFETY_PAGE_CEILING = 1000

COLUMNS = [
    "Brand",
    "Dealer_Name",
    "Address",
    "City",
    "State",
    "Pincode",
    "Phone",
    "Latitude",
    "Longitude",
    "Status",
    "Website_URL",
    "Google_Map_URL",
    "Detail_URL"
]


# =========================
# HELPER FUNCTIONS
# =========================

def jitter_sleep(a=0.8, b=1.6):
    time.sleep(random.uniform(a, b))


def normalize_space(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def make_safe_filename(value):
    value = str(value or "").strip()

    value = (
        value.replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace("*", "_")
        .replace("?", "_")
        .replace('"', "_")
        .replace("<", "_")
        .replace(">", "_")
        .replace("|", "_")
        .replace(" ", "_")
    )

    while "__" in value:
        value = value.replace("__", "_")

    return value.strip("_")


def clean_url(value):
    """
    Extract clean URL and remove query/fragment.
    """

    value = str(value or "").strip()

    m = re.search(r'https?://[^\s"<>\]]+', value)

    if m:
        value = m.group(0)

    if not value:
        return ""

    parts = urlsplit(value)

    scheme = parts.scheme or "https"
    netloc = parts.netloc
    path = re.sub(r"/+$", "", parts.path)

    return urlunsplit((scheme, netloc, path, "", ""))


def canonical_home_url(url):
    """
    Canonicalise station detail URL.
    """

    if not url:
        return ""

    url = clean_url(url)

    if not url:
        return ""

    parts = urlsplit(url)

    netloc = parts.netloc.lower().replace("www.", "")

    path = re.sub(
        r"(?i)/home/?$",
        "/Home",
        parts.path
    )

    return urlunsplit(("https", netloc, path, "", ""))


def build_page_url(base_url, page_no):
    if page_no <= 1:
        return base_url

    return f"{base_url}?page={page_no}"


def wait_for_any_selector(page, selectors, timeout_each=5000):
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=timeout_each)
            return sel

        except PlaywrightTimeoutError:
            continue

        except Exception:
            continue

    return None


def goto_with_retries(
    page,
    url,
    wait_selectors=None,
    timeout=PAGE_TIMEOUT,
    retries=NAV_RETRIES
):
    last_err = None

    for attempt in range(1, retries + 1):

        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout
            )

            if wait_selectors:
                wait_for_any_selector(
                    page,
                    wait_selectors,
                    timeout_each=5000
                )

            return True

        except Exception as e:
            last_err = e
            print(f"Retry {attempt}/{retries} failed for {url}: {e}")

            try:
                page.wait_for_timeout(1500 * attempt)
            except Exception:
                time.sleep(1.5 * attempt)

    print(f"FAILED to load: {url}")

    if last_err:
        print(last_err)

    return False


def visible_lines_from_html(html):
    soup = BeautifulSoup(html, "lxml")

    lines = [
        normalize_space(x)
        for x in soup.get_text("\n", strip=True).splitlines()
    ]

    return [x for x in lines if x]


def load_jsonld_objects(soup):
    objs = []

    for tag in soup.select('script[type="application/ld+json"]'):

        raw = tag.string or tag.get_text()
        raw = normalize_space(raw)

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        if isinstance(data, list):
            objs.extend(data)

        elif isinstance(data, dict):
            objs.append(data)

    return objs


def flatten_json(obj):
    stack = [obj]
    out = []

    while stack:
        item = stack.pop()

        if isinstance(item, dict):
            out.append(item)

            for v in item.values():
                if isinstance(v, (dict, list)):
                    stack.append(v)

        elif isinstance(item, list):
            stack.extend(item)

    return out


def pick_business_jsonld(objs):
    candidates = []

    for obj in objs:

        for item in flatten_json(obj):

            if not isinstance(item, dict):
                continue

            t = item.get("@type")

            if isinstance(t, str):
                types = {t.lower()}

            elif isinstance(t, list):
                types = {str(x).lower() for x in t}

            else:
                types = set()

            has_signal = any(
                k in item
                for k in (
                    "name",
                    "address",
                    "telephone",
                    "geo",
                    "url"
                )
            )

            valid_types = {
                "localbusiness",
                "gasstation",
                "store",
                "place",
                "organization"
            }

            if has_signal or types.intersection(valid_types):

                score = sum(
                    bool(item.get(k))
                    for k in (
                        "name",
                        "address",
                        "telephone",
                        "geo",
                        "url"
                    )
                )

                candidates.append((score, item))

    if not candidates:
        return {}

    candidates.sort(key=lambda x: x[0], reverse=True)

    return candidates[0][1]


def parse_address_object(address_obj):
    if isinstance(address_obj, dict):

        street = normalize_space(address_obj.get("streetAddress", ""))
        locality = normalize_space(address_obj.get("addressLocality", ""))
        region = normalize_space(address_obj.get("addressRegion", ""))
        postal = normalize_space(address_obj.get("postalCode", ""))
        country = normalize_space(address_obj.get("addressCountry", ""))

        parts = [
            p for p in [
                street,
                locality,
                region,
                postal,
                country
            ]
            if p
        ]

        full = ", ".join(parts)

        return full, locality, region, postal

    if isinstance(address_obj, str):

        full = normalize_space(address_obj)

        m = re.search(r"\b(\d{6})\b", full)
        postal = m.group(1) if m else ""

        return full, "", "", postal

    return "", "", "", ""


def derive_city_state_pin_from_text(address_text, state_hint):
    address_text = normalize_space(address_text)

    if not address_text:
        return "", state_hint, ""

    pin = ""

    m = re.search(r"\b(\d{6})\b", address_text)

    if m:
        pin = m.group(1)

    parts = [
        p.strip()
        for p in address_text.split(",")
        if p.strip()
    ]

    parts_l = [
        p.lower()
        for p in parts
    ]

    city = ""
    state = state_hint

    if state_hint:
        state_hint_l = state_hint.lower()

        for i, p in enumerate(parts_l):

            if p == state_hint_l:
                state = parts[i]

                if i > 0:
                    city = parts[i - 1]

                break

    if not city and len(parts) >= 2:

        last = parts[-1].lower()

        if last == "india":

            if len(parts) >= 3:

                if (
                    state_hint
                    and parts[-2].lower() == state_hint.lower()
                    and len(parts) >= 4
                ):
                    city = parts[-3]

                else:
                    city = parts[-2]

        else:
            city = parts[-1]

    return city, state, pin


def collect_listing_links(list_page):
    """
    Collect unique station detail links from listing page.
    """

    html = list_page.content()
    soup = BeautifulSoup(html, "lxml")

    out = []
    seen = set()

    skip_text = {
        "website",
        "home",
        "gallery",
        "map",
        "timeline",
        "contact us",
        "call now",
        "get direction",
        "next",
        "last",
        "search"
    }

    for a in soup.select("a[href]"):

        href_raw = a.get("href", "").strip()
        text = normalize_space(a.get_text(" ", strip=True))

        if not href_raw:
            continue

        href = canonical_home_url(
            urljoin(
                list_page.url,
                href_raw
            )
        )

        low = text.lower()

        if not href:
            continue

        if "mobilitystation.jiobp.com" not in href.lower():
            continue

        if not href.lower().endswith("/home"):
            continue

        if not text:
            continue

        if low in skip_text:
            continue

        if re.fullmatch(r"\d+", text):
            continue

        if href in seen:
            continue

        seen.add(href)

        out.append(
            {
                "brand_hint": text,
                "detail_url": href
            }
        )

    return out


def extract_status_from_lines(lines):
    for line in lines:
        if "Open 24 hours" in line:
            return "Open 24 hours"

    for line in lines:

        low = line.lower()

        if low.startswith("open until "):
            return line

        if low.startswith("open now"):
            return line

    return ""


def extract_detail(detail_page, state_hint, brand_hint=""):
    html = detail_page.content()
    soup = BeautifulSoup(html, "lxml")
    lines = visible_lines_from_html(html)

    jsonlds = load_jsonld_objects(soup)
    business = pick_business_jsonld(jsonlds)

    name = ""
    address = ""
    city = ""
    state = ""
    pin = ""
    phone = ""
    website = ""
    status = ""
    lat = ""
    lon = ""

    if isinstance(business, dict):

        name = normalize_space(business.get("name", ""))

        address, city, state, pin = parse_address_object(
            business.get("address", {})
        )

        phone = normalize_space(business.get("telephone", ""))
        website = normalize_space(business.get("url", ""))

        if isinstance(business.get("openingHours"), str):
            status = normalize_space(business.get("openingHours", ""))

        elif business.get("openingHoursSpecification"):
            status = "See openingHoursSpecification"

        geo = business.get("geo", {})

        if isinstance(geo, dict):
            lat = str(geo.get("latitude", "")).strip()
            lon = str(geo.get("longitude", "")).strip()

    title_text = (
        normalize_space(soup.title.get_text(" ", strip=True))
        if soup.title
        else ""
    )

    if not name:

        h1 = soup.select_one("h1")

        if h1:
            name = normalize_space(h1.get_text(" ", strip=True))

    if not name and title_text:
        name = title_text.split(":")[0].strip()

    direction_url = ""

    for a in soup.select("a[href]"):

        href = urljoin(
            detail_page.url,
            a.get("href", "").strip()
        )

        text = normalize_space(
            a.get_text(" ", strip=True)
        ).lower()

        if (
            not direction_url
            and (
                "maps.google.com" in href.lower()
                or "google.com/maps" in href.lower()
                or text == "get direction"
            )
        ):
            direction_url = href

        if not website and text == "website":
            website = href

    if not phone:

        tel = soup.select_one('a[href^="tel:"]')

        if tel:
            href = tel.get("href", "")

            phone = (
                normalize_space(href.replace("tel:", ""))
                or normalize_space(tel.get_text(" ", strip=True))
            )

    if not phone:

        for line in lines:

            if re.fullmatch(r"[+\d][\d\s\-\(\)]{7,}", line):
                phone = normalize_space(line)
                break

    if not address and phone:

        phone_idx = None

        for i, line in enumerate(lines):

            if normalize_space(line) == normalize_space(phone):
                phone_idx = i
                break

        if phone_idx is not None:

            for j in range(
                phone_idx - 1,
                max(-1, phone_idx - 6),
                -1
            ):

                cand = lines[j]
                cand_l = cand.lower()

                if cand_l in {
                    "website",
                    "call now",
                    "get direction",
                    "open now"
                }:
                    continue

                if "petrol pump" in cand_l or "reviews" in cand_l:
                    continue

                if len(cand) >= 12:
                    address = cand
                    break

    if not address:

        state_hint_l = state_hint.lower()

        for line in lines[:35]:

            low = line.lower()

            if (
                state_hint_l in low
                or "india" in low
                or re.search(r"\b\d{6}\b", line)
            ):

                if (
                    len(line) > 15
                    and not low.startswith("jio-bp")
                    and "fuel station near me" not in low
                ):
                    address = line
                    break

    if not status:
        status = extract_status_from_lines(lines)

    if not state:
        state = state_hint

    if address:

        city2, state2, pin2 = derive_city_state_pin_from_text(
            address,
            state or state_hint
        )

        if not city:
            city = city2

        if not state:
            state = state2

        if not pin:
            pin = pin2

    brand = brand_hint or name or "Jio-bp"

    dealer_name = ""

    if (
        name
        and brand_hint
        and normalize_space(name).lower() != normalize_space(brand_hint).lower()
    ):
        dealer_name = name

    elif name and not brand_hint:
        dealer_name = name

    row = {
        "Brand": brand,
        "Dealer_Name": dealer_name,
        "Address": address,
        "City": city,
        "State": state or state_hint,
        "Pincode": pin,
        "Phone": phone,
        "Latitude": lat,
        "Longitude": lon,
        "Status": status,
        "Website_URL": website,
        "Google_Map_URL": direction_url,
        "Detail_URL": canonical_home_url(detail_page.url)
    }

    return row


def save_state_files(state_rows_map):
    """
    Saves final state-wise CSV files after all input rows are processed.
    This avoids overwriting if same state appears multiple times in input CSV.
    """

    for state, rows in state_rows_map.items():

        if not rows:
            print(f"No records found for state: {state}")
            continue

        df = pd.DataFrame(rows)

        for c in COLUMNS:
            if c not in df.columns:
                df[c] = ""

        before = len(df)

        df = (
            df[COLUMNS]
            .drop_duplicates()
            .reset_index(drop=True)
        )

        after = len(df)

        safe_state = make_safe_filename(state)

        state_file = os.path.join(
            BASE_OUTPUT_FOLDER,
            f"{safe_state}_JioBP.csv"
        )

        df.to_csv(
            state_file,
            index=False,
            encoding="utf-8-sig"
        )

        print("\n" + "#" * 90)
        print(f"State          : {state}")
        print(f"Saved records  : {len(df)}")
        print(f"Duplicates     : {before - after}")
        print(f"State CSV      : {state_file}")
        print("#" * 90)


def save_master_file(all_rows):
    if not all_rows:
        print("\nNo records found. Master file not created.")
        return

    df = pd.DataFrame(all_rows)

    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""

    before = len(df)

    df = (
        df[COLUMNS]
        .drop_duplicates()
        .reset_index(drop=True)
    )

    after = len(df)

    master_file = os.path.join(
        BASE_OUTPUT_FOLDER,
        "All_States_JioBP.csv"
    )

    df.to_csv(
        master_file,
        index=False,
        encoding="utf-8-sig"
    )

    print("\n" + "=" * 90)
    print("MASTER FILE SAVED")
    print(f"Saved records      : {len(df)}")
    print(f"Duplicates removed : {before - after}")
    print(f"Master CSV         : {master_file}")
    print("=" * 90)


def save_network_log(network_hits):
    if network_hits:

        net_df = (
            pd.DataFrame(network_hits)
            .drop_duplicates()
            .reset_index(drop=True)
        )

        net_df.to_csv(
            NETWORK_LOG_CSV,
            index=False,
            encoding="utf-8-sig"
        )

        print(f"Network/API log saved: {NETWORK_LOG_CSV}")

    else:
        print("No JSON/API/XHR hits were captured in this session.")


# =========================
# MAIN
# =========================

def main():

    os.makedirs(BASE_OUTPUT_FOLDER, exist_ok=True)

    inputs = pd.read_csv(INPUT_CSV)

    all_rows = []

    state_rows_map = {}

    seen_detail_urls = set()

    network_hits = []

    with sync_playwright() as p:

        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA,
            executable_path=CHROME_PATH,
            headless=HEADLESS,
            viewport={
                "width": 1366,
                "height": 900
            },
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            ),
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-popup-blocking",
                "--disable-notifications",
                "--disable-dev-shm-usage"
            ]
        )

        list_page = context.new_page()
        detail_page = context.new_page()

        list_page.set_default_timeout(PAGE_TIMEOUT)
        detail_page.set_default_timeout(PAGE_TIMEOUT)

        list_page.set_extra_http_headers(
            {
                "Accept-Language": "en-IN,en;q=0.9",
                "Upgrade-Insecure-Requests": "1"
            }
        )

        detail_page.set_extra_http_headers(
            {
                "Accept-Language": "en-IN,en;q=0.9",
                "Upgrade-Insecure-Requests": "1"
            }
        )

        def record_response(resp):

            try:
                headers = resp.headers
                ctype = (
                    headers.get("content-type")
                    or ""
                ).lower()

            except Exception:
                ctype = ""

            url = resp.url
            url_l = url.lower()

            if (
                "/api/" in url_l
                or "graphql" in url_l
                or "_format=json" in url_l
                or url_l.endswith(".json")
                or "json" in ctype
            ):
                network_hits.append(
                    {
                        "url": url,
                        "status": resp.status,
                        "content_type": ctype
                    }
                )

        list_page.on("response", record_response)
        detail_page.on("response", record_response)

        for _, r in tqdm(
            inputs.iterrows(),
            total=len(inputs)
        ):

            state = normalize_space(r.get("State", ""))
            base = clean_url(r.get("URL", ""))

            if not state:
                print("Skipping row because State is blank.")
                continue

            if not base:
                print(f"Skipping row with empty/invalid URL for state: {state}")
                continue

            if state not in state_rows_map:
                state_rows_map[state] = []

            print("\n" + "=" * 90)
            print(f"Processing state : {state}")
            print(f"Base URL         : {base}")

            page_no = 1
            last_first_detail = None

            while page_no <= SAFETY_PAGE_CEILING:

                page_url = build_page_url(
                    base,
                    page_no
                )

                print("\n" + "-" * 90)
                print(f"Page {page_no}: {page_url}")

                loaded = goto_with_retries(
                    list_page,
                    page_url,
                    wait_selectors=[
                        "a[href*='/Home']",
                        "text=Locate Nearest Jio-bp Mobility Stations",
                        "body"
                    ]
                )

                if not loaded:
                    print("Stopping pagination because page could not be loaded.")
                    break

                print("Title    :", list_page.title())
                print("Final URL:", list_page.url)

                listing_links = collect_listing_links(list_page)

                print("Detail links found:", len(listing_links))

                if not listing_links:

                    debug_html = os.path.join(
                        BASE_OUTPUT_FOLDER,
                        f"debug_{make_safe_filename(state)}_page_{page_no}.html"
                    )

                    with open(
                        debug_html,
                        "w",
                        encoding="utf-8"
                    ) as f:
                        f.write(list_page.content())

                    print(f"No station detail links found. Debug HTML saved to: {debug_html}")
                    print("Stopping naturally.")
                    break

                current_first = listing_links[0]["detail_url"]

                if current_first == last_first_detail:
                    print("Duplicate page detected because first Detail_URL repeated. Stopping.")
                    break

                last_first_detail = current_first

                new_links = []

                for x in listing_links:

                    detail_url = x["detail_url"]

                    if detail_url in seen_detail_urls:
                        continue

                    new_links.append(x)

                if not new_links:
                    print("No new station URLs on this page. Stopping.")
                    break

                print("New detail pages to scrape:", len(new_links))

                for item in new_links:

                    detail_url = item["detail_url"]
                    brand_hint = item["brand_hint"]

                    ok = goto_with_retries(
                        detail_page,
                        detail_url,
                        wait_selectors=[
                            "text=Get Direction",
                            "text=Website",
                            "body"
                        ]
                    )

                    if not ok:
                        print(f"Skipping detail page because load failed: {detail_url}")
                        continue

                    try:
                        row = extract_detail(
                            detail_page,
                            state,
                            brand_hint=brand_hint
                        )

                        all_rows.append(row)

                        state_rows_map[state].append(row)

                        seen_detail_urls.add(detail_url)

                        print(
                            f"Scraped: {row['Brand']} | {row['Address'][:80]}"
                        )

                    except Exception as e:
                        print(f"Detail parse error for {detail_url}: {e}")

                    jitter_sleep()

                page_no += 1

                jitter_sleep()

        context.close()

    save_state_files(state_rows_map)

    save_master_file(all_rows)

    save_network_log(network_hits)


if __name__ == "__main__":
    main()