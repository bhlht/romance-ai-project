import json
import sys

def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    path = r"d:\myProject\streamlit\story_data\bhlht3\My_romance_20260601.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    chapters = data.get("chapters", {})
    ch15 = chapters.get("15", "")
    print(f"Chapter 15 length: {len(ch15)} chars")
    print("--- Chapter 15 end snippet ---")
    print(ch15[-300:])

if __name__ == "__main__":
    main()
