# LinkedIn Job Scraper - Project Instructions

This project automates the collection of job descriptions from LinkedIn based on manually configured search alerts. It prioritizes account safety, data organization, and idempotent execution.

## Objective
Automatically scrape the top _N_ job descriptions for multiple job alerts and save them as organized, parsable Markdown files for further analysis.

## Core Workflows

### 1. Authentication (`login.py`)
- **First-Time Setup**: Run `uv run python login.py` to create a persistent session in `.chrome_profile/`.
- **Manual Step**: The user must log in and navigate to the Jobs page in the opened browser window before pressing Enter in the terminal.
- **Persistence**: Once established, the session is reused by the scraper without further interaction.

### 2. Scraping (`scraper.py`)
- **Direct Search URLs**: The scraper bypasses brittle UI navigation by building direct search URLs from `config.toml`.
- **Click-to-View Strategy**: Instead of direct navigation to job URLs (which can trigger security checks), the script stays on the search page and clicks each job card to load details in the side pane.
- **Modes**: 
  - `--check-alerts`: Diagnostic tool to verify `config.toml` entries.
  - `--dry-run`: Full navigation test that prints titles/companies without downloading data.
  - Normal Run: Performs full metadata and description extraction.

### 3. Skill Extraction (`processor.py`)
- **Master Skill List**: Uses `db/master_skills.yaml` to normalize skill names (e.g., "Python 3" -> "Python").
- **NLP Extraction**: Scans descriptions using the master list. Detects "optional" skills based on context (e.g., "plus", "bonus").
- **Sync Mode**: Use `--sync-skills` with a Gemini API key to update the master list from current job samples.
- **Idempotency**: Checks `job_id` in `db/*.yaml` to skip already processed jobs.

### 4. Skill Analysis (`analyzer.py`)
- **Data Source**: Aggregates all job data from the `db/` folder. Implements ID-based deduplication to ensure accurate penetration percentages (avoiding >100%).
- **Static Reports**: Generates PNG charts in `analysis/static/` for demand, co-occurrence, trends, and faceted alert comparisons.
- **Dynamic Dashboards**: 
  - `skill_dashboard.html`: Fully dynamic view with client-side filtering by **Alert** and **Date Range** (Start/End). Supports "Optional" toggle via legend.
  - `alert_comparison.html`: Faceted side-by-side comparison of all alerts with percentage labels.
- **Filtering**: Supports both interactive HTML controls and CLI filters.

## Engineering Standards

### Idempotency
- Before every download, the script checks for the `jobid` suffix (e.g., `*-<jobid>.md`) across *all* date subfolders within the alert's directory.
- Jobs are skipped if they already exist, preventing redundant traffic and storage.

### Data Organization
- **Structure**: `output/<Alert_Name>/<YYYYMMDD>/<YYYYMMDD>-<Job_name>-<Company_name>-<jobid>.md`.
- **Date Parsing**: Relative LinkedIn dates (e.g., "2 days ago") are parsed into approximate absolute `YYYYMMDD` timestamps.

### Markdown Style
- **Bullets**: Always use `-`.
- **Italics**: Always use `_`.
- **Spacing**: Exactly one empty line before/after headers, lists, and literal sections.
- **Metadata**: Structured under an `## Metadata` header with bulleted key-value pairs for easy parsing.

### Anti-Detection
- **Stealth**: Uses `playwright-stealth` to mask automation signals.
- **Randomization**: Implements a 1-minute average delay between job extractions, with configurable variance in `config.toml`.
- **UI Interaction**: Includes auto-scrolling and specific waits to mimic human reading behavior.

## Configuration (`config.toml`)
- **Initialization**: Automatically created from `template.config.toml` if missing.
- **Git Strategy**: `config.toml` is ignored by version control to protect personal preferences.
- **Settings**: Control `max_jobs_per_alert`.
- **Delays**: Adjust `avg_wait_seconds` and `wait_variance`.
- **Alerts**: Define list of `[[alerts]]` with `name`, `keywords`, `location`, and optional `remote = true`.
