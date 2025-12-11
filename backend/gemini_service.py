import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

class GeminiService:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            print("Warning: GEMINI_API_KEY not found in environment variables.")
        else:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel('gemini-2.5-flash-preview-09-2025')
            self.image_model = genai.GenerativeModel('models/nano-banana-pro-preview') # Direct Image Generation Model

    async def analyze_text(self, text: str) -> str:
        if not self.api_key:
            return "Error: Gemini API Key is missing. Please configure the server."

        prompt = f"""
        You are an expert romance novel editor. 
        Please analyze the following text for:
        1. Plot holes or inconsistencies.
        2. Emotional depth and character motivation errors.
        3. Stylistic suggestions to improve the romantic atmosphere.
        
        Text to analyze:
        {text}
        
        Provide your critique in a structured format.
        IMPORTANT: Output MUST be in Korean language. (한국어로 작성해 주세요)
        """
        
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Error interacting with Gemini API: {str(e)}"

    async def analyze_novel_content(self, text: str) -> dict:
        """
        Analyzes a novel text to extract metadata.
        Target Output: JSON with genre, keywords, mood, summary.
        """
        if not self.api_key:
            return {"error": "Gemini API Key missing"}

        # Truncate text if too long to save cost/time (optional, can be adjusted)
        # Using first 30,000 characters is usually enough for style/intro, 
        # but for full summary, we might need more. 
        # Gemini 1.5 Flash is recommended for full context. 
        # Truncating to 1,000,000 characters (approx 200k-300k tokens).
        # Gemini 1.5 Flash supports up to 1M tokens, so this is safe and allows full summary.
        
        prompt = f"""
        Analyze the following novel content/excerpt and provide a JSON response.
        Do not include markdown formatting like ```json ... ```, just the raw JSON.
        
        Required JSON Structure:
        {{
            "genre": "Specific Sub-genre",
            "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
            "mood": "Overall atmosphere (e.g., Melancholic, Cheerful, Tense)",
            "summary": "A concise plot summary (3-5 sentences)."
        }}

        Novel Content:
        {text[:1000000]} 
        """
        # Truncating to 1M chars to prevent extreme edge cases/memory issues, 
        # but this covers almost all standard romance novels.
        
        try:
            response = self.model.generate_content(prompt)
            # Simple cleanup to ensure valid JSON
            import json
            cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
            return json.loads(cleaned_text)
        except Exception as e:
            return {"error": f"Analysis failed: {str(e)}", "raw_response": str(e)}

    async def generate_cover_prompt(self, text):
        prompt = f"""
        Based on the following romance story, write a detailed, high-quality image generation prompt suitable for AI art tools like Midjourney, DALL-E 3, or Stable Diffusion.
        
        Focus on:
        - Main characters (appearance, clothing)
        - Setting (background, lighting, atmosphere)
        - Artistic style (e.g., Oil painting, Digital Art, Watercolor, Cinematic lighting)
        - Color palette
        
        The output should be a single string in English, ready to be pasted into an image generator.
        Format: "An exquisite digital art cover of... [details] ... --ar 2:3"

        Story Context:
        {text[:5000]}
        """
        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Error generating prompt: {str(e)}"

    async def generate_story_idea(self):
        """
        Generates a creative romance story premise.
        """
        prompt = """
        Generate a unique, creative, and engaging romance novel premis.
        Include the following elements:
        1. **Characters & Dynamics**: Brief description of the two protagonists and their relationship (e.g., Rivals, Childhood friends).
        2. **Tone & Mood**: e.g., Dark Academia, Fluffy Rom-Com, Angst-filled.
        3. **Plot Twist / Hook**: A unique conflict or secret that drives the story.
        
        Format the output clearly so the user can easily read and edit it.
        Keep it concise (around 150 words).
        IMPORTANT: Output MUST be in Korean language. (한국어로 작성해 주세요)
        """
        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Error generating story idea: {str(e)}"

    async def generate_cover_image(self, prompt):
        """
        Generates an image using Nano Banana Pro (Gemini Image Model).
        Returns base64 encoded image or error.
        """
        try:
            # Note: This API call might differ based on exact library version, 
            # but usually it's generate_content with text prompt for image models.
            response = self.image_model.generate_content(prompt)
            
            # Check for image parts
            if response.parts:
                for part in response.parts:
                    if hasattr(part, 'image'):
                         # Return the raw image blob or bytes
                         # Google GenAI library returns PIL Image or Blob usually.
                         # We need to convert it to base64 for API transfer.
                         import base64
                         from io import BytesIO
                         
                         img = part.image
                         buffered = BytesIO()
                         img.save(buffered, format="PNG")
                         img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
                         return {"image_base64": img_str}
                    elif hasattr(part, 'inline_data'):
                        # Handle raw inline data
                        import base64
                        return {"image_base64": base64.b64encode(part.inline_data.data).decode("utf-8")}
                        
            return {"error": "No image generated. Safety filters might have blocked it."}
        except Exception as e:
            return {"error": f"Image generation failed: {str(e)}"}

gemini_service = GeminiService()
