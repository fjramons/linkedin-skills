import os
import random
import time
import re
import toml
import argparse
import urllib.parse
from pathlib import Path
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# --- Constants & Config ---
CONFIG_FILE = "config.toml"
TEMPLATE_FILE = "template.config.toml"
CHROME_PROFILE_DIR = ".chrome_profile"
OUTPUT_DIR = "output"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        if os.path.exists(TEMPLATE_FILE):
            print(f"Config file not found. Creating {CONFIG_FILE} from {TEMPLATE_FILE}...")
            import shutil
            shutil.copy(TEMPLATE_FILE, CONFIG_FILE)
            print("Please edit config.toml with your job alert details.")
        else:
            print(f"ERROR: Neither {CONFIG_FILE} nor {TEMPLATE_FILE} found.")
            return {
                "settings": {"max_jobs_per_alert": 10},
                "delays": {"avg_wait_seconds": 60, "wait_variance": 30},
                "alerts": []
            }
    
    return toml.load(CONFIG_FILE)

CONFIG = load_config()
MAX_JOBS = CONFIG["settings"].get("max_jobs_per_alert", 10)
AVG_WAIT = CONFIG["delays"].get("avg_wait_seconds", 60)
WAIT_VARIANCE = CONFIG["delays"].get("wait_variance", 30)
ALERTS = CONFIG.get("alerts", [])

# --- Helper Functions ---

def human_delay():
    wait_time = random.uniform(AVG_WAIT - WAIT_VARIANCE, AVG_WAIT + WAIT_VARIANCE)
    print(f"Waiting for {wait_time:.2f} seconds...")
    time.sleep(wait_time)

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name).replace(" ", "_")

def parse_relative_date(relative_str):
    # Default to current date if parsing fails
    now = datetime.now()
    clean_str = relative_str.lower().replace("posted", "").strip()
    
    try:
        # Regex to find number and unit
        match = re.search(r'(\d+)\s+(second|minute|hour|day|week|month|year)s?', clean_str)
        if match:
            value = int(match.group(1))
            unit = match.group(2)
            
            if "second" in unit:
                delta = timedelta(seconds=value)
            elif "minute" in unit:
                delta = timedelta(minutes=value)
            elif "hour" in unit:
                delta = timedelta(hours=value)
            elif "day" in unit:
                delta = timedelta(days=value)
            elif "week" in unit:
                delta = timedelta(weeks=value)
            elif "month" in unit:
                delta = timedelta(days=value * 30)
            elif "year" in unit:
                delta = timedelta(days=value * 365)
            else:
                delta = timedelta(0)
            return (now - delta).strftime("%Y%m%d")
        
        if "yesterday" in clean_str:
            return (now - timedelta(days=1)).strftime("%Y%m%d")
    except Exception:
        pass
    return now.strftime("%Y%m%d")

def format_markdown(title, company, posted_date, job_id, url, description):
    description = description.replace("•", "-").replace("*", "_")
    
    md = f"# {title}\n\n"
    md += "## Metadata\n\n"
    md += f"- **Company**: {company}\n"
    md += f"- **Posted**: {posted_date}\n"
    md += f"- **Job ID**: {job_id}\n"
    md += f"- **URL**: <{url}>\n\n"
    md += "## Description\n\n"
    md += description.strip()
    md += "\n"
    
    return md

def build_search_url(alert):
    keywords = urllib.parse.quote(alert.get("keywords", ""))
    location = urllib.parse.quote(alert.get("location", ""))
    
    # Base search URL
    url = f"https://www.linkedin.com/jobs/search/?keywords={keywords}&location={location}&distance=25"
    
    # f_WT=2 -> Remote
    if alert.get("remote"):
        url += "&f_WT=2"
        
    return url

