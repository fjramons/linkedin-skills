from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import os
from pathlib import Path

CHROME_PROFILE_DIR = ".chrome_profile"

def run_login():
    print("\n" + "="*50)
    print("LINKEDIN LOGIN HELPER")
    print("="*50)
    print(f"This script will open a browser to save your session in: {CHROME_PROFILE_DIR}")
    print("\nSteps:")
    print("1. A browser window will open.")
    print("2. Log in to LinkedIn manually.")
    print("3. Navigate to: https://www.linkedin.com/jobs/")
    print("4. Find and click 'Preferences' in the left pane.")
    print("5. Click 'Job alerts' (or 'Manage job alerts') that appears under Preferences.")
    print("6. Verify your alerts are visible in the pane/modal.")
    print("7. Return here and press Enter to save the session and close.")
    print("="*50 + "\n")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE_DIR,
            headless=False,
            args=["--start-maximized"]
        )
        
        page = context.new_page()
        Stealth().apply_stealth_sync(page)
        
        page.goto("https://www.linkedin.com/jobs/")
        
        input("Press Enter here AFTER you have logged in and can see your 'Manage job alerts' pane...")
        
        print("Session saved. Closing browser...")
        context.close()
    
    print("\nSetup complete! You can now run the scraper.")

if __name__ == "__main__":
    run_login()
