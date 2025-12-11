import google.generativeai as genai
import os
from dotenv import load_dotenv
from PIL import Image
from io import BytesIO

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("Error: GEMINI_API_KEY not found.")
    exit()

genai.configure(api_key=api_key)

def test_image_gen(model_name):
    print(f"\nTesting model: {model_name}")
    try:
        model = genai.GenerativeModel(model_name)
        # Attempt to prompt for an image
        prompt = "A beautiful oil painting of a castle on a hill, sunset, fantasy style."
        print(f"Prompting: {prompt}")
        
        # Note: The API syntax for image generation might differ.
        # Standard generate_content might return an image part if supported.
        response = model.generate_content(prompt)
        
        if response.parts:
            print("Response parts received.")
            for part in response.parts:
                if hasattr(part, 'image'):
                    print("SUCCESS: Image part found!")
                    # In a real app we would save it, here just confirming it exists
                    return True
                elif hasattr(part, 'inline_data'):
                     print("SUCCESS: Inline data (image) found!")
                     return True
        
        print("Response received but no obvious image part found.")
        print(f"Text content: {response.text}")
        return False

    except Exception as e:
        print(f"Error with {model_name}: {e}")
        return False

# Test the candidate models found earlier
models_to_test = [
    'models/nano-banana-pro-preview',
    'models/gemini-3-pro-image-preview'
]

for m in models_to_test:
    if test_image_gen(m):
        print(f"*** {m} SUPPORTS IMAGE GENERATION ***")
        break
