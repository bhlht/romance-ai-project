from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv

# Import local modules
from backend.model import romance_model
from backend.gemini_service import gemini_service

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
    # Load model on startup
    print("Initializing Romance Model...")
    romance_model.load_model()
    yield
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
        # Use Gemini Service for main generation to support Model Selection & Context
        # This overrides the local model for now, which gives better immediate results with the new features.
        # If user wants local model, they can select it if we add it to options, 
        # but for now we map all generation to Gemini for the "Advanced features".
        
        # We need a new method in gemini_service for story generation
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

@app.post("/generate/idea")
async def generate_idea(request: IdeaRequest = None):
    # Handle case where request might be empty
    if not request:
        request = IdeaRequest()
        
    try:
        idea = await gemini_service.generate_story_idea(request.genre, request.spice_level, request.model)
        return {"idea": idea}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ImageGenRequest(BaseModel):
    prompt: str

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
