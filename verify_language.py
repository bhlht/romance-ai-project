import requests
import json

BACKEND_URL = "https://romance-ai-backend-46410417920.asia-southeast1.run.app"

def run_test():
    data = {
        "story": "태준은 지수의 눈을 바라보았다.",
        "chapter_focus": "갈등 장면",
        "chars": "태준, 지수",
        "rel_map": "갈등",
        "model": "models/gemini-3-flash-preview"
    }
    try:
        res = requests.post(f"{BACKEND_URL}/analyze/next_choices", json=data)
        result = {
            "status": res.status_code,
            "choices": res.json().get("choices", [])
        }
        with open("d:/myProject/streamlit/test_result_final.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("Test results written to test_result_final.json")
    except Exception as e:
        print(f"Test failed: {e}")

if __name__ == "__main__":
    run_test()
