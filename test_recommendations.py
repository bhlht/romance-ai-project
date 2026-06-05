import requests
import json
import os

BACKEND_URL = "https://romance-ai-backend-46410417920.asia-southeast1.run.app"

def test_recommendations():
    print("Testing /analyze/next_choices for language stability...")
    data = {
        "story": "태준은 지수의 눈을 바라보았다. 그는 그녀가 자신의 제안을 받아들일지 확신할 수 없었다.",
        "chapter_focus": "두 사람의 갈등이 최고조에 달하며 감정이 폭발하는 장면",
        "chars": "태준: 차가운 재벌 3세. 지수: 가난하지만 당당한 화가.",
        "rel_map": "계속되는 오해로 인한 갈등 관계",
        "model": "models/gemini-3-flash-preview"
    }
    
    try:
        res = requests.post(f"{BACKEND_URL}/analyze/next_choices", json=data)
        print(f"Status: {res.status_code}")
        if res.status_code == 200:
            choices = res.json().get("choices", [])
            print("--- CHOICES ---")
            for i, c in enumerate(choices):
                print(f"Option {i}: {c}")
                # Check for English (Latin alphabet chars)
                import re
                if re.search("[a-zA-Z]", c):
                    print(f"Warning: Option {i} contains English characters!")
        else:
            print(f"Error: {res.text}")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_recommendations()
