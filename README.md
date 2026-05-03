# LinkedIn Job Scraper

A Python application designed to automatically gather job descriptions from your LinkedIn job alerts and save them as organized, parsable Markdown files.

## Overview

This tool automates the process of visiting each of your LinkedIn job alerts, extracting the top _N_ results, and saving the full description text.

- **Session Reuse**: Uses a dedicated browser profile to keep you logged in.
- **Anti-Detection**: Randomized human-like delays (averaging 1 minute) to protect your account.
- **Idempotency**: Skips jobs you have already downloaded.
- **Organized Output**: Organizes jobs into folders by alert name.
- **Skill Extraction**: Automatically identifies and normalizes skills from job descriptions, saving them to YAML files in `db/`.

## Installation

### Prerequisites

- **Python 3.11+**
- **uv** (recommended)

### Setup

1. Clone or download this repository.
2. Initialize the project and install browsers:

```bash
uv init
uv add playwright playwright-stealth toml
uv run playwright install chromium
```

## First-Time Setup (Login)

Because LinkedIn requires authentication, you must log in once to create a session profile.

1. Run the login helper:
   ```bash
   uv run python login.py
   ```
2. A browser window will open. Log in to your LinkedIn account.
3. Navigate to [Manage Job Alerts](https://www.linkedin.com/jobs/manage/) to confirm you can see your alerts.
4. Return to the terminal and press **Enter** to save the session.

## Configuration

On the first run, the scraper will create a local `config.toml` from `template.config.toml`. You should edit this file to customize the number of jobs and your job alert details.

**Note**: `config.toml` is ignored by Git to protect your personal search preferences.

```toml
[settings]
max_jobs_per_alert = 10

[delays]
avg_wait_seconds = 60
wait_variance = 30

[[alerts]]
name = "Cloud Architect"
keywords = "Cloud Architect"
location = "Madrid, Spain"
```

## Usage

### Check Alerts Mode
Verify that the script can see your alerts without browsing individual jobs:
```bash
uv run python scraper.py --check-alerts
```

### Dry-Run Mode
Test the navigation and see job titles/companies without downloading files:
```bash
uv run python scraper.py --dry-run
```

### Normal Run
Scrape job descriptions:
```bash
uv run python scraper.py
```

### Skill Extraction
Process downloaded job descriptions and extract normalized skills:
```bash
uv run python processor.py
```
- Results are saved to `db/<Alert_Name>.yaml`.
- Use `--sync-skills` to update the master skill list using an LLM (requires API key in `config.toml`).

## Output Format

Job descriptions are saved in the `output/` folder, organized by alert name and date. Each file follows this strict Markdown format:

```markdown
# [Job Title]

## Metadata

- **Company**: [Name]
- **Posted**: [Date]
- **Job ID**: [ID]
- **URL**: <[LinkedIn URL]>

## Description

[Cleaned Job Description]
```

## Technical Notes

- Data is saved in the `output/` folder.
- The browser session is stored in `.chrome_profile/`.
- Both folders are ignored by Git.
