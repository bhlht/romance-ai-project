import google.generativeai as genai
import os

with open(r"d:\myProject\streamlit\.env", "r") as f:
    for line in f:
        if line.strip() and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            os.environ[k] = v

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

for m in genai.list_models():
    if "generateContent" in m.supported_generation_methods:
        print(f"Model: {m.name}, Output Limit: {m.output_token_limit}")
