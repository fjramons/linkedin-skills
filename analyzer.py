import os
import yaml
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import plotly.express as px
import plotly.graph_objects as go
import argparse
import json
import re
from pathlib import Path

# --- Constants ---
DB_DIR = "db"
ANALYSIS_DIR = "analysis"
STATIC_DIR = os.path.join(ANALYSIS_DIR, "static")
INTERACTIVE_DIR = os.path.join(ANALYSIS_DIR, "interactive")

class SkillAnalyzer:
    def __init__(self):
        self.df = self.load_data()
        Path(STATIC_DIR).mkdir(parents=True, exist_ok=True)
        Path(INTERACTIVE_DIR).mkdir(parents=True, exist_ok=True)

    def load_data(self):
        """Loads all YAML files from db/ and flattens them into a DataFrame."""
        all_rows = []
        if not os.path.exists(DB_DIR):
            return pd.DataFrame()

        for file in os.listdir(DB_DIR):
            if file.endswith(".yaml") and file != "master_skills.yaml":
                file_path = os.path.join(DB_DIR, file)
                with open(file_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or []
                    for job in data:
                        skills = job.get("skills", [])
                        if not skills:
                            continue
                        for skill in skills:
                            all_rows.append({
                                "alert": job.get("alert"),
                                "date": str(job.get("date")),
                                "company": job.get("company"),
                                "position": job.get("position"),
                                "job_id": str(job.get("job_id")),
                                "skill_name": skill.get("name"),
                                "is_optional": skill.get("optional", False)
                            })
        
        df = pd.DataFrame(all_rows)
        if not df.empty:
            # Deduplicate by job_id and skill_name (in case same job was scraped in different alerts)
            # We keep the row but we'll handle alert-specific filtering later.
            # Actually, to avoid > 100% in "All Alerts", we need to be careful.
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
        return df

    def filter_data(self, alert=None, start_date=None, end_date=None):
        """Applies filters to the internal DataFrame."""
        df = self.df.copy()
        if df.empty:
            return df
        if alert:
            df = df[df['alert'] == alert]
        if start_date:
            df = df[df['date'] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df['date'] <= pd.to_datetime(end_date)]
        return df

    def run_demand_analysis_static(self, df, prefix="total"):
        """Generates static bar charts for top skills."""
        if df.empty:
            return

        # Deduplicate jobs for global count
        # Number of unique jobs per skill
        skill_counts = df.groupby('skill_name')['job_id'].nunique().sort_values(ascending=False).head(20).reset_index()
        skill_counts.columns = ['Skill', 'Count']

        plt.figure(figsize=(12, 8))
        sns.barplot(data=skill_counts, x='Count', y='Skill', hue='Skill', palette='viridis', legend=False)
        plt.title(f'Top 20 Demanded Skills ({prefix.capitalize()})')
        plt.tight_layout()
        plt.savefig(os.path.join(STATIC_DIR, f"demand_{prefix}.png"))
        plt.close()

    def run_cooccurrence_analysis_static(self, df, prefix="total"):
        """Generates a heatmap for skill co-occurrence."""
        if df.empty or df['job_id'].nunique() < 2:
            return

        # Unique skills per job
        unique_df = df[['job_id', 'skill_name']].drop_duplicates()
        matrix = unique_df.pivot_table(index='job_id', columns='skill_name', aggfunc='size', fill_value=0)
        
        # Calculate co-occurrence
        cooccurrence = matrix.T @ matrix
        
        # Only take top 15 skills
        top_skills = unique_df['skill_name'].value_counts().head(15).index
        cooccurrence = cooccurrence.loc[top_skills, top_skills]

        plt.figure(figsize=(10, 8))
        sns.heatmap(cooccurrence, annot=True, fmt='d', cmap='YlGnBu')
        plt.title(f'Skill Co-occurrence Heatmap ({prefix.capitalize()})')
        plt.tight_layout()
        plt.savefig(os.path.join(STATIC_DIR, f"cooccurrence_{prefix}.png"))
        plt.close()

    def run_trend_analysis_static(self, df, prefix="total"):
        """Generates trend lines for top skills over time."""
        if df.empty:
            return

        unique_df = df[['job_id', 'skill_name', 'date']].drop_duplicates()
        top_skills = unique_df['skill_name'].value_counts().head(5).index
        df_top = unique_df[unique_df['skill_name'].isin(top_skills)]
        
        trends = df_top.groupby(['date', 'skill_name']).size().unstack(fill_value=0)
        
        plt.figure(figsize=(12, 6))
        trends.plot(marker='o')
        plt.title(f'Demand Trends for Top 5 Skills ({prefix.capitalize()})')
        plt.ylabel('Number of Jobs')
        plt.legend(title='Skill')
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.tight_layout()
        plt.savefig(os.path.join(STATIC_DIR, f"trends_{prefix}.png"))
        plt.close()

    def run_alert_comparison_static(self, df, prefix="total"):
        """Compares skill distribution across different alerts using faceted panes."""
        if df.empty or df['alert'].nunique() < 2:
            return

        # Use unique jobs per alert/skill
        unique_df = df[['alert', 'job_id', 'skill_name']].drop_duplicates()
        jobs_per_alert = unique_df.groupby('alert')['job_id'].nunique()
        counts = unique_df.groupby(['alert', 'skill_name']).size().reset_index(name='count')
        counts['penetration'] = counts.apply(lambda x: (x['count'] / jobs_per_alert[x['alert']]) * 100, axis=1)

        alerts = sorted(unique_df['alert'].unique())
        n_alerts = len(alerts)
        cols = 2
        rows = (n_alerts + 1) // cols

        fig, axes = plt.subplots(rows, cols, figsize=(16, 5 * rows), squeeze=False)
        axes = axes.flatten()

        for i, alert in enumerate(alerts):
            alert_data = counts[counts['alert'] == alert].sort_values('penetration', ascending=False).head(15)
            
            sns.barplot(data=alert_data, x='penetration', y='skill_name', ax=axes[i], palette='magma', hue='skill_name', legend=False)
            axes[i].set_title(f'Alert: {alert}')
            axes[i].set_xlabel('% of Jobs')
            axes[i].set_ylabel('')
            axes[i].set_xlim(0, 105)

            for p in axes[i].patches:
                width = p.get_width()
                axes[i].text(width + 1, p.get_y() + p.get_height()/2, f'{width:.1f}%', va='center')

        for j in range(i + 1, len(axes)):
            fig.delaxes(axes[j])

        plt.suptitle(f'Skill Penetration % per Alert ({prefix.capitalize()})', fontsize=16, y=1.02)
        plt.tight_layout()
        plt.savefig(os.path.join(STATIC_DIR, f"comparison_{prefix}.png"), bbox_inches='tight')
        plt.close()

    def generate_interactive_dashboard(self):
        """Generates a dynamic HTML dashboard with client-side filtering."""
        if self.df.empty:
            print("DEBUG: No data available for interactive dashboard.")
            return

        # Prepare raw data for JS
        js_df = self.df.copy()
        js_df['date_str'] = js_df['date'].dt.strftime('%Y-%m-%d')
        # Essential columns: alert, date_str, skill_name, is_optional, job_id
        raw_data_json = json.dumps(js_df[['alert', 'date_str', 'skill_name', 'is_optional', 'job_id']].to_dict(orient='records'))
        
        alerts = sorted(js_df['alert'].unique().tolist())
        all_dates = sorted(js_df['date_str'].unique())

        # Placeholder for initial load (All Alerts, Full Range)
        # We'll just let JS handle the initial load too for consistency
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Skill Demand Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{ margin: 0; padding: 20px; background: #eee; font-family: sans-serif; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }}
        h1 {{ text-align: center; color: #333; }}
        .controls {{ padding: 20px; background: #f8f9fa; border-radius: 8px; margin-bottom: 20px; display: flex; gap: 30px; align-items: center; flex-wrap: wrap; }}
        .control-group {{ display: flex; flex-direction: column; }}
        label {{ font-weight: bold; margin-bottom: 5px; }}
        select {{ padding: 8px; border-radius: 4px; border: 1px solid #ccc; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Skill Demand Dashboard</h1>
        <div class="controls">
            <div class="control-group">
                <label>Job Alert:</label>
                <select id="alertFilter">
                    <option value="All">All Alerts</option>
                    {"".join([f'<option value="{a}">{a}</option>' for a in alerts])}
                </select>
            </div>
            <div class="control-group">
                <label>Start Date:</label>
                <select id="dateStart">
                    {"".join([f'<option value="{d}">{d}</option>' for d in all_dates])}
                </select>
            </div>
            <div class="control-group">
                <label>End Date:</label>
                <select id="dateEnd">
                    {"".join([f'<option value="{d}" {"selected" if i == len(all_dates)-1 else ""}>{d}</option>' for i, d in enumerate(all_dates)])}
                </select>
            </div>
        </div>
        <div id="plot"></div>
    </div>

    <script>
        const rawData = {raw_data_json};

        function updateChart() {{
            const selectedAlert = document.getElementById('alertFilter').value;
            const startDate = document.getElementById('dateStart').value;
            const endDate = document.getElementById('dateEnd').value;

            // 1. Filter
            const filtered = rawData.filter(d => {{
                const alertMatch = selectedAlert === "All" || d.alert === selectedAlert;
                const dateMatch = d.date_str >= startDate && d.date_str <= endDate;
                return alertMatch && dateMatch;
            }});

            if (filtered.length === 0) {{
                Plotly.newPlot('plot', [], {{ title: "No data for selected filters" }});
                return;
            }}

            // 2. Deduplicate job entries for correct penetration calculation
            // We need unique (job_id, skill_name) pairs to avoid > 100%
            const uniqueEntries = [];
            const seen = new Set();
            filtered.forEach(d => {{
                const key = d.job_id + "|" + d.skill_name;
                if (!seen.has(key)) {{
                    seen.add(key);
                    uniqueEntries.push(d);
                }}
            }});

            const uniqueJobIds = new Set(filtered.map(d => d.job_id));
            const nJobs = uniqueJobIds.size;

            // 3. Aggregate
            const counts = {{}};
            const mandCounts = {{}};
            uniqueEntries.forEach(d => {{
                counts[d.skill_name] = (counts[d.skill_name] || 0) + 1;
                if (!d.is_optional) {{
                    mandCounts[d.skill_name] = (mandCounts[d.skill_name] || 0) + 1;
                }}
            }});

            // 4. Sort and Prepare Traces
            const sortedSkills = Object.keys(counts)
                .sort((a, b) => counts[b] - counts[a])
                .slice(0, 20)
                .reverse();

            const mandPen = sortedSkills.map(s => (mandCounts[s] || 0) / nJobs * 100);
            const totalPen = sortedSkills.map(s => counts[s] / nJobs * 100);
            const optPen = sortedSkills.map((s, i) => totalPen[i] - mandPen[i]);

            const traceMand = {{
                x: mandPen, y: sortedSkills, orientation: 'h', name: 'Mandatory',
                type: 'bar', marker: {{ color: 'darkorange' }},
                text: mandPen.map(p => p > 0.1 ? p.toFixed(1) + "%" : ""),
                textposition: 'inside'
            }};

            const traceOpt = {{
                x: optPen, y: sortedSkills, orientation: 'h', name: 'Optional',
                type: 'bar', marker: {{ color: 'mediumseagreen' }},
                text: optPen.map(p => p > 0.1 ? p.toFixed(1) + "%" : ""),
                textposition: 'inside',
                customdata: totalPen,
                hovertemplate: '<b>%{{y}}</b><br>Optional bonus: %{{x:.1f}}%<br>Total: %{{customdata:.1f}}%<extra></extra>'
            }};

            const layout = {{
                barmode: 'stack',
                title: "Skill Demand: " + selectedAlert + " (" + startDate + " to " + endDate + ")",
                xaxis: {{ title: "% of Jobs", range: [0, 110] }},
                yaxis: {{ title: "" }},
                height: 700,
                margin: {{ l: 200, r: 50, t: 80, b: 50 }},
                legend: {{ orientation: "h", y: 1.05, x: 1, xanchor: 'right' }}
            }};

            Plotly.newPlot('plot', [traceMand, traceOpt], layout);
        }}

        document.getElementById('alertFilter').addEventListener('change', updateChart);
        document.getElementById('dateStart').addEventListener('change', updateChart);
        document.getElementById('dateEnd').addEventListener('change', updateChart);

        // Initial load
        updateChart();
    </script>
</body>
</html>
"""
        with open(os.path.join(INTERACTIVE_DIR, "skill_dashboard.html"), "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"Interactive dashboard saved to {INTERACTIVE_DIR}/skill_dashboard.html")

    def generate_faceted_comparison_interactive(self):
        """Generates an interactive faceted comparison with one pane per alert."""
        if self.df.empty or self.df['alert'].nunique() < 2:
            return

        unique_df = self.df[['alert', 'job_id', 'skill_name']].drop_duplicates()
        jobs_per_alert = unique_df.groupby('alert')['job_id'].nunique()
        counts = unique_df.groupby(['alert', 'skill_name']).size().reset_index(name='count')
        counts['penetration'] = counts.apply(lambda x: (x['count'] / jobs_per_alert[x['alert']]) * 100, axis=1)

        counts = counts.sort_values(['alert', 'penetration'], ascending=[True, False])
        top_counts = counts.groupby('alert').head(15)

        fig = px.bar(
            top_counts, 
            x='penetration', 
            y='skill_name', 
            facet_col='alert', 
            facet_col_wrap=2,
            orientation='h',
            title='Skill Penetration % per Alert (Faceted Comparison)',
            labels={'penetration': '% of Jobs', 'skill_name': 'Skill', 'alert': 'Alert'},
            text='penetration',
            color='alert',
            height=400 * ((len(jobs_per_alert) + 1) // 2)
        )
        
        fig.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
        fig.update_yaxes(matches=None, categoryorder='total ascending')
        fig.update_xaxes(range=[0, 115])

        fig.write_html(os.path.join(INTERACTIVE_DIR, "alert_comparison.html"))
        print(f"Interactive comparison saved to {INTERACTIVE_DIR}/alert_comparison.html")

    def run_all(self):
        """Runs the full analysis suite."""
        if self.df.empty:
            print("No data found in db/ for analysis.")
            return

        print(f"Analyzing {len(self.df)} skill entries from {self.df['job_id'].nunique()} jobs...")
        
        self.run_demand_analysis_static(self.df, "total")
        self.run_cooccurrence_analysis_static(self.df, "total")
        self.run_trend_analysis_static(self.df, "total")
        self.run_alert_comparison_static(self.df, "total")

        mandatory_df = self.df[self.df['is_optional'] == False]
        self.run_demand_analysis_static(mandatory_df, "mandatory")
        self.run_cooccurrence_analysis_static(mandatory_df, "mandatory")
        self.run_trend_analysis_static(mandatory_df, "mandatory")
        self.run_alert_comparison_static(mandatory_df, "mandatory")

        print("Generating Interactive Dashboards...")
        self.generate_interactive_dashboard()
        self.generate_faceted_comparison_interactive()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze job skill data and generate reports.")
    parser.add_argument("--alert", type=str, help="Filter by specific alert name.")
    parser.add_argument("--start-date", type=str, help="Filter by start date (YYYYMMDD).")
    parser.add_argument("--end-date", type=str, help="Filter by end date (YYYYMMDD).")
    args = parser.parse_args()

    analyzer = SkillAnalyzer()
    
    if args.alert or args.start_date or args.end_date:
        print("Applying CLI filters...")
        analyzer.df = analyzer.filter_data(args.alert, args.start_date, args.end_date)
    
    analyzer.run_all()
