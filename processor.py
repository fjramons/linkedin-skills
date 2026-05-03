import os
import re
import yaml
import argparse
import toml
from pathlib import Path
from datetime import datetime

# --- Constants ---
CONFIG_FILE = "config.toml"
OUTPUT_DIR = "output"
DB_DIR = "db"
MASTER_SKILLS_FILE = os.path.join(DB_DIR, "master_skills.yaml")

def load_config():
    if os.path.exists(CONFIG_FILE):
        return toml.load(CONFIG_FILE)
    return {}

class JobProcessor:
    def __init__(self, api_key=None):
        self.config = load_config()
        self.api_key = api_key or self.config.get("processor", {}).get("gemini_api_key")
        self.master_skills = self.load_master_skills()
        
    def load_master_skills(self):
        if os.path.exists(MASTER_SKILLS_FILE):
            with open(MASTER_SKILLS_FILE, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or []
        return []

    def save_master_skills(self, skills):
        Path(DB_DIR).mkdir(exist_ok=True)
        with open(MASTER_SKILLS_FILE, "w", encoding="utf-8") as f:
            yaml.dump(skills, f, allow_unicode=True, sort_keys=False)

    def sync_skills(self, sample_size=5):
        """Uses Gemini API to discover new skills from a sample of jobs."""
        if not self.api_key:
            print("ERROR: Gemini API key not found. Set it in config.toml or pass via --api-key.")
            return

        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')

        print(f"Syncing skills using LLM (sampling {sample_size} jobs)...")
        
        # Collect sample text
        samples = []
        for root, _, files in os.walk(OUTPUT_DIR):
            for file in files:
                if file.endswith(".md"):
                    with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                        content = f.read()
                        # Get only the description part
                        desc_match = re.search(r"## Description\n(.*)", content, re.DOTALL)
                        if desc_match:
                            samples.append(desc_match.group(1)[:1000]) # First 1000 chars
                if len(samples) >= sample_size:
                    break
            if len(samples) >= sample_size:
                break

        if not samples:
            print("No job descriptions found to scan.")
            return

        prompt = f"""
        Extract a comprehensive list of technical and soft skills from these job descriptions.
        For each skill, provide a 'name' (normalized) and 'aliases' (variations found in text).
        Return ONLY a YAML-formatted list like this:
        - name: Python
          aliases: [Python 3, Py]
        
        Job Descriptions:
        {" ".join(samples)}
        """
        
        try:
            response = model.generate_content(prompt)
            new_skills_raw = response.text
            # Clean up potential markdown code blocks
            new_skills_raw = re.sub(r"```yaml\n|```", "", new_skills_raw)
            new_skills = yaml.safe_load(new_skills_raw)
            
            if isinstance(new_skills, list):
                # Merge with existing
                existing_names = {s['name'].lower(): i for i, s in enumerate(self.master_skills)}
                for ns in new_skills:
                    name_lower = ns['name'].lower()
                    if name_lower in existing_names:
                        idx = existing_names[name_lower]
                        # Merge aliases
                        current_aliases = set(self.master_skills[idx].get('aliases', []))
                        new_aliases = set(ns.get('aliases', []))
                        self.master_skills[idx]['aliases'] = list(current_aliases.union(new_aliases))
                    else:
                        self.master_skills.append(ns)
                
                self.save_master_skills(self.master_skills)
                print(f"Successfully synced skills. Master list now has {len(self.master_skills)} entries.")
            else:
                print("Unexpected response format from LLM.")
        except Exception as e:
            print(f"Error syncing skills: {e}")

    def extract_metadata(self, file_path):
        """Extracts metadata from the markdown file and its path."""
        path_parts = Path(file_path).parts
        # Path: output/<Alert_Name>/<YYYYMMDD>/<File>
        alert_name = path_parts[1].replace("_", " ")
        date_str = path_parts[2]
        
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Metadata extraction
        title_match = re.search(r"^# (.*)", content)
        company_match = re.search(r"- \*\*Company\*\*: (.*)", content)
        job_id_match = re.search(r"- \*\*Job ID\*\*: (.*)", content)
        
        title = title_match.group(1).strip() if title_match else "Unknown"
        company = company_match.group(1).strip() if company_match else "Unknown"
        job_id = job_id_match.group(1).strip() if job_id_match else os.path.basename(file_path).split("-")[-1].replace(".md", "")
        
        desc_match = re.search(r"## Description\n(.*)", content, re.DOTALL)
        description = desc_match.group(1).strip() if desc_match else ""
        
        return {
            "alert": alert_name,
            "date": date_str,
            "company": company,
            "position": title,
            "job_id": job_id,
            "description": description
        }

    def extract_skills_from_text(self, text):
        """Finds skills from the master list in the text."""
        found_skills = []
        text_lower = text.lower()
        
        # Track found skill names to ensure uniqueness per job
        seen_skills = set()
        
        for skill_info in self.master_skills:
            name = skill_info['name']
            if name in seen_skills:
                continue
                
            aliases = [name] + skill_info.get('aliases', [])
            
            for alias in aliases:
                # Use word boundaries
                pattern = r'\b' + re.escape(alias.lower()) + r'\b'
                match = re.search(pattern, text_lower)
                
                if match:
                    # Check for "optional" context around the match
                    # Search ~80 chars before the match (increased window)
                    start = max(0, match.start() - 80)
                    context = text_lower[start:match.start()]
                    
                    optional_keywords = [
                        "plus", "desirable", "bonus", "preferred", "optional", "nice to have", "advantage",
                        "valorará", "valorara", "deseable", "deseamos", "plus", "extra", "preferible", "ventaja",
                        "conocimientos de", "conocimiento de" # Sometimes indicate non-core
                    ]
                    is_optional = any(ok in context for ok in optional_keywords)
                    
                    found_skills.append({
                        "name": name,
                        "optional": is_optional
                    })
                    seen_skills.add(name)
                    break # Found this skill, move to next in master list
                    
        return found_skills

    def process_all(self, target_alert=None):
        """Scans all output files and updates the database."""
        Path(DB_DIR).mkdir(exist_ok=True)
        
        if not os.path.exists(OUTPUT_DIR):
            print(f"ERROR: Output directory '{OUTPUT_DIR}' not found.")
            return

        for alert_folder in os.listdir(OUTPUT_DIR):
            if target_alert and alert_folder.lower() != target_alert.lower().replace(" ", "_"):
                continue
                
            alert_path = os.path.join(OUTPUT_DIR, alert_folder)
            if not os.path.isdir(alert_path):
                continue
                
            print(f"Processing alert: {alert_folder}")
            
            db_file = os.path.join(DB_DIR, f"{alert_folder}.yaml")
            existing_data = []
            if os.path.exists(db_file):
                with open(db_file, "r", encoding="utf-8") as f:
                    existing_data = yaml.safe_load(f) or []
            
            processed_ids = {str(job['job_id']) for job in existing_data}
            new_entries = 0
            
            # Walk through date folders
            for date_folder in os.listdir(alert_path):
                date_path = os.path.join(alert_path, date_folder)
                if not os.path.isdir(date_path):
                    continue
                    
                for file in os.listdir(date_path):
                    if not file.endswith(".md"):
                        continue
                        
                    file_path = os.path.join(date_path, file)
                    
                    # Quick check for job_id in filename for idempotency
                    job_id_match = re.search(r"-(\d+)\.md$", file)
                    if job_id_match:
                        if job_id_match.group(1) in processed_ids:
                            continue
                    
                    # Full metadata extraction
                    metadata = self.extract_metadata(file_path)
                    if metadata['job_id'] in processed_ids:
                        continue
                        
                    print(f"  Extracting skills for: {metadata['position']} ({metadata['job_id']})")
                    skills = self.extract_skills_from_text(metadata['description'])
                    
                    # Build entry
                    entry = {
                        "alert": metadata['alert'],
                        "date": metadata['date'],
                        "company": metadata['company'],
                        "position": metadata['position'],
                        "job_id": metadata['job_id'],
                        "skills": skills
                    }
                    
                    existing_data.append(entry)
                    processed_ids.add(metadata['job_id'])
                    new_entries += 1
            
            if new_entries > 0:
                with open(db_file, "w", encoding="utf-8") as f:
                    yaml.dump(existing_data, f, allow_unicode=True, sort_keys=False)
                print(f"  Done. Added {new_entries} new jobs to {db_file}")
            else:
                print(f"  No new jobs to process for {alert_folder}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process job descriptions and extract skills.")
    parser.add_argument("--sync-skills", action="store_true", help="Refresh the master skill list using LLM (requires API key).")
    parser.add_argument("--alert", type=str, help="Process only a specific alert name.")
    parser.add_argument("--api-key", type=str, help="Manually provide Gemini API key.")
    args = parser.parse_args()
    
    processor = JobProcessor(api_key=args.api_key)
    
    if args.sync_skills:
        processor.sync_skills()
    else:
        processor.process_all(target_alert=args.alert)
