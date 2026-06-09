import json

filepath = r"d:\myProject\streamlit\story_data\bhlht3\My_romance_20260601.json"
try:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    review = data.get("review_result", {})
    print("--- SAVED REVIEW RESULT ---")
    print(json.dumps(review, ensure_ascii=False, indent=2))
except Exception as e:
    print("Error:", e)
