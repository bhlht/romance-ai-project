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
            
        # Load Trends
        self.trends = self.load_trends()

    def load_trends(self):
        try:
            import json
            with open("backend/trends.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("trends", [])
        except Exception as e:
            print(f"Error loading trends: {e}")
            return []

    async def analyze_text(self, text: str, model_name: str = 'gemini-2.5-flash-preview-09-2025') -> str:
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
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
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

    async def generate_cover_prompt(self, text, model_name: str = 'gemini-2.5-flash-preview-09-2025'):
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
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Error generating prompt: {str(e)}"

    async def generate_story_idea(self, genre="Random", spice_level="19금(없음)", model_name="gemini-2.5-flash-preview-09-2025", apply_trends=True, moods=None, male_tags=None, female_tags=None, arc="", char_sheet="", world_setting=""):
        """
        Generates a creative romance story premise based on genre, spice, and existing bible.
        """
        
        # Format trends for the prompt
        trend_context = ""
        if apply_trends and self.trends:
            trend_list = [f"- {t['name']}: {t['description']}" for t in self.trends]
            trend_context = "\n**Popular K-Romance Trends (Use ONLY if they enhance the user's selected tags):**\n" + "\n".join(trend_list)

        # Context from Bible
        bible_context = ""
        if char_sheet:
            bible_context += f"\n[EXISTING CHARACTERS]\n{char_sheet}\n"
        if world_setting:
            bible_context += f"\n[WORLD SETTING]\n{world_setting}\n"

        # User Preferences
        user_prefs = f"""
        [USER PREFERENCES - PRIORITY 1]
        - Moods: {', '.join(moods) if moods else 'Any'}
        - Male Lead Tags: {', '.join(male_tags) if male_tags else 'Any'}
        - Female Lead Tags: {', '.join(female_tags) if female_tags else 'Any'}
        - Character Arc: {arc if arc else 'Any'}
        """

        prompt = f"""
        Generate a unique, creative, and engaging romance novel premis.
        
        **Target Genre**: {genre}
        **Spice Level (수위)**: {spice_level}
        
        {user_prefs}
        {bible_context}
        {trend_context}
        
        **CRITICAL INSTRUCTION**: 
        1. **User Preferences are ABSOLUTE**. If the user selected 'Kind' Male Lead, do NOT make him a 'Regretful Jerk' unless explicitly asked. 
        2. **Trends are SECONDARY**. Use trends (e.g., Regret, Possession) ONLY if they fit the User Preferences. Do not override user tags with trends.
        3. **Gap Moe**: If traits seem contradictory (e.g., 'Cold' + 'Kind'), interpret it as duality (e.g., Cold to others, Kind to FL).
        4. **Existing Data**: If [EXISTING CHARACTERS] or [WORLD] provided, weave the new plot around them.

        Include the following elements:
        1. **Characters & Dynamics**: Incorporate the selected traits naturally.
        2. **Tone & Mood**: Reflect the selected situations.
        3. **Plot Twist / Hook**: A unique conflict.
        
        Format the output clearly so the user can easily read and edit it.
        Keep it concise (around 150 words).
        IMPORTANT: Output MUST be in Korean language. (한국어로 작성해 주세요)
        """
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Error generating story idea: {str(e)}"

    async def generate_plot(self, settings: dict, model_name="gemini-2.5-flash-preview-09-2025") -> str:
        """
        Generates a structured plot outline based on provided settings.
        """
        idea_context = ""
        if settings.get('idea_premise'):
            idea_context = f"\n[CORE STORY IDEA]\n{settings.get('idea_premise')}\n"

        prompt = f"""
        Act as a professional romance novel editor.
        Create a detailed, chapter-by-chapter plot outline based on the following story settings.
        {idea_context}
        [STORY SETTINGS]
        - Genre: {settings.get('genre', 'Romance')}
        - Spice Level: {settings.get('spice', 'Unknown')}
        - Mood: {settings.get('mood', 'Unknown')}
        - Characters: {settings.get('chars', 'Unknown')}
        - World Setting: {settings.get('world', 'Unknown')}
        - Theme/Arc: {settings.get('arc', 'Unknown')}
        - Trends: {settings.get('trends', 'None')}

        [INSTRUCTION]
        Provide a detailed **Chapter-by-Chapter Outline** (Total 40-50 Chapters) based on the **4-Part Structure** (Kishotenketsu).
        
        **CRITICAL**: You MUST use the characters and world setting provided above. Do not invent new main characters if they are already defined. Refine them if necessary, but keep the core identity.
        - Part 1 (Introduction): Approx 1-10 Chapters
        - Part 2 (Development): Approx 11-25 Chapters
        - Part 3 (Twist/Climax): Approx 26-40 Chapters
        - Part 4 (Conclusion): Approx 41-50 Chapters
        
        IMPORTANT: Output MUST be in Korean.
        """
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Plot Generation Error: {str(e)}"

    async def generate_full_outline(self, settings: dict, total_chapters=50, model_name="gemini-2.0-pro-exp-02-05", reference_outline: str = ""):
        """
        Generates a 50-chapter outline.
        If reference_outline is provided, it expands/refines it instead of creating from scratch.
        """
        
        base_instruction = ""
        if reference_outline:
            base_instruction = f"""
            [EXISTING PLOT OUTLINE]
            {reference_outline}

            [INSTRUCTION]
            Based on the [EXISTING PLOT OUTLINE], expand and structure it into exactly {total_chapters} chapters.
            - Keep the original plot points and arc.
            - Break down the existing summary into detailed chapters.
            - If the existing outline is short, fill in the gaps creatively to reach {total_chapters} chapters.
            """
        else:
            base_instruction = f"""
            Create a NEW, original 50-chapter outline based on the settings below.
            """

        prompt = f"""
        Act as a Professional Web Novel Planner.
        
        {base_instruction}

        [Story Settings]
        - Genre: {settings.get('genre', 'Romance')}
        - Theme: {settings.get('theme', 'Love')}
        - Characters: {settings.get('characters', 'Unknown')}
        - Conflict: {settings.get('conflict', 'Standard')}

        [Structure: Kishotenketsu (4 Parts)]
        - Part 1 (Introduction): Approx 1-{int(total_chapters * 0.2)} Chapters
        - Part 2 (Development): Approx {int(total_chapters * 0.2) + 1}-{int(total_chapters * 0.5)} Chapters
        - Part 3 (Twist/Climax): Approx {int(total_chapters * 0.5) + 1}-{int(total_chapters * 0.8)} Chapters
        - Part 4 (Conclusion): Approx {int(total_chapters * 0.8) + 1}-{total_chapters} Chapters

        **CRITICAL REQUIREMENTS**:
        1. **Emotional Arc**: For each chapter, specify the emotional change.
        2. **Conflict**: Every chapter must have a clear conflict.
        3. **Pacing**: Indicate pacing (Action/Introspection).
        
        Format:
        ## 1. Introduction (Setup)
        - Chapter 1: [Title] [Summary] (Emotion: A->B)
        - Chapter 2: ...
        
        ## 2. Development (Rising Action)
        ...
        
        IMPORTANT: Output MUST be in Korean (한국어로 작성).
        Ensure the story flows logically for a long-form web novel (300 pages).
        """
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            cleaned = response.text.strip()
            return self._parse_outline_to_json(cleaned, total_chapters)
        except Exception as e:
            return {"error": f"Plot Generation Error: {str(e)}"}

    def _parse_outline_to_json(self, text, total_chapters):
        """
        Parses the text outline into a structure for the batch generator.
        Expected format:
        ## 1. Part Title
        - Chapter 1: Title ...
        """
        chapters = []
        current_part = ""
        import re
        
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # Match Part
            if line.startswith("##"):
                current_part = line.replace("##", "").strip()
            
            # Match Chapter
            # Regex to match "- Chapter 1: Title" or "Chapter 1: Title"
            match = re.search(r'(?:-\s*)?Chapter\s*(\d+)\s*[:.]\s*(.+)', line, re.IGNORECASE)
            if match:
                ch_num = int(match.group(1))
                content = match.group(2)
                
                # Split title and summary if possible
                title = content
                summary = content
                
                # Check for "Summary" or parenthesis
                if "(" in content:
                    parts = content.split("(", 1)
                    title = parts[0].strip()
                    summary = parts[1].strip().rstrip(")")
                
                chapters.append({
                    "chapter_num": ch_num,
                    "title": title,
                    "summary": f"[{current_part}] {summary}",
                    "key_events": [summary] # Simple default
                })
        
        # Fallback if parsing failed
        if not chapters:
            return {"error": "Failed to parse outline. Raw text: " + text[:500]}
            
        return {"chapters": chapters}

    async def generate_marketing_data(self, text, model_name="gemini-2.5-flash-preview-09-2025"):
        prompt = f"""
        Analyze the following romance novel content and generate a marketing package in JSON format.
        
        Required JSON Structure:
        {{
            "titles": ["Catchy Title 1", "Catchy Title 2", "Catchy Title 3", "Catchy Title 4", "Catchy Title 5"],
            "blurb": "A compelling introduction/blurb to hook readers (paragraph form).",
            "summary": "A concise plot summary (3-5 sentences).",
            "keywords": ["Keyword1", "Keyword2", "Keyword3", "Keyword4", "Keyword5"]
        }}

        Content:
        {text[:10000]}

        IMPORTANT: Output values MUST be in KOREAN. Return ONLY raw JSON.
        """
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            # Cleanup JSON
            cleaned = response.text.replace("```json", "").replace("```", "").strip()
            import json
            return json.loads(cleaned)
        except Exception as e:
            return {"error": f"Error generating marketing data: {str(e)}"}

    async def check_consistency(self, text, char_sheet, world_setting, model_name="gemini-2.5-flash-preview-09-2025"):
        prompt = f"""
        You are a Consistency Editor for a novel.
        Compare the [Story Content] with the [Story Bible] and identify errors.

        [Story Bible]
        - Characters: {char_sheet}
        - World: {world_setting}

        [Story Content]
        {text}

        Analyze for:
        1. **Name Errors**: Characters referred to by wrong names or spellings.
        2. **Character Errors**: Actions contradicting the character sheet (unless explained).
        3. **Plot/World Errors**: Contradictions with the world setting or previous events (if evident).
        4. **Typos/Grammar**: Major issues only.

        Output JSON structure:
        {{
            "name_errors": ["Error 1", "Error 2"],
            "plot_errors": ["Error 1", "Error 2"],
            "suggestions": ["Suggestion 1"]
        }}
        
        IMPORTANT: Output values in Korean. Return ONLY raw JSON.
        """
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            cleaned = response.text.replace("```json", "").replace("```", "").strip()
            import json
            return json.loads(cleaned)
        except Exception as e:
            return {"error": f"Consistency check failed: {str(e)}"}

    async def perform_comprehensive_review(self, text, criteria="Consistency, Grammar, Creativity", model_name="gemini-2.0-pro-exp-02-05"):
        """
        Performs a deep review of the text based on specific criteria.
        Returns a JSON report with scores and detailed feedback.
        """
        prompt = f"""
        You are an elite Novel Editor. Review the following text strictly.

        [Criteria]
        {criteria}
        - **Show, Don't Tell**: Check if emotions are shown through action/senses, not just stated.
        - **Deep POV**: Check if the narrative stays deep in the character's perspective.
        - **Pacing**: Check if the flow matches the scene's intent.

        [Text to Review]
        {text}

        Provide a structured JSON Review Report:
        {{
            "scores": {{
                "consistency": <int 1-100>,
                "grammar_flow": <int 1-100>,
                "creativity": <int 1-100>
            }},
            "feedback": {{
                "consistency": "Detailed feedback in Korean...",
                "grammar_flow": "Detailed feedback in Korean...",
                "creativity": "Detailed feedback in Korean..."
            }},
            "overall_critique": "Overall summary of the chapter quality in Korean.",
            "improvement_suggestions": ["Suggestion 1", "Suggestion 2"]
        }}

        IMPORTANT: Output MUST be valid JSON. All text values should be in Korean.
        """
        try:
            # Use a smarter model if possible, defaulting to the requested one
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            cleaned = response.text.replace("```json", "").replace("```", "").strip()
            import json
            return json.loads(cleaned)
        except Exception as e:
             # Fallback to flash if Pro fails or not available
            try:
                model = genai.GenerativeModel("gemini-1.5-flash")
                response = model.generate_content(prompt)
                cleaned = response.text.replace("```json", "").replace("```", "").strip()
                import json
                return json.loads(cleaned)
            except Exception as inner_e:
                return {"error": f"Review failed: {str(inner_e)}"}

    async def rewrite_story_segment(self, text, critique, char_sheet, world_setting, model_name="gemini-2.0-pro-exp-02-05") -> str:
        """
        Rewrites the story segment based on the provided critique and Story Bible.
        Ensures consistency and improved quality.
        """
        prompt = f"""
        You are an elite Novel Editor and Ghostwriter. 
        Your task is to REWRITE the following story segment to improve it based on the critique, 
        while strictly adhering to the Story Bible.

        [Story Bible - Consistency Check]
        - Characters: {char_sheet}
        - World Setting: {world_setting}

        [Critique / Improvement Goals]
        {critique}

        [Original Text]
        {text}

        [Instruction]
        1. Apply the critique points (e.g., Show Don't Tell, fix plotholes).
        2. MAINTAIN key plot points unless they violate the Story Bible.
        3. Ensure the tone and character voices match the Story Bible.
        4. Output ONLY the rewritten text in Korean. Do not include explanations.

        Rewritten Version:
        """
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Rewrite failed: {str(e)}"

    async def generate_full_outline(self, settings: dict, total_chapters=50, model_name="gemini-2.0-pro-exp-02-05") -> dict:
        """
        Generates a 50-chapter outline.
        """
        prompt = f"""
        You are a Master Plotter. Create a detailed {total_chapters}-chapter outline for a romance novel.
        
        [Settings]
        - Genre: {settings.get('genre')}
        - Theme: {settings.get('theme')}
        - Main Characters: {settings.get('characters')}
        - Key Conflict: {settings.get('conflict')}
        
        Output a JSON object containing a list of chapters.
        Structure:
        {{
            "title": "Novel Title",
            "chapters": [
                {{
                    "chapter_num": 1,
                    "title": "Chapter Title",
                    "summary": "Detailed summary of events (3-4 sentences). Focus on plot progression and emotional beats.",
                    "key_events": ["Event 1", "Event 2"]
                }},
                ... (up to {total_chapters})
            ]
        }}
        
        IMPORTANT: Output values in Korean. Return ONLY raw JSON. Valid JSON is critical.
        """
        try:
             model = genai.GenerativeModel(model_name)
             # High token limit needed for long outline
             response = model.generate_content(prompt, generation_config={"max_output_tokens": 8192})
             cleaned = response.text.replace("```json", "").replace("```", "").strip()
             import json
             return json.loads(cleaned)
        except Exception as e:
            return {"error": f"Outline generation failed: {str(e)}"}

    async def generate_image_imagen3(self, prompt, model_name="imagen-3.0-generate-001"):
        """
        Generates an image using Imagen 3.
        """
        try:
            # Note: The specific API call for Imagen 3 via 'genai' might vary.
            # Assuming standard generation model interface for now, or using specific endpoint.
            # If standard model interface doesn't work, we might need specific client configurations.
            # For now, we reuse the existing image model logic but with the specific model name.
            
            # If the user has access to Imagen 3 via the same API key:
            model = genai.GenerativeModel(model_name) 
            response = model.generate_content(prompt)
            
            if response.parts:
                for part in response.parts:
                    if hasattr(part, 'image'):
                         import base64
                         from io import BytesIO
                         img = part.image
                         buffered = BytesIO()
                         img.save(buffered, format="PNG")
                         img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
                         return {"image_base64": img_str}
                    elif hasattr(part, 'inline_data'):
                        import base64
                        return {"image_base64": base64.b64encode(part.inline_data.data).decode("utf-8")}
            
            return {"error": "No image generated."}
        except Exception as e:
            return {"error": f"Imagen 3 generation failed: {str(e)}"}

    async def summarize_context(self, text, model_name="gemini-2.5-flash-preview-09-2025"):
        prompt = f"""
        Summarize the following story segment into a concise 3-5 sentence paragraph. 
        Focus on key events, character development, and changes in relationship dynamics.
        This summary will be used as memory for the AI to write the next chapter.

        Content:
        {text}

        IMPORTANT: Output in Korean.
        """
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Summary Error: {str(e)}"

    async def generate_story_content(self, prompt, temperature=0.7, model_name="gemini-2.5-flash-preview-09-2025"):
        try:
            model = genai.GenerativeModel(
                model_name,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=4000 # Allow very long generation
                )
            )
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Error: {str(e)}"

    async def evaluate_plot_potential(self, settings: dict, outline: str, model_name="gemini-2.0-pro-exp-02-05") -> dict:
        """
        Analyzes the plot outline and settings for commercial potential.
        Returns a JSON report.
        """
        prompt = f"""
        Act as a Veteran Editor-in-Chief of a top web novel platform.
        Analyze the following 'Romance Novel Plan' and predict its commercial success.

        [Story Settings]
        - Genre: {settings.get('genre')}
        - Mood: {settings.get('mood')}
        - Characters: {settings.get('characters')}
        - World Setting: {settings.get('world')}
        - Trends Applied: {settings.get('trends')}

        [Plot Outline]
        {outline[:15000]} 

        [Analysis Criteria]
        1. **Commercial Viability (0-100)**: Does it fit current market trends (e.g., Regret, Possession, Revenge, Cider)?
        2. **Target Audience**: Who will pay for this? (Age, Gender, Buying Power).
        3. **Binge-Reading Factor (0-100)**: Are the cliffhangers strong? Is the pacing fast?
        4. **SWOT Analysis**: Strengths, Weaknesses, Opportunities, Threats.

        [Output Format (JSON)]
        {{
            "commercial_score": <int 0-100>,
            "binge_score": <int 0-100>,
            "target_audience": {{
                "age": "e.g., 20-30s",
                "gender": "e.g., Female",
                "buying_power": "High/Medium/Low"
            }},
            "swot": {{
                "strengths": ["Point 1", "Point 2"],
                "weaknesses": ["Point 1", "Point 2"],
                "opportunities": ["Point 1", "Point 2"],
                "threats": ["Point 1", "Point 2"]
            }},
            "overall_review": "Comprehensive feedback (3-4 sentences).",
            "improvement_advice": "Key advice to increase success rate."
        }}

        IMPORTANT: Output values in Korean (한국어로 작성). Return ONLY raw JSON.
        """
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            cleaned = response.text.replace("```json", "").replace("```", "").strip()
            import json
            return json.loads(cleaned)
        except Exception as e:
            return {"error": f"Evaluation failed: {str(e)}"}

    async def generate_book_packaging(self, settings: dict, outline: str, model_name="gemini-2.0-pro-exp-02-05") -> dict:
        """
        Generates Title, Blurb (Intro), and Keywords.
        """
        prompt = f"""
        Act as a Best-selling Web Novel Editor.
        Create a 'Book Packaging' set for the following story.

        [Genre] {settings.get('genre')}
        [Trends] {settings.get('trends')}
        [Mood & Atmosphere] {settings.get('mood')}
        [Character Dynamics] {settings.get('characters')}
        [World Setting] {settings.get('world')}
        
        [Story Content (Excerpt/Summary)]
        {outline[:300000]}

        [Requirements]
        1. **Titles**: 5 Catchy, Trend-following titles (e.g., "The Villainess...", "Level Up...").
        2. **Blurb (Intro)**: A compelling 3-paragraph introduction for the platform main page. Hook the reader immediately.
           - **MUST reflect the Mood and Character Dynamics**.
           - If the mood is 'Sad', make it poignant. If 'Sweet', make it fluttery.
        3. **Keywords**: 10 hashtags #Keyword for search optimization.

        [Output JSON]
        {{
            "titles": ["Title 1", "Title 2", ...],
            "blurb": "Full blurb text...",
            "keywords": ["#Tag1", "#Tag2", ...]
        }}
        
        IMPORTANT: Output in Korean. Return ONLY raw JSON.
        """
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            cleaned = response.text.replace("```json", "").replace("```", "").strip()
            import json
            return json.loads(cleaned)
        except Exception as e:
            return {"error": f"Packaging failed: {str(e)}"}

    async def auto_improve_plot(self, settings: dict, outline: str, advice: str, model_name="gemini-2.0-pro-exp-02-05") -> str:
        """
        Rewrites the plot outline to incorporate specific improvement advice.
        """
        prompt = f"""
        Act as a Professional Novel Editor.
        Your task is to IMPROVE the following Plot Outline based on the provided Advice.

        [Story Settings]
        - Genre: {settings.get('genre')}
        - Mood: {settings.get('mood')}
        - Characters: {settings.get('characters')}
        - World: {settings.get('world')}

        [Current Plot Outline]
        {outline}

        [Advice for Improvement]
        {advice}

        [Instruction]
        Rewrite the plot outline to be more commercially successful and engaging, incorporating the advice above.
        Keep the JSON format or structured text format.
        IMPORTANT: Output in Korean.
        """
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Improvement failed: {str(e)}"

    async def rewrite_improved_content(self, original_text: str, critique_json: dict, model_name="gemini-2.0-pro-exp-02-05") -> str:
        """
        Rewrites the story content based on the critique to improve quality.
        Targeting 'Self-Healing' workflow.
        """
        critique_text = critique_json.get("overall_critique", "")
        suggestions = "\n".join(critique_json.get("improvement_suggestions", []))
        
        prompt = f"""
        Act as a Best-Selling Author and Editor.
        Your task is to REWRITE the following chapter text to improve its quality based on the critique.

        [Critique / Diagnosis]
        {critique_text}
        
        [Specific Improvements Needed]
        {suggestions}

        [Original Text]
        {original_text}

        [Instruction]
        1. **Show, Don't Tell**: Convert abstract emotions into physical actions.
        2. **Pacing**: Fix any pacing issues mentioned.
        3. **Dialogue**: Make dialogue more natural and character-specific.
        4. **Maintain Plot**: Do not change the core events, just enhance the execution.

        Output the REWRITTEN chapter text only (in Korean).
        """
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Rewrite failed: {str(e)}"

gemini_service = GeminiService()
