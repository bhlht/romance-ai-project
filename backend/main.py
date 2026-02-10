from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv

# Import local modules
from backend.model import romance_model
from backend.gemini_service import gemini_service
from backend.export_service import export_service
from fastapi.responses import StreamingResponse
import io

load_dotenv()

class GenerateRequest(BaseModel):
    prompt: str
    max_length: int = 2000 # Increased for stylistic depth
    temperature: float = 0.7
    model: str = "gemini-2.5-flash-preview-09-2025"

class AnalyzeRequest(BaseModel):
    text: str
    model: str = "gemini-2.5-flash-preview-09-2025"

class AnalyzeNovelRequest(BaseModel):
    text: str = None
    file_url: str = None
    model: str = "gemini-2.5-flash-preview-09-2025"

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load model lazily on first request
    print("🚀 Server Started. Model will be loaded on first use.")
    yield
    # Clean up (if needed)
    # Clean up (if needed)

app = FastAPI(title="Romance AI API", lifespan=lifespan)

# Add CORS Middleware to allow requests from any origin (e.g., Localhost Frontend, Mobile App)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"status": "running", "model_loaded": romance_model.is_loaded}

@app.post("/generate/romance")
async def generate_romance(request: GenerateRequest):
    try:
        # Check model selection
        # Check model selection
        if request.model == "DeepSeek-7B (Fine-tuned)":
            print("Generating with Local DeepSeek Model...")
            
            # Lazy Loading
            if not romance_model.is_loaded:
                print("⏳ Loading Model on First Request...")
                romance_model.load_model()
                
            generated_text = await romance_model.generate_text(
                prompt=request.prompt,
                max_length=request.max_length,
                temperature=request.temperature
            )
        else:
            # Use Gemini Service
            generated_text = await gemini_service.generate_story_content(
                prompt=request.prompt,
                temperature=request.temperature,
                model_name=request.model
            )
        return {"generated_text": generated_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze/title")
async def analyze_title(request: AnalyzeRequest):
    try:
        result = await gemini_service.generate_marketing_data(request.text, request.model)
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze/feedback")
async def analyze_feedback(request: AnalyzeRequest):
    try:
        critique = await gemini_service.analyze_text(request.text, request.model)
        return {"critique": critique}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class AnalyzeConsistencyRequest(BaseModel):
    text: str
    char_sheet: str
    world_setting: str
    model: str = "gemini-2.5-flash-preview-09-2025"

class AnalyzePlotRequest(BaseModel):
    settings: dict
    model: str = "gemini-2.5-flash-preview-09-2025"

class ImageGenRequest(BaseModel):
    prompt: str

@app.post("/analyze/consistency")
async def analyze_consistency(request: AnalyzeConsistencyRequest):
    try:
        report = await gemini_service.check_consistency(
            request.text, 
            request.char_sheet, 
            request.world_setting, 
            request.model
        )
        return {"report": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ReviewRequest(BaseModel):
    text: str
    criteria: str = "Consistency, Grammar, Creativity"
    model: str = "gemini-2.5-flash-preview-09-2025"

@app.post("/analyze/review_comprehensive")
async def analyze_review_comprehensive(request: ReviewRequest):
    try:
        # Force Gemini for Analysis/Review (DeepSeek is for Writing)
        target_model = request.model
        if "DeepSeek" in target_model:
            target_model = "gemini-2.0-pro-exp-02-05" # Fallback to high-intellect model
            
        review = await gemini_service.perform_comprehensive_review(request.text, request.criteria, target_model)
        return {"review": review}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze/generate_plan")
async def analyze_generate_plan(request: AnalyzePlotRequest):
    try:
        # Assuming settings has keys for generate_full_outline
        plan = await gemini_service.generate_full_outline(request.settings, model_name=request.model)
        return {"plan": plan}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class RewriteRequest(BaseModel):
    text: str
    critique: str
    char_sheet: str
    world_setting: str
    model: str = "gemini-2.0-pro-exp-02-05"

@app.post("/analyze/rewrite")
async def analyze_rewrite(request: RewriteRequest):
    try:
        rewritten = await gemini_service.rewrite_story_segment(
            request.text, 
            request.critique, 
            request.char_sheet, 
            request.world_setting, 
            request.model
        )
        return {"rewritten": rewritten}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class PredictionRequest(BaseModel):
    settings: dict
    outline: str
    model: str = "gemini-2.0-pro-exp-02-05"

@app.post("/analyze/prediction")
async def analyze_prediction(request: PredictionRequest):
    try:
        # Force Gemini for Analysis
        target_model = request.model
        if "DeepSeek" in target_model:
            target_model = "gemini-2.0-pro-exp-02-05"
            
        report = await gemini_service.evaluate_plot_potential(
            request.settings,
            request.outline,
            target_model
        )
        return {"report": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate/imagen3")
async def generate_imagen3(request: ImageGenRequest):
    try:
        result = await gemini_service.generate_image_imagen3(request.prompt)
        if "error" in result:
             raise HTTPException(status_code=500, detail=result["error"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ExportRequest(BaseModel):
    title: str
    author: str
    content: str
    cover_image_path: str = None # Optional local path if available
    export_type: str = "epub" # 'epub', 'txt_zip', 'epub_zip'
    publisher: str = None

@app.post("/export/download")
async def export_download(request: ExportRequest):
    try:
        buffer = None
        filename = "novel.epub"
        media_type = "application/epub+zip"
        
        if request.export_type == "epub":
            buffer = export_service.create_epub(request.title, request.author, request.content, request.cover_image_path, request.publisher)
            filename = f"{request.title}.epub"
        
        elif request.export_type == "txt":
            clean_text = export_service.get_clean_text(request.content)
            buffer = io.BytesIO(clean_text.encode('utf-8'))
            filename = f"{request.title}.txt"
            media_type = "text/plain"
            
        elif request.export_type == "txt_zip":
            # Split content first
            episodes = export_service.split_text_for_serialization(request.content)
            buffer = export_service.create_serial_zip(episodes, request.title, request.author, request.publisher, 'txt')
            filename = f"{request.title}_serial_txt.zip"
            media_type = "application/zip"
            
        elif request.export_type == "epub_zip":
            # Split content first
            episodes = export_service.split_text_for_serialization(request.content)
            buffer = export_service.create_serial_zip(episodes, request.title, request.author, request.publisher, 'epub')
            filename = f"{request.title}_serial_epub.zip"
            media_type = "application/zip"
            
        else:
            raise HTTPException(status_code=400, detail="Invalid export type")
            
        # Return as downloadable file
        return StreamingResponse(
            buffer, 
            media_type=media_type, 
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

class PackagingRequest(BaseModel):
    settings: dict
    outline: str
    model: str = "gemini-2.0-pro-exp-02-05"

@app.post("/generate/packaging")
async def generate_packaging(request: PackagingRequest):
    try:
        result = await gemini_service.generate_book_packaging(request.settings, request.outline, request.model)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------
# Batch Novel Generation System
# ---------------------------------------------------------
from backend.memory_manager import MemoryManager
import uuid
import asyncio

# Global Job Store (In-memory for demo; use Redis/DB for production)
jobs = {}

class BatchStartRequest(BaseModel):
    settings: dict
    target_vols: int = 2 # Default 2 volumes (50 chapters)
    model_writer: str = "DeepSeek-7B (Fine-tuned)"
    model_planner: str = "gemini-2.0-pro-exp-02-05"
    reference_outline: str = "" # Optional: Use existing outline from Planner Tab
    self_healing: bool = False # Optional: Enable iterative refinement
    model_config = {'protected_namespaces': ()}

async def run_batch_generation(job_id: str, settings: dict, target_vols: int, model_writer: str, model_planner: str, reference_outline: str = "", self_healing: bool = False):
    """
    Long-running background task to generate a full novel.
    1. Plan (Gemini)
    2. Loop N Chapters (DeepSeek + Memory + Gemini Review)
    """
    total_chapters = target_vols * 25
    
    jobs[job_id]["status"] = "planning"
    jobs[job_id]["log"] = []
    
    try:
        # Step 1: Planning
        jobs[job_id]["log"].append(f"Starting Global Planning for {total_chapters} chapters...")
        outline = await gemini_service.generate_full_outline(settings, total_chapters=total_chapters, model_name=model_planner, reference_outline=reference_outline)
        
        if "error" in outline:
            raise Exception(f"Planning failed: {outline['error']}")
            
        jobs[job_id]["outline"] = outline
        jobs[job_id]["total_chapters"] = len(outline.get("chapters", []))
        jobs[job_id]["results"] = []
        
        memory = MemoryManager()
        
        # Step 2: Writing Loop
        for i, chapter in enumerate(outline.get("chapters", [])):
            if jobs[job_id].get("cancel_requested"):
                jobs[job_id]["status"] = "cancelled"
                return

            chapter_num = chapter['chapter_num']
            jobs[job_id]["status"] = f"writing_chapter_{chapter_num}"
            jobs[job_id]["current_chapter"] = chapter_num
            jobs[job_id]["log"].append(f"Writing Chapter {chapter_num}: {chapter['title']}")
            
            # 2.1 Context Retrieval
            context = memory.get_recent_context()
            
            # 2.2 Writing
            humor_level = int(settings.get("humor_level", 0))
            humor_instruction = ""
            if humor_level >= 9:
                humor_instruction = "7. **Extreme Comedy**: Absurdist humor, chaotic situations, and laugh-out-loud slapstick."
            elif humor_level >= 7:
                humor_instruction = "7. **High-End Situational Comedy**: Sharp wit, perfect 'Tiki-Taka' banter, and strong situational irony. Characters should constantly bicker or misunderstand each other in funny ways."
            elif humor_level >= 4:
                humor_instruction = "7. **Light Comedy**: Use witty dialogue and occasional funny situations to keep the tone light."
            elif humor_level >= 1:
                humor_instruction = "7. **Subtle Wit**: Add a touch of humor or playfulness to the dialogue."

            prompt = f"""
            [Role]
            You are a world-class Romance Novelist (Best-seller level).
            Write Chapter {chapter_num}: {chapter['title']}

            [Style Guide]
            - **Tone/Style**: {settings.get('style', 'Romance')}
            - **Author Persona**: {settings.get('persona', 'Professional Storyteller')}

            [Context / Memory]
            {context}

            [Character Sheet]
            {settings.get('characters', 'N/A')}

            [World Setting]
            {settings.get('world', 'N/A')}

            [Core Story Idea]
            {settings.get('idea_premise', 'N/A')}

            [Chapter Summary]
            {chapter['summary']}

            [Key Events]
            {', '.join(chapter.get('key_events', []))}

            [High-Quality Writing Instructions]
            1. **Show, Don't Tell**: Do not label emotions (e.g., "he was sad"). Describe the physical manifestation (e.g., "his throat tightened," "he stared at the cold coffee").
            2. **Cinematic Depth**: Frame the scene like a movie. Use lighting, silence, and ambient sound to build tension.
            3. **Psychological Nuance**: Explore the character's internal contradictions. (e.g., He wants to hate her, but his eyes follow her).
            4. **Originality**: Avoid clichés. If the situation is typical, twist the reaction or outcome.
            5. **Pacing**: Slow down during key emotional realizations. Speed up action sequences.
            6. **Micro-expressions**: Describe subtle shifts in facial expressions and body language to convey emotion.
            {humor_instruction}

            [Output Requirement]
            - Language: **Natural, High-Quality Korean (Web-novel style)**.
            - Length: Sufficient to cover all key events with depth (approx. 4000-5000 characters).
            - Tone: Emotional, Immersive, Romantic.
            """
            
            # Extract Creativity (Temperature)
            temperature = settings.get('creativity', 0.7)

            if "DeepSeek" in model_writer:
                # Use local/cloud run DeepSeek
                if not romance_model.is_loaded: romance_model.load_model()
                chapter_text = await romance_model.generate_text(prompt, max_length=4000, temperature=temperature)
            else:
                # Fallback to Gemini
                chapter_text = await gemini_service.generate_story_content(prompt, model_name=model_writer, temperature=temperature)
            
            # 2.3 Review (Self-Correction / Quality Check)
            jobs[job_id]["log"].append(f"Reviewing Chapter {chapter_num}...")
            review = await gemini_service.perform_comprehensive_review(chapter_text)
            
            # [Self-Healing / Auto-Fix Logic]
            if self_healing:
                scores = review.get("scores", {})
                consistency = scores.get("consistency", 100)
                creativity = scores.get("creativity", 100)
                
                # Threshold: Score < 70 triggers rewrite
                if consistency < 70 or creativity < 70:
                    jobs[job_id]["log"].append(f"⚠️ Quality Alert (Consist: {consistency}, Creat: {creativity}). Rewriting Chapter {chapter_num} (Healing Mode)...")
                    
                    # Ask Gemini to fix it based on the critique
                    try:
                        chapter_text = await gemini_service.rewrite_improved_content(chapter_text, review)
                        # Optional: Re-review but for now just accept the fix to save tokens/time
                        jobs[job_id]["log"].append(f"✅ Self-Healing Completed.")
                    except Exception as he:
                        jobs[job_id]["log"].append(f"❌ Self-Healing Failed: {str(he)}")
            
            # 2.4 Update Memory
            
            # 2.4 Update Memory
            memory.add_chapter_memory(chapter_num, chapter['summary'], chapter.get('key_events', []), [])
            
            # Save Result
            jobs[job_id]["results"].append({
                "chapter_num": chapter_num,
                "title": chapter['title'],
                "text": chapter_text,
                "review": review
            })
            
            # Update Progress
            jobs[job_id]["progress"] = int(((i + 1) / jobs[job_id]["total_chapters"]) * 100)
            
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["log"].append("Novel Generation Completed!")
        
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["log"].append(f"Error: {str(e)}")
        print(f"Job {job_id} failed: {e}")

@app.post("/generate/batch_start")
async def start_batch_generation(request: BatchStartRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "results": [],
        "created_at": str(os.getenv("Time", ""))
    }
    background_tasks.add_task(run_batch_generation, job_id, request.settings, request.target_vols, request.model_writer, request.model_planner, request.reference_outline, request.self_healing)
    return {"job_id": job_id, "message": "Batch generation started"}

@app.get("/generate/batch_status/{job_id}")
async def get_batch_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]

@app.post("/generate/batch_cancel/{job_id}")
async def cancel_batch_generation(job_id: str):
    if job_id in jobs:
        jobs[job_id]["cancel_requested"] = True
        return {"message": "Cancellation requested"}
    raise HTTPException(status_code=404, detail="Job not found")

# Existing Endpoints...
from backend.utils import process_epub_from_url

@app.post("/analyze/novel")
async def analyze_novel(request: AnalyzeNovelRequest):
    """
    Endpoint for external systems (Flutter Admin) to get keyword metadata.
    Accepts 'text' OR 'file_url'.
    """
    try:
        target_text = request.text
        
        if not target_text and request.file_url:
            # Download and parse
            target_text = process_epub_from_url(request.file_url)
            
        if not target_text:
             raise HTTPException(status_code=400, detail="Either 'text' or 'file_url' must be provided.")

        result = await gemini_service.analyze_novel_content(target_text)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze/cover_prompt")
async def analyze_cover_prompt(request: AnalyzeRequest):
    try:
        prompt = await gemini_service.generate_cover_prompt(request.text, request.model)
        return {"cover_prompt": prompt}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class IdeaRequest(BaseModel):
    genre: str = "Random"
    spice_level: str = "19금(없음)"
    model: str = "gemini-2.5-flash-preview-09-2025"
    apply_trends: bool = True
    moods: list[str] = []
    male_tags: list[str] = []
    female_tags: list[str] = []
    arc: str = ""
    char_sheet: str = ""
    world_setting: str = ""

class AnalyzePlotRequest(BaseModel):
    settings: dict
    model: str = "gemini-2.5-flash-preview-09-2025"

@app.post("/analyze/plot")
async def analyze_plot(request: AnalyzePlotRequest):
    try:
        plot = await gemini_service.generate_plot(request.settings, request.model)
        return {"plot": plot}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ImprovePlotRequest(BaseModel):
    settings: dict
    outline: str
    advice: str
    model: str = "gemini-2.0-pro-exp-02-05"

@app.post("/analyze/improve_plot")
async def improve_plot(request: ImprovePlotRequest):
    try:
        new_plot = await gemini_service.auto_improve_plot(
            request.settings, 
            request.outline, 
            request.advice, 
            request.model
        )
        return {"plot": new_plot}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate/idea")
async def generate_idea(request: IdeaRequest = None):
    # Handle case where request might be empty
    if not request:
        request = IdeaRequest()
        
    try:
        idea = await gemini_service.generate_story_idea(
            genre=request.genre, 
            spice_level=request.spice_level, 
            model_name=request.model, 
            apply_trends=request.apply_trends,
            moods=request.moods,
            male_tags=request.male_tags,
            female_tags=request.female_tags,
            arc=request.arc,
            char_sheet=request.char_sheet,
            world_setting=request.world_setting
        )
        return {"idea": idea}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate/cover_image")
async def generate_cover_image(request: ImageGenRequest):
    try:
        result = await gemini_service.generate_cover_image(request.prompt)
        if "error" in result:
             raise HTTPException(status_code=500, detail=result["error"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze/summarize")
async def analyze_summarize(request: AnalyzeRequest):
    try:
        summary = await gemini_service.summarize_context(request.text, request.model)
        return {"summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class AnalyzeReviewRequest(BaseModel):
    text: str
    model: str = "gemini-2.0-pro-exp-02-05"

@app.post("/analyze/review")
async def analyze_review_comprehensive(request: AnalyzeReviewRequest):
    try:
        # Returns JSON string
        result = await gemini_service.perform_comprehensive_review(request.text, model_name=request.model)
        import json
        return json.loads(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class RewriteRequest(BaseModel):
    text: str
    critique: dict
    model: str = "gemini-2.0-pro-exp-02-05"

@app.post("/generate/rewrite")
async def generate_rewrite(request: RewriteRequest):
    try:
        rewritten_text = await gemini_service.rewrite_improved_content(request.text, request.critique, model_name=request.model)
        return {"rewritten_text": rewritten_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
