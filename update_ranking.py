import urllib.request
import json
import re
import os
import time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

try:
    import schedule
except ImportError:
    print("Please 'pip install schedule'")

try:
    import requests
except ImportError:
    print("Please 'pip install requests'")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")

def analyze_changes_with_ai(old_data, new_data):
    """Call OpenRouter (Gemini) to analyze what changed"""
    system_prompt = (
        "You are an executive-level strategic AI analyst for the Board of the University of Carthage (UCAR). "
        "Your task is to analyze changes in the weekly scraped university rankings from Times Higher Education. "
        "Be very concise and deliver uncompromising, data-backed diagnostics in French."
    )
    
    prompt = (
        f"Voici les données du classement de la semaine dernière : {json.dumps(old_data['rankings'])}\n"
        f"Voici les données d'aujourd'hui : {json.dumps(new_data['rankings'])}\n"
        "Veuillez résumer les changements observés. Si rien n'a changé, confirmez-le simplement."
    )
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENROUTER_API_KEY}"
    }
    
    payload = {
        "model": "google/gemini-2.0-flash-001",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }
    
    try:
        response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        print("\n=== STRATEGIC AI ANALYSIS ===")
        print(result['choices'][0]['message']['content'])
        print("=============================\n")
    except Exception as e:
        print(f"OpenRouter API Error: {str(e)}")

def fetch_and_extract_rankings():
    url = "https://www.timeshighereducation.com/world-university-rankings/university-carthage"
    print(f"[{datetime.now()}] Fetching data from: {url}")
    
    req = urllib.request.Request(
        url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
    except Exception as e:
        print(f"Failed to fetch webpage: {e}")
        return

    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not match:
        print("Error: Could not find ranking data in the page source.")
        return
        
    try:
        next_data = json.loads(match.group(1))
        # Navigate to wurRankingsGRAData
        view_props = next_data.get('props', {}).get('pageProps', {}).get('viewProps', {})
        raw_data = view_props.get('wurRankingsGRAData')
        
        if not raw_data:
            print("Error: 'wurRankingsGRAData' not found.")
            return
            
    except Exception as e:
        print(f"Error parsing JSON data: {e}")
        return

    # Sort raw_data by year
    raw_data.sort(key=lambda x: x.get('year', 0))

    categories_map = {
        'Overall': 'world',
        'Business and Economics': 'business_economics',
        'Computer Science': 'computer_science',
        'Engineering': 'engineering',
        'Life Sciences': 'life_sciences'
    }

    score_keys = {
        'Teaching': 'teaching',
        'Research Environment': 'research_environment',
        'Research Quality': 'research_quality',
        'Industry': 'industry',
        'International Outlook': 'international_outlook',
        'Research': 'research_environment', 
        'Citations': 'research_quality',
    }

    rankings = {
        cat_id: {"rank": "", "scores": {}, "trend": []}
        for cat_id in categories_map.values()
    }

    for year_data in raw_data:
        year = year_data.get('year')
        level1s = year_data.get('level1s', [])
        for l1 in level1s:
            name = l1.get('name')
            if name not in categories_map:
                continue
            cat_id = categories_map[name]
            
            level2s = l1.get('level2s', [])
            teaching_score = None
            scores_dict = {}
            for l2 in level2s:
                metric_name = l2.get('name')
                score = l2.get('result', {}).get('score')
                if score is not None:
                    if metric_name == 'Teaching':
                        teaching_score = score
                    if metric_name in score_keys:
                        scores_dict[score_keys[metric_name]] = score
            
            if teaching_score is not None:
                rankings[cat_id]['trend'].append({
                    "year": year,
                    "teaching_score": teaching_score
                })
                
            if year == 2026:
                rankings[cat_id]['scores'] = scores_dict
                rank = l1.get('result', {}).get('rank', {}).get('displayRank', '')
                rankings[cat_id]['rank'] = rank.replace('\u2013', '-')

    # Calculate AI Insights
    def parse_rank(rstr):
        if not rstr: return 9999
        rstr = str(rstr).replace('+', '').replace('\u2013', '-')
        if '-' in rstr:
            parts = rstr.split('-')
            return (int(parts[0]) + int(parts[1])) / 2
        return int(rstr)

    best_rank_val = 9999
    best_cat = None
    for name, cat_id in categories_map.items():
        r = parse_rank(rankings[cat_id]['rank'])
        if r < best_rank_val:
            best_rank_val = r
            best_cat = name

    weakest_score_val = 999
    weakest_score_name = None
    for cat_id, data in rankings.items():
        if not data['scores']: continue
        for k, v in data['scores'].items():
            if v < weakest_score_val:
                weakest_score_val = v
                weakest_score_name = f"{k} in {cat_id}"

    fastest_improving_val = -999
    fastest_improving = None
    for name, cat_id in categories_map.items():
        tr = rankings[cat_id]['trend']
        if len(tr) >= 2:
            diff = tr[-1]['teaching_score'] - tr[0]['teaching_score']
            if diff > fastest_improving_val:
                fastest_improving_val = diff
                fastest_improving = name

    ai_insights = {
        "strongest_category": best_cat,
        "weakest_score": weakest_score_name,
        "fastest_improving": fastest_improving,
        "recommended_priority": f"Renforcer les initiatives de {weakest_score_name} pour améliorer le classement global."
    }

    final_output = {
      "university": "University of Carthage",
      "country": "Tunisia",
      "scraped_at": datetime.now().strftime("%Y-%m-%d"),
      "rankings": rankings,
      "ai_insights": ai_insights
    }

    file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extracted_ranking_data.json")
    
    # Load old data to compare
    old_data = None
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
        except Exception as e:
            print(f"Failed to read previous data: {e}")

    # Check for changes and use Grok
    if old_data:
        # Compare actual rankings string representation
        if json.dumps(old_data.get('rankings'), sort_keys=True) != json.dumps(final_output['rankings'], sort_keys=True):
            print("Changes detected! Sending to AI for analysis...")
            analyze_changes_with_ai(old_data, final_output)
        else:
            print("No changes in the data since the last check.")
    
    # Save the new file
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
        
    print(f"Successfully updated {file_path}")


def job():
    print(f"Starting weekly scheduled job...")
    fetch_and_extract_rankings()

if __name__ == "__main__":
    # Run once immediately
    job()
    
    # Schedule every week
    print("Scheduling job to run every week...")
    schedule.every().week.do(job)
    
    while True:
        schedule.run_pending()
        time.sleep(60)
