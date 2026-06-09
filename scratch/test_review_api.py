import requests
import json
import os

def run_test():
    filepath = r"d:\myProject\streamlit\story_data\bhlht3\My_romance_20260601.json"
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
        
    with open(filepath, "r", encoding="utf-8") as f:
        story_data = json.load(f)
        
    memory_chain = story_data.get("memory_chain", [])
    print(f"Loaded memory chain with {len(memory_chain)} items.")
    
    payload = {
        "text": "",
        "memory_chain": memory_chain,
        "criteria": "Consistency, Grammar, Creativity",
        "model": "models/gemini-2.5-flash"
    }
    
    # Let's try port 8082
    url = "http://127.0.0.1:8082/analyze/review_comprehensive"
    try:
        print(f"Sending request to {url}...")
        res = requests.post(url, json=payload, timeout=60)
        print(f"Status Code: {res.status_code}")
        if res.status_code == 200:
            print("Response JSON:")
            print(json.dumps(res.json(), ensure_ascii=False, indent=2))
        else:
            print(f"Error: {res.text}")
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    run_test()
