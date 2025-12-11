import google.generativeai as genai
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("Error: GEMINI_API_KEY not found.")
    exit()

genai.configure(api_key=api_key)

# Initialize with the model currently in use
model_name = 'gemini-3-pro-preview'
model = genai.GenerativeModel(model_name)

async def test_idea():
    print(f"Testing idea generation with {model_name}...")
    try:
        prompt = "Generate a unique, creative, and engaging romance novel premis."
        response = await model.generate_content_async(prompt)
        print("Success!")
        print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_idea())