def discover_jobs_with_scroll(page, target_count):
    """Scrolls the job results pane to discover up to target_count jobs."""
    jobs_dict = {} # Use dict to store unique jobs by ID: {id: metadata}
    
    print(f"Scrolling to discover up to {target_count} jobs...")
    
    # 1. Try to find the scrollable container
    # LinkedIn uses various structures; we try the most common ones
    container_selectors = [
        "div.jobs-search-results-list",
        ".scaffold-layout__list-container",
        "main[role='main']",
        "div[data-test-results-container]",
        ".jobs-search-results-list__container"
    ]
    
    container = None
    for sel in container_selectors:
        try:
            container = page.query_selector(sel)
            if container and container.is_visible():
                print(f"Found scrollable container: {sel}")
                container.click()
                break
        except Exception:
            continue

    last_count = 0
    stagnant_scrolls = 0
    
    while len(jobs_dict) < target_count and stagnant_scrolls < 8:
        # Extract currently visible job cards
        cards = page.query_selector_all(".job-card-container, [data-job-id], .jobs-search-results__list-item")
        
        initial_len = len(jobs_dict)
        for card in cards:
            job_id = card.get_attribute("data-job-id")
            if not job_id:
                link_elem = card.query_selector("a[href*='/view/']")
                if link_elem:
                    href = link_elem.get_attribute("href")
                    match = re.search(r'/view/(\d+)', href)
                    if match:
                        job_id = match.group(1)
            
            if job_id and job_id not in jobs_dict:
                # Basic metadata extraction from card
                title_elem = card.query_selector(".job-card-list__title, .job-card-container__link, .artdeco-entity-lockup__title")
                company_elem = card.query_selector(".job-card-container__primary-description, .job-card-container__company-name, .artdeco-entity-lockup__subtitle")
                
                title = title_elem.inner_text().strip().split('\n')[0] if title_elem else "Unknown Title"
                company = company_elem.inner_text().strip().split('\n')[0] if company_elem else "Unknown Company"
                
                jobs_dict[job_id] = {
                    "id": job_id,
                    "title": title,
                    "company": company,
                    "url": f"https://www.linkedin.com/jobs/view/{job_id}/"
                }
                
                if len(jobs_dict) >= target_count:
                    break
        
        if len(jobs_dict) >= target_count:
            break
            
        if len(jobs_dict) == initial_len:
            stagnant_scrolls += 1
        else:
            stagnant_scrolls = 0
            
        # Scroll down
        if cards:
            try:
                # Target the last card to force lazy loading
                cards[-1].scroll_into_view_if_needed()
                # Randomized additional scroll
                page.mouse.wheel(0, random.randint(400, 800))
            except Exception:
                page.keyboard.press("PageDown")
        else:
            page.keyboard.press("PageDown")
        
        # Wait for lazy loading
        time.sleep(2)
        
        # Check for "See more jobs" button
        try:
            see_more_btn = page.get_by_role("button", name=re.compile("See more jobs", re.IGNORECASE))
            if see_more_btn.is_visible():
                print("Clicking 'See more jobs'...")
                see_more_btn.click()
                time.sleep(3)
        except Exception:
            pass

    print(f"Discovery complete. Found {len(jobs_dict)} unique jobs.")
    return list(jobs_dict.values())

# --- Main Scraper ---

