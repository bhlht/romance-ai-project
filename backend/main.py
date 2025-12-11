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
    max_length: int = 500
    temperature: float = 0.7

class AnalyzeRequest(BaseModel):
    text: str

class AnalyzeNovelRequest(BaseModel):
    text: str = None
    file_url: str = None

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
        generated_text = await romance_model.generate_text(
            prompt=request.prompt,
            max_length=request.max_length,
            temperature=request.temperature
        )
        return {"generated_text": generated_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze/feedback")
async def analyze_feedback(request: AnalyzeRequest):
    try:
        critique = await gemini_service.analyze_text(request.text)
        return {"critique": critique}
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
        prompt = await gemini_service.generate_cover_prompt(request.text)
        return {"cover_prompt": prompt}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate/idea")
async def generate_idea():
    try:
        idea = await gemini_service.generate_story_idea()
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
