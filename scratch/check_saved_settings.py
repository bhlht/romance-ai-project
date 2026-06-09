import json

filepath = r"d:\myProject\streamlit\story_data\bhlht3\My_romance_20260601.json"
try:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    print("setting_temperature:", data.get("setting_temperature"))
    print("setting_humor:", data.get("setting_humor"))
except Exception as e:
    print("Error:", e)