def run_scraper(dry_run=False, check_alerts=False):
    if not os.path.exists(CHROME_PROFILE_DIR):
        print("\nERROR: No browser session found.")
        print("Please run 'uv run python login.py' first to log in.")
        return

    if not ALERTS:
        print("\nERROR: No alerts configured in config.toml.")
        return

    if check_alerts:
        print(f"Configured Alerts ({len(ALERTS)}):")
        for a in ALERTS:
            print(f"- {a['name']} (Keywords: {a['keywords']}, Location: {a['location']})")
        return

    if not dry_run:
        Path(OUTPUT_DIR).mkdir(exist_ok=True)
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE_DIR,
            headless=False,
            args=["--start-maximized"]
        )
        
        page = context.new_page()
        Stealth().apply_stealth_sync(page)
        
        for alert_info in ALERTS:
            alert_name = alert_info["name"]
            alert_url = build_search_url(alert_info)
            
            print(f"\nProcessing alert: {alert_name}")
            print(f"Search URL: {alert_url}")
            
            if not dry_run:
                alert_folder = Path(OUTPUT_DIR) / sanitize_filename(alert_name)
                alert_folder.mkdir(exist_ok=True)
            
            page.goto(alert_url, wait_until="domcontentloaded")
            page.wait_for_load_state("domcontentloaded")
            
            try:
                print("Waiting for search results to appear...")
                # Check for security wall first
                if "checkpoint" in page.url or page.query_selector(".challenge-dialog"):
                    print("\n" + "!"*50)
                    print("SECURITY CHECK DETECTED")
                    print("Please solve the CAPTCHA/Security check in the browser window.")
                    print("!"*50 + "\n")
                    page.wait_for_selector(".jobs-search-results-list, .scaffold-layout__list-container", timeout=0)

                page.wait_for_selector(".jobs-search-results-list, .scaffold-layout__list-container, [class*='results-list'], main ul", timeout=30000)
                time.sleep(3)
            except Exception:
                print(f"Could not load search results for alert: {alert_name}")
                continue
            
            # Use scrolling to discover up to MAX_JOBS
            jobs_to_process = discover_jobs_with_scroll(page, MAX_JOBS)
            
            for index, job_info in enumerate(jobs_to_process):
                job_id = job_info["id"]
                job_title = job_info["title"]
                job_company = job_info["company"]
                job_url = job_info["url"]
                
                if not dry_run:
                    # Idempotency check across all date subfolders for this alert
                    # New format: <YYYYMMDD>-<Job_name>-<Company_name>-<jobid>.md
                    existing_files = list(alert_folder.glob(f"**/*-{job_id}.md"))
                    if existing_files:
                        print(f"Job {job_id} ({job_title}) already exists in {existing_files[0].parent.name}. Skipping.")
                        continue
                
                if dry_run:
                    print(f"[Dry-Run] Processing: {job_title} at {job_company} (ID: {job_id})")
                    # In dry run we still want to click to verify loading
                    try:
                        # Find the card again in case DOM was refreshed during scroll
                        card = page.query_selector(f"[data-job-id='{job_id}']")
                        if card:
                            card.scroll_into_view_if_needed()
                            card.click()
                            time.sleep(3)
                        else:
                            # Fallback: navigate directly
                            page.goto(job_url, wait_until="domcontentloaded")
                            time.sleep(3)
                        
                        page.wait_for_selector(".jobs-search__job-details, .jobs-details-pane, .jobs-description, #job-details", timeout=15000)
                        print(f"[Dry-Run] Successfully loaded details for {job_id}")
                    except Exception:
                        print(f"Could not load details for job {job_id} in side pane. URL: {page.url}")
                        continue
                else:
                    print(f"Fetching: {job_title} at {job_company} (ID: {job_id})...")
                    # Click the card to view details in the pane
                    try:
                        card = page.query_selector(f"[data-job-id='{job_id}']")
                        if card:
                            card.scroll_into_view_if_needed()
                            card.click()
                            time.sleep(3)
                        else:
                            page.goto(job_url, wait_until="domcontentloaded")
                            time.sleep(3)
                            
                        # Target selectors specifically in the detail pane
                        page.wait_for_selector(".jobs-search__job-details, .jobs-details-pane, .jobs-description, #job-details", timeout=15000)
                        
                        # Re-extract metadata for accuracy
                        detail_pane = page.query_selector(".jobs-search__job-details, .jobs-details-pane, #job-details")
                        if detail_pane:
                            pane_title_elem = detail_pane.query_selector(".jobs-unified-top-card__job-title, .job-details-jobs-unified-top-card__job-title, h2, h1")
                            pane_company_elem = detail_pane.query_selector(".jobs-unified-top-card__company-name, .job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name a")
                            
                            if pane_title_elem:
                                refined_title = pane_title_elem.inner_text().strip().split('\n')[0]
                                if refined_title and "notification" not in refined_title.lower():
                                    job_title = refined_title
                                    
                            if pane_company_elem:
                                refined_company = pane_company_elem.inner_text().strip().split('\n')[0]
                                if refined_company:
                                    job_company = refined_company

                    except Exception:
                        print(f"Could not load details for job {job_id} in side pane.")
                        continue

                    # Extraction logic (from the pane)
                    print(f"Extracting: {job_title} at {job_company} (ID: {job_id})...")
                    posted_date = "Unknown"
                    posted_elems = page.query_selector_all(".jobs-search__job-details span, .jobs-unified-top-card__primary-description-container span")
                    for p in posted_elems:
                        txt = p.inner_text().strip()
                        if "Posted" in txt or "ago" in txt:
                            posted_date = txt
                            break
                    
                    # Parse to absolute date for folder organization
                    abs_date = parse_relative_date(posted_date)
                    date_folder = alert_folder / abs_date
                    date_folder.mkdir(exist_ok=True)
                    
                    desc_elem = page.query_selector(".jobs-description__content, #job-details, .show-more-less-html__markup")
                    description = desc_elem.inner_text().strip() if desc_elem else "No description found."
                    
                    md_content = format_markdown(job_title, job_company, posted_date, job_id, f"https://www.linkedin.com/jobs/view/{job_id}/", description)
                    
                    # New filename format: <YYYYMMDD>-<Job_name>-<Company_name>-<jobid>.md
                    safe_title = sanitize_filename(job_title)
                    safe_company = sanitize_filename(job_company)
                    filename = f"{abs_date}-{safe_title}-{safe_company}-{job_id}.md"
                    
                    with open(date_folder / filename, "w", encoding="utf-8") as f:
                        f.write(md_content)
                    
                    print(f"Saved to {abs_date}/: {filename}")
                
                if index < len(jobs_to_process) - 1:
                    human_delay()

        print("\nProcessing complete.")
        context.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LinkedIn Job Scraper")
    parser.add_argument("--dry-run", action="store_true", help="Run without downloading files, browses jobs")
    parser.add_argument("--check-alerts", action="store_true", help="Only verify the configured alerts in config.toml")
    args = parser.parse_args()
    
    run_scraper(dry_run=args.dry_run, check_alerts=args.check_alerts)
