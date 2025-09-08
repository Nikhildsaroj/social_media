# streamlit_scraper.py
# Public Contact Info Scraper – Streamlit + Playwright (Async API, Windows-friendly)

import re
import pandas as pd
import phonenumbers
from urllib.parse import urlparse
import streamlit as st
import nest_asyncio
import asyncio
import sys
from playwright.async_api import async_playwright

# ====================
# Event loop patching
# ====================
nest_asyncio.apply()
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ===== CONFIG =====
SOCIAL_OPTIONS = {
    "Facebook": "facebook.com",
    "LinkedIn": "linkedin.com",
    "Instagram": "instagram.com",
    "Twitter": "twitter.com",
    "X": "x.com"
}

INDIAN_KEYWORDS = [
    "India", "Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai",
    "Kolkata", "Ahmedabad", "Pune", "Jaipur", "Surat", "Lucknow"
]

# --- Validate Indian phone numbers ---
def validate_indian_number(num_str: str) -> bool:
    try:
        num = phonenumbers.parse(num_str, "IN")
        return phonenumbers.is_valid_number(num) and phonenumbers.region_code_for_number(num) == "IN"
    except:
        return False

# --- Extract contacts from HTML ---
def extract_contacts_from_html(html: str):
    emails = list(set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", html)))
    raw_phones = re.findall(r"\b(?:\+91[-\s]?)?[6-9]\d{9}\b", html)

    clean_phones = []
    for ph in set(raw_phones):
        digits = re.sub(r"\D", "", ph)
        if not digits.startswith("91") and len(digits) == 10:
            digits = "91" + digits
        candidate = "+" + digits
        if validate_indian_number(candidate):
            clean_phones.append(candidate)

    return emails, clean_phones

# --- Build Google query ---
def build_query(keyword: str, selected_domains):
    india_hint = " OR ".join([f'"{k}"' for k in INDIAN_KEYWORDS])
    contact_hint = '(intext:"email" OR intext:"@" OR intext:"gmail.com" OR intext:"yahoo.com" OR intext:"outlook.com" OR intext:"contact")'
    phone_hint = '(intext:"phone" OR intext:"mobile" OR intext:"WhatsApp" OR intext:"call")'
    domains = " OR ".join([f"site:{d}" for d in selected_domains])
    return f'({domains}) "{keyword}" ({india_hint}) {contact_hint} {phone_hint}'

# --- Async scraping function ---
async def scrape_social_media_async(keyword: str, selected_domains, max_results: int, progress=None):
    rows = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        page = await browser.new_page()

        query = build_query(keyword, selected_domains)
        search_url = "https://www.google.com/search?q=" + query.replace(" ", "+")
        await page.goto(search_url, timeout=60000)

        # Handle consent
        html = await page.content()
        if "Before you continue" in html or "consent" in page.url:
            try:
                await page.click("button:has-text('I agree')", timeout=5000)
                await page.wait_for_timeout(2000)
            except:
                pass

        links = []
        while len(links) < max_results:
            results = await page.query_selector_all("a h3")
            for r in results:
                parent = await r.evaluate_handle("node => node.parentElement")
                href = await parent.get_attribute("href")
                if href and any(d in href for d in selected_domains) and href not in links:
                    links.append(href)
                    if len(links) >= max_results:
                        break

            next_btn = await page.query_selector("a#pnnext")
            if not next_btn or len(links) >= max_results:
                break
            await next_btn.click()
            await page.wait_for_timeout(2000)

        # Visit each link and extract contacts
        for i, link in enumerate(links, 1):
            try:
                new_page = await browser.new_page()
                await new_page.goto(link, timeout=60000)
                await new_page.wait_for_timeout(3000)
                html = await new_page.content()
                await new_page.close()

                emails, phones = extract_contacts_from_html(html)
                rows.append({
                    "keyword": keyword,
                    "url": link,
                    "domain": urlparse(link).netloc,
                    "emails": ", ".join(emails),
                    "phones": ", ".join(phones),
                })
                if progress:
                    progress.progress(i / len(links))
            except Exception as e:
                print(f"❌ Error scraping {link}: {e}")
                continue

        await browser.close()
    return rows

# --- Wrapper for Streamlit (use running loop) ---
def scrape_social_media(keyword, selected_domains, max_results, progress=None):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(scrape_social_media_async(keyword, selected_domains, max_results, progress))

# ===== Streamlit UI =====
def main():
    st.title("📡 Public Contact Info Scraper (Playwright)")
    st.write("Extract emails & phones from Google results + target sites.")

    keyword = st.text_input("Enter your keyword (e.g., dental lab, jewelry manufacturer)")
    max_results = st.number_input("How many results?", min_value=10, max_value=200, value=50, step=10)

    selected = st.multiselect("Select social platforms", list(SOCIAL_OPTIONS.keys()), default=["LinkedIn", "Facebook"])
    selected_domains = [SOCIAL_OPTIONS[s] for s in selected]

    if st.button("Start Scraping"):
        if not keyword:
            st.warning("Please enter a keyword")
            return

        progress = st.progress(0)
        rows = scrape_social_media(keyword, selected_domains, max_results, progress)
        df = pd.DataFrame(rows)

        if df.empty:
            st.error("No data extracted.")
        else:
            st.success(f"✅ Extracted {len(df)} contacts")
            st.dataframe(df)
            st.download_button("Download Excel", df.to_excel(index=False), "contacts.xlsx")

if __name__ == "__main__":
    main()
