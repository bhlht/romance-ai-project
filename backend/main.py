import json

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager
from typing import Optional, List
import os
from dotenv import load_dotenv

# Import local modules
from backend.db_service import db_service
from backend.gemini_service import gemini_service
from backend.export_service import export_service
from backend.import_service import import_service
from fastapi.responses import StreamingResponse
import io
import time
import threading

load_dotenv()

class GenerateRequest(BaseModel):
    prompt: str
    max_length: int = 1500
    temperature: float = 0.7
    model: str = "DeepSeek-7B (Fine-tuned)"
    # Structured Story Bible fields
    chars: str = None
    world: str = None
    plot_summary: str = None
    ch_focus: str = None
    writer_memo: str = None
    context: str = None
    previous_chapter_context: Optional[str] = None
    style: str = "기본"         # 문체 프리셋
    persona: str = ""           # 유명 작가/작품 모방 페르소나
    humor_level: int = 0        # 유머 레벨
    # [장기 기억] 이전 화 요약 체인
    memory_chain: list = []   # [{"chapter": 1, "summary": "..."}, ...]
    chapter_num: int = 1      # 현재 집필 화수
    
    # RAG parameters
    rag_enabled: bool = True
    rag_category_id: Optional[int] = None
    rag_series_id: Optional[int] = None
    rag_keyword: Optional[str] = None
    apply_trends: bool = True
    style_guide: str = ""

class SummarizeRequest(BaseModel):
    text: str                  # 방금 생성된 소설 본문
    chapter_num: int = 1
    chars: str = ""
    model: str = "models/gemini-3-flash-preview"

class PolishRequest(BaseModel):
    paragraph: Optional[str] = None
    text: Optional[str] = None
    model: str = "models/gemini-2.5-flash"
    rag_enabled: bool = True
    rag_category_id: Optional[int] = None
    rag_series_id: Optional[int] = None
    rag_keyword: Optional[str] = None

class AnalyzeRequest(BaseModel):
    text: str
    model: str = "models/gemini-3-flash-preview"

class AnalyzeNovelRequest(BaseModel):
    text: str = None
    file_url: str = None
    model: str = "models/gemini-3-flash-preview"

class NextChoicesRequest(BaseModel):
    story: str
    chapter_focus: str
    chars: str
    rel_map: str
    model: str = "models/gemini-3-flash-preview"

# --- Global Activity Tracking ---
IDLE_TIMEOUT_MIN = 30 # Increased to 30 mins for safety
server_start_time = time.time()
last_activity_time = server_start_time

def update_activity():
    global last_activity_time
    last_activity_time = time.time()

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Server Started. Initializing PostgreSQL pool...")
    await db_service.initialize()
    yield

app = FastAPI(title="Romance AI API", lifespan=lifespan)

# Add CORS Middleware to allow requests from any origin (e.g., Localhost Frontend, Mobile App)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_activity_update(request, call_next):
    # Update activity for every request except /ping or /system/status to avoid self-extension
    if request.url.path not in ["/ping", "/system/status", "/"]:
        update_activity()
    response = await call_next(request)
    return response

@app.get("/")
def read_root():
    return {"status": "running", "db_connected": db_service.pool is not None}

@app.get("/ping")
def ping():
    """Simple heartbeat endpoint to keep the server awake."""
    update_activity() # Manual extension
    return {"status": "alive", "db_connected": db_service.pool is not None}

@app.get("/system/status")
def system_status():
    """Returns the remaining idle time in seconds."""
    elapsed = time.time() - last_activity_time
    remaining = max(0, (IDLE_TIMEOUT_MIN * 60) - elapsed)
    return {
        "status": "active" if remaining > 0 else "idle",
        "remaining_sec": remaining,
        "db_connected": db_service.pool is not None,
        "last_activity": last_activity_time,
        "server_start_time": server_start_time,
        "server_time": time.time()
    }

@app.get("/rag/categories")
async def get_rag_categories():
    try:
        categories = await db_service.get_categories()
        return {"categories": categories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/rag/series")
async def get_rag_series(category_id: int = None, series_id: int = None, search_query: str = None):
    try:
        series = await db_service.get_series(
            category_id=category_id,
            series_id=series_id,
            search_query=search_query
        )
        return {"series": series}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate/romance")
async def generate_romance(request: GenerateRequest):
    try:
        # 창작 엔드포인트는 항상 파인튜닝된 DeepSeek LoRA 모델을 사용합니다.
        # (V3: 초기 초안은 제미나이가 작성하므로 로컬 모델 로딩을 기다릴 필요가 없습니다.)
        print("Generating Romance Story Draft (Gemini-First)...")
        
        # ========================================================================
        # [상용화 고도화] 완전한 스토리 바이블 주입 시스템
        # ========================================================================
        
        # Step 1: 훈련 시 사용된 정확한 Native Trigger 사용
        # 이 문장은 87만 번 반복 학습된 모델의 핵심 활성화 키입니다.
        native_instruction = "독창적인 비유와 상징을 사용하여 문학적 완성도가 높은 글을 완성해줘."
        
        # Step 2: 본문 컨텍스트 및 이전 화 본문 정제
        raw_context = request.context if request.context else ""
        cleaned_story = raw_context.strip()
        
        raw_prev_context = request.previous_chapter_context if request.previous_chapter_context else ""
        cleaned_prev_context = raw_prev_context.strip()
        
        # 직전 흐름 및 시공간 추적 조립 (Flow Context)
        flow_context = ""
        if cleaned_prev_context:
            flow_context += f"--- [직전 화(제{request.chapter_num-1}화)의 마지막 장면] ---\n{cleaned_prev_context[-2500:]}\n\n"
        if cleaned_story:
            flow_context += f"--- [현재 화(제{request.chapter_num}화)의 작성된 앞 부분] ---\n{cleaned_story}\n\n"
        else:
            flow_context += f"--- [현재 화(제{request.chapter_num}화)를 새로 시작해야 함] ---\n[안내] 직전 화의 마무리에 바로 이어서 자연스러운 전환(Bridge)을 만들며 제{request.chapter_num}화의 첫 장면을 시작하십시오.\n"

        # Step 3: [핵심] 스토리 바이블 브리핑 생성
        # ### Response: 블록 안에 삽입하여 모델이 "소설에 등장하는 설정 정보"로 인식하게 합니다.
        bible_lines = []
        if request.chars:
            bible_lines.append(f"[인물: {request.chars}]")
        if request.world:
            bible_lines.append(f"[배경: {request.world}]")
        if request.chapter_num:
            bible_lines.append(f"[현재 화수: 제{request.chapter_num}화]")
        if request.ch_focus and request.ch_focus not in ("N/A", "아웃라인 정보를 찾을 수 없습니다.", ""):
            bible_lines.append(f"[이번 화 목표: {request.ch_focus}]")
        elif request.plot_summary:
            bible_lines.append(f"[줄거리 요약: {request.plot_summary}]")
        if request.writer_memo and request.writer_memo not in ("N/A", ""):
            bible_lines.append(f"[작가 지시: {request.writer_memo}]")
        
        # [장기 기억] 이전 화 요약 체인 주입
        # 최근 15개 요약만 포함 (토큰 예산 절약)
        if request.memory_chain:
            recent_memories = request.memory_chain[-15:]
            memory_text = "\n".join(
                f"  - 제{m.get('chapter', '?')}화: {m.get('summary', '')}"
                for m in recent_memories
            )
            bible_lines.append(f"[이전 화 요약]\n{memory_text}")
            print(f"📚 장기 기억 주입: {len(recent_memories)}개 화 요약 포함")
        
        bible_brief = "\n".join(bible_lines)
        
        # [추가] 프론트엔드의 스타일/유머/페르소나 반영
        style_prompt_str = f"문체: {request.style}"
        if request.persona:
            style_prompt_str += f", 페르소나: {request.persona}"
        if request.humor_level > 0:
            humor_instruction = ""
            if request.humor_level >= 9:
                humor_instruction = " (극강의 코미디: 아방궁 같은 상황, 황당무계한 전개, 배꼽 잡는 슬랩스틱 유머를 적극적으로 활용하여 소설 중간중간에 반드시 코믹하고 웃긴 장면을 연출하십시오.)"
            elif request.humor_level >= 7:
                humor_instruction = " (고품격 상황 코미디: 날카로운 재치, 완벽한 '티키타카' 대사, 강렬한 상황적 아이러니를 활용하십시오. 캐릭터들이 끊임없이 서로 오해하거나 유머러스하게 투닥거리게 하여 확실하게 유쾌하고 웃긴 분위기를 만드십시오.)"
            elif request.humor_level >= 4:
                humor_instruction = " (경쾌한 코미디: 재치 있는 대사와 가끔씩 터지는 코믹한 상황을 통해 극의 분위기를 가볍고 즐겁게 유지하십시오.)"
            else:
                humor_instruction = " (은은한 유머: 대사에 미소를 자아내는 재치나 장난스러움을 한 스푼 더하십시오.)"
            
            style_prompt_str += f", 유머 감각(레벨 {request.humor_level}/10) 적용{humor_instruction}"
            
        if request.style_guide:
            style_prompt_str += (
                f"\n- [스타일 가이드 지침 강제 적용]\n"
                f"다음 지침을 소설 전개와 문체 및 서술 템포에 절대적으로 강제 적용하십시오:\n{request.style_guide}"
            )
            
        # =====================================================================
        # Step 4: [V3 RAG 아키텍처] 기획자(Gemini) - RAG 보강 후 2000자 초안 작성 및 <STYLE> 태그 삽입
        # =====================================================================
        print("🧠 [Writer's Room V3] 기획자(Gemini)가 2000자 초안을 작성합니다...")
        
        # PostgreSQL RAG 조회
        if request.rag_enabled or (request.model and "RAG" in request.model):
            rag_context = await db_service.get_rag_context(
                project_name="Romance Novel",
                query_text=request.prompt or request.ch_focus or "",
                category_id=request.rag_category_id,
                series_id=request.rag_series_id,
                keyword=request.rag_keyword
            )
        else:
            rag_context = "[RAG 참조 비활성화됨]"
        
        # RAG 검색 결과를 시공간 텍스트 컨텍스트 뒤에 덧붙여 Gemini에 주입
        rag_extended_context = f"{flow_context}\n\n[참고 데이터 (RAG 검색 결과)]\n{rag_context}"
        
        draft_text = ""
        if request.chars:
            draft_text = await gemini_service.generate_v3_draft(
                prompt=request.prompt,
                chars=request.chars,
                world=request.world or "현대 로맨스",
                plot_summary=request.plot_summary or "내용 전개",
                ch_focus=request.ch_focus or "감정선 전개",
                style_directions=style_prompt_str, # UI 설정 파라미터 전달
                previous_context=rag_extended_context, # 합성된 시공간 맥락 및 RAG 참조 전달
                model_name=request.model,
                temperature=request.temperature
            )
        
        if not draft_text:
            return {"generated_text": "[Error: Gemini 초안 작성에 실패했습니다.]"}

        print(f"✅ 초안 작성 완료 (길이: {len(draft_text)}자)")

        print("✨ Gemini 초안 반환 (수동 교정 모드 대기)")
        return {"generated_text": draft_text.strip()}

    except HTTPException as he:
        raise he
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate/polish")
async def generate_polish(request: PolishRequest):
    """
    [V3 아키텍처] 특정 문단을 Gemini와 RAG 컨텍스트를 사용해 3가지 변종 생성
    """
    try:
        target_text = request.paragraph or request.text
        if not target_text:
            raise HTTPException(status_code=400, detail="Missing paragraph or text")
            
        print(f"💎 [Polish Mode] 문단 교정 시작 (RAG={request.rag_enabled}): {target_text[:30]}...")
        
        # PostgreSQL RAG 조회
        if request.rag_enabled:
            rag_context = await db_service.get_rag_context(
                project_name="Romance Novel Polish",
                query_text=target_text,
                category_id=request.rag_category_id,
                series_id=request.rag_series_id,
                keyword=request.rag_keyword,
                limit=3  # 문단 윤색은 문맥 참조용이므로 최대 3개 정도로 한정
            )
        else:
            rag_context = None

        options = await gemini_service.generate_polish_options(
            paragraph=target_text,
            model_name=request.model,
            rag_context=rag_context
        )
        return {"options": options}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/summarize")
async def summarize_scene(request: SummarizeRequest):
    """
    [장기 기억 시스템] 방금 생성된 장면에서 초정밀 요약(chunk_summary), 인물/설정 변동사항(entity_changes), 
    그리고 다음 화로 이어지는 미끼(cliffhanger_point) 정보를 추출합니다.
    """
    try:
        prompt = f"""
당신은 베스트셀러 소설 전문 교열가이자 기획자입니다. 다음 소설 장면을 정밀하게 분석하여 장기 기억 스토리지용 설정 변경 메타데이터를 추출하십시오.

[분석할 본문 (제{request.chapter_num}화)]
{request.text}

[요구사항]
1. **chunk_summary**: 1화의 핵심 플롯에 대한 3~5줄 분량의 상세 요약.
2. **entity_changes**:
   - **characters**: 해당 화에서 발생한 주요 인물들의 감정 상태 변화, 관계 전진 및 갈등 상태 변화.
   - **settings**: 이번 화에서 새롭게 이동한 공간 배경, 혹은 새로 정립되거나 발견된 아이템/설정 규칙.
3. **cliffhanger_point**: 본문의 마지막에서 다음 화로 자연스럽게 독자의 흥미를 유발하며 이어지는 핵심 미끼/연결고리 정보.

반드시 아래 JSON 형식으로만 응답하십시오. (No meta-commentary, 오직 한국어로 작성)
{{
  "chunk_summary": "3~5줄 상세 플롯 요약...",
  "entity_changes": {{
    "characters": "주요 인물 감정 상태, 관계 변화...",
    "settings": "새로운 아이템, 물리적 공간의 설정 변화..."
  }},
  "cliffhanger_point": "다음 화로 넘어가는 연결고리 정보..."
}}
"""
        
        raw_res = await gemini_service._call_gem_with_retry(prompt, request.model)
        cleaned = raw_res.replace("```json", "").replace("```", "").strip()
        import json
        metadata = json.loads(cleaned)
        return {
            "chunk_summary": metadata.get("chunk_summary", ""),
            "entity_changes": metadata.get("entity_changes", {"characters": "", "settings": ""}),
            "cliffhanger_point": metadata.get("cliffhanger_point", ""),
            "chapter": request.chapter_num
        }
    except Exception as e:
        # Fallback metadata structure in case of parsing exception
        return {
            "chunk_summary": "요약본 생성 중 파싱 오류가 발생했습니다.",
            "entity_changes": {"characters": "인물 상태 변동 정보 없음", "settings": "설정 변동 정보 없음"},
            "cliffhanger_point": "연결 정보 없음",
            "chapter": request.chapter_num
        }

class RewriteRequest(BaseModel):
    text: str
    critique: dict
    model: str = "models/gemini-3.1-pro-preview"
    chars: str = "기본 인물"
    world: str = "기본 세계관"
    style_guide: Optional[str] = ""
    rag_enabled: bool = False
    rag_category_id: Optional[int] = None
    rag_series_id: Optional[int] = None
    rag_keyword: Optional[str] = ""

@app.post("/generate/rewrite")
async def rewrite_chapter(request: RewriteRequest):
    try:
        # Retrieve RAG context if enabled
        rag_context = ""
        if request.rag_enabled:
            try:
                rag_context = db_service.get_rag_context(
                    query_text=request.text,
                    category_id=request.rag_category_id,
                    series_id=request.rag_series_id,
                    keyword=request.rag_keyword,
                    limit=3
                )
            except Exception as db_err:
                print(f"RAG search failed in rewrite: {db_err}")

        # Auto-Fix uses Gemini because it requires instruction following and editing capabilities
        rewritten_text = await gemini_service.rewrite_story_segment(
            text=request.text,
            critique=json.dumps(request.critique, ensure_ascii=False),
            char_sheet=request.chars,
            world_setting=request.world,
            model_name=request.model,
            style_guide=request.style_guide,
            rag_context=rag_context
        )
        return {"rewritten_text": rewritten_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Redundant class definition and polish endpoint removed to consolidate format.
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze/next_choices")
async def analyze_next_choices(request: NextChoicesRequest):
    try:
        choices = await gemini_service.generate_next_scene_choices(
            story_context=request.story,
            chapter_focus=request.chapter_focus,
            chars=request.chars,
            rel_map=request.rel_map,
            model_name=request.model
        )
        return {"choices": choices}
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
    model: str = "models/gemini-3-flash-preview"

class AnalyzePlotRequest(BaseModel):
    settings: dict
    model: str = "models/gemini-3-flash-preview"

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

class ResolveSettingsRequest(BaseModel):
    char_sheet: str
    world_setting: str
    plot_errors: list
    model: str = "models/gemini-3-flash-preview"

class ResolveStoryRequest(BaseModel):
    text: str
    char_sheet: str
    world_setting: str
    plot_errors: list
    style_guide: str
    rag_context: Optional[str] = ""
    model: str = "models/gemini-3.1-pro-preview"

@app.post("/analyze/consistency/resolve-setting")
async def resolve_consistency_setting(request: ResolveSettingsRequest):
    try:
        proposed = await gemini_service.resolve_consistency_via_settings(
            request.char_sheet,
            request.world_setting,
            request.plot_errors,
            request.model
        )
        return proposed
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze/consistency/resolve-story")
async def resolve_consistency_story(request: ResolveStoryRequest):
    try:
        revised_text = await gemini_service.resolve_consistency_via_story(
            request.text,
            request.char_sheet,
            request.world_setting,
            request.plot_errors,
            request.style_guide,
            request.rag_context,
            request.model
        )
        return {"revised_text": revised_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class SyncOutlineRequest(BaseModel):
    char_sheet: str
    world_setting: str
    blurb: str
    plot_outline: str
    model: str = "models/gemini-3.1-pro-preview"

@app.post("/analyze/consistency/sync-outline")
async def sync_outline_endpoint(request: SyncOutlineRequest):
    try:
        synced = await gemini_service.sync_outline_with_settings(
            request.char_sheet,
            request.world_setting,
            request.blurb,
            request.plot_outline,
            request.model
        )
        return synced
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ReviewRequest(BaseModel):
    text: Optional[str] = None
    memory_chain: Optional[list] = []  # List of precision summaries and entity updates
    criteria: str = "Consistency, Grammar, Creativity"
    model: str = "models/gemini-3-flash-preview"

@app.post("/analyze/review_comprehensive")
async def analyze_review_comprehensive(request: ReviewRequest):
    try:
        target_model = request.model
        if "DeepSeek" in target_model:
            target_model = "models/gemini-3.1-pro-preview"

        if request.memory_chain:
            # Map-Reduce mode: Perform aggregate evaluation of all chapter summaries
            map_prompt = f"""
당신은 대한민국 최고의 웹소설 기획자이자 비평가입니다. 다음 축적된 [매화별 초정밀 요약 및 캐릭터/세계관 설정 변동사항]을 기반으로 작품 전체의 장기적 일관성, 개연성, 상업성 및 전개 템포를 심층 비평하십시오.

[스토리 메타데이터 피드]
{json.dumps(request.memory_chain, ensure_ascii=False, indent=2)}

[검토 기준]
- 캐릭터 감정선의 누적 및 개연성 (Characters arc consistency)
- 시공간/규칙의 일관성 (World setting consistency)
- 상업적 텐션 및 호흡 (Pacing and commercial potential)

반드시 아래 JSON 형식으로만 응답하십시오. (No meta-commentary, 오직 한국어로 작성)
{{
    "scores": {{
        "consistency": <점수 1-100>,
        "grammar_flow": <점수 1-100>,
        "creativity": <점수 1-100>
    }},
    "feedback": {{
        "consistency": "캐릭터 아크 및 사건 인과관계에 대한 한국어 정밀 비평...",
        "grammar_flow": "스토리 전개 호흡 및 속도감에 대한 한국어 정밀 비평...",
        "creativity": "소재의 독창성 및 텐션 유지를 위한 제안..."
    }},
    "overall_critique": "작품 전체의 전반적인 완성도에 대한 요약 평.",
    "improvement_suggestions": ["개선 제안 1", "개선 제안 2"],
    "recommended_chapters": [
        {{"chapter": 3, "reason": "구체적으로 왜 이 화차의 수정이 필요한지 이유 설명"}}
    ]
}}
"""
            raw_text = await gemini_service._call_gem_with_retry(map_prompt, target_model)
            cleaned = raw_text.replace("```json", "").replace("```", "").strip()
            import json as json_mod
            return {"review": json_mod.loads(cleaned)}
        else:
            # Standard single segment mode
            review = await gemini_service.perform_comprehensive_review(request.text or "", request.criteria, target_model)
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

class AnalyzeRewriteRequest(BaseModel):
    text: str
    critique: str
    char_sheet: str
    world_setting: str
    model: str = "models/gemini-3.1-pro-preview"
    style_guide: Optional[str] = ""
    rag_enabled: bool = False
    rag_category_id: Optional[int] = None
    rag_series_id: Optional[int] = None
    rag_keyword: Optional[str] = ""

@app.post("/analyze/rewrite")
async def analyze_rewrite(request: AnalyzeRewriteRequest):
    try:
        # Retrieve RAG context if enabled
        rag_context = ""
        if request.rag_enabled:
            try:
                rag_context = db_service.get_rag_context(
                    query_text=request.text,
                    category_id=request.rag_category_id,
                    series_id=request.rag_series_id,
                    keyword=request.rag_keyword,
                    limit=3
                )
            except Exception as db_err:
                print(f"RAG search failed in rewrite: {db_err}")

        rewritten = await gemini_service.rewrite_story_segment(
            text=request.text, 
            critique=json.dumps(request.critique, ensure_ascii=False) if isinstance(request.critique, dict) else str(request.critique), 
            char_sheet=request.char_sheet, 
            world_setting=request.world_setting, 
            model_name=request.model,
            style_guide=request.style_guide,
            rag_context=rag_context
        )
        return {"rewritten": rewritten}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class PredictionRequest(BaseModel):
    settings: dict
    outline: str
    model: str = "models/gemini-3.1-pro-preview"

@app.post("/analyze/prediction")
async def analyze_prediction(request: PredictionRequest):
    try:
        # Force Gemini for Analysis
        target_model = request.model
        if "DeepSeek" in target_model:
            target_model = "models/gemini-3.1-pro-preview"
            
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
        result = await gemini_service.generate_cover_image(request.prompt)
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
            buffer = export_service.create_serial_zip(episodes, request.title, request.author, request.publisher, 'epub', request.cover_image_path)
            filename = f"{request.title}_serial_epub.zip"
            media_type = "application/zip"
            
        else:
            raise HTTPException(status_code=400, detail="Invalid export type")
            
        # Return as downloadable file
        from urllib.parse import quote
        encoded_filename = quote(filename)
        return StreamingResponse(
            buffer, 
            media_type=media_type, 
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
        )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

class PackagingRequest(BaseModel):
    settings: dict
    outline: str
    model: str = "models/gemini-3.1-pro-preview"

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
    model_planner: str = "models/gemini-3.1-pro-preview"
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
                humor_instruction = "7. **극강의 코미디**: 아방궁 같은 상황, 황당무계한 전개, 배꼽 잡는 슬랩스틱 유머를 적극적으로 활용하십시오."
            elif humor_level >= 7:
                humor_instruction = "7. **고품격 상황 코미디**: 날카로운 재치, 완벽한 '티키타카' 대사, 강렬한 상황적 아이러니를 활용하십시오. 캐릭터들이 끊임없이 서로 오해하거나 유머러스하게 투닥거려야 합니다."
            elif humor_level >= 4:
                humor_instruction = "7. **경쾌한 코미디**: 재치 있는 대사와 가끔씩 터지는 코믹한 상황을 통해 극의 분위기를 가볍고 즐겁게 유지하십시오."
            elif humor_level >= 1:
                humor_instruction = "7. **은은한 유머**: 대사에 미소를 자아내는 재치나 장난스러움을 한 스푼 더하십시오."

            style_guide_text = settings.get("style_guide", "")
            trend_instruction = ""
            if style_guide_text:
                # Indent lines of style_guide for clean prompt formatting
                indented_guide = "\n   ".join(style_guide_text.split("\n"))
                trend_instruction = (
                    f"8. **스타일 가이드 지침 강제 적용**:\n"
                    f"   소설 전개와 문체 및 서술 템포에 다음 지침을 절대적으로 강제 적용하십시오:\n"
                    f"   {indented_guide}"
                )

            prompt = f"""
            당신은 대한민국 최고의 베스트셀러 로맨스 소설 작가입니다. 
            제 {chapter_num}화: '{chapter['title']}'를 집필해 주세요.

            [문체 및 페르소나]
            - **분위기/스타일**: {settings.get('style', '로맨틱')}
            - **작가 페르소나**: {settings.get('persona', '전문 소설가')}

            [이전 줄거리 및 기억]
            {context}

            [등장인물 설정]
            {settings.get('characters', 'N/A')}

            [세계관 배경]
            {settings.get('world', 'N/A')}

            [핵심 스토리 아이디어]
            {settings.get('idea_premise', 'N/A')}

            [이번 회차 줄거리 요약]
            {chapter['summary']}

            [필수 포함 사건]
            {', '.join(chapter.get('key_events', []))}

            [집필 가이드라인 (최고의 퀄리티를 위해)]
            1. **묘사 강화 (Show, Don't Tell)**: 감정의 이름을 직접 언급하지 마십시오(예: "그는 슬펐다"). 대신 신체적 징후나 행동으로 묘사하십시오(예: "목구멍이 꽉 막혀왔다", "그는 식어버린 커피만 멍하니 바라보았다").
            2. **시네마틱한 깊이**: 영화의 한 장면처럼 구성하십시오. 조명, 정적, 주변의 소리를 활용하여 긴장감을 조성하십시오.
            3. **심리적 세밀함**: 캐릭터의 내면적 모순을 탐구하십시오. (예: 그녀를 미워하고 싶지만, 눈길은 자꾸 그녀를 쫓는다).
            4. **독창성**: 클리셰를 피하십시오. 상황이 전형적이라도 반응이나 결과만큼은 의외성을 주십시오.
            5. **호흡 조절(Pacing)**: 감정이 고조되는 순간에는 호흡을 늦추고, 액션이나 급박한 상황에서는 속도를 높이십시오.
            6. **미세 묘사**: 표정의 미묘한 변화나 몸짓을 통해 캐릭터의 감정을 섬세하게 전달하십시오.
            {humor_instruction}
            {trend_instruction}

            [출력 요구사항]
            - 언어: **자연스럽고 품격 있는 한국어 (웹소설 스타일)**. 영어는 절대 사용하지 마십시오.
            - 분량: 모든 핵심 사건을 깊이 있게 다룰 수 있는 충분한 분량 (약 4000~5000자 권장).
            - 어조: 감성적이고 몰입감 넘치는 로맨틱한 분위기. (Output ONLY in Korean)
            """
            
            # Extract Creativity (Temperature)
            temperature = settings.get('creativity', 0.7)

            # [하드코딩] 한꺼번에 창작하기(Batch Generation) 시에도 
            # 무조건 파인튜닝된 커스텀 LoRA (DeepSeek) 모델을 강제로 사용하도록 덮어씌웁니다.
            model_writer = "DeepSeek-7B (Fine-tuned)"

            # RAG Context Retrieval for current chapter summary
            if settings.get("rag_enabled", True) or "RAG" in settings.get("model", "") or "RAG" in model_planner or "RAG" in model_writer:
                rag_context = await db_service.get_rag_context(
                    project_name="Romance Novel",
                    query_text=chapter['summary'],
                    category_id=settings.get("rag_category_id"),
                    series_id=settings.get("rag_series_id"),
                    keyword=settings.get("rag_keyword")
                )
            else:
                rag_context = "[RAG 참조 비활성화됨]"
            
            prompt_with_rag = f"{prompt}\n\n[참고 설정 (RAG 검색 결과)]\n{rag_context}"
            
            jobs[job_id]["log"].append(f"Generating Chapter {chapter_num} via Gemini (RAG enabled)...")
            chapter_text = await gemini_service.generate_story_content(
                prompt_with_rag, 
                model_name=model_planner, 
                temperature=temperature
            )
            
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
    model: str = "models/gemini-3-flash-preview"
    apply_trends: bool = True
    moods: list[str] = []
    male_tags: list[str] = []
    female_tags: list[str] = []
    arc: str = ""
    char_sheet: str = ""
    world_setting: str = ""

class AnalyzePlotRequest(BaseModel):
    settings: dict
    model: str = "models/gemini-3-flash-preview"

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
    model: str = "models/gemini-3.1-pro-preview"

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
    model: str = "models/gemini-3.1-pro-preview"

@app.post("/analyze/review")
async def analyze_review_comprehensive(request: AnalyzeReviewRequest):
    try:
        # Returns dictionary
        result = await gemini_service.perform_comprehensive_review(request.text, model_name=request.model)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class RewriteRequest(BaseModel):
    text: str
    critique: dict
    model: str = "models/gemini-3.1-pro-preview"

@app.post("/generate/rewrite")
async def generate_rewrite(request: RewriteRequest):
    try:
        rewritten_text = await gemini_service.rewrite_improved_content(request.text, request.critique, model_name=request.model)
        return {"rewritten_text": rewritten_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class NextPromptRequest(BaseModel):
    chapter_num: int
    chapter_outline: str
    recent_memory: str

@app.post("/generate/next_prompts")
async def generate_next_prompts(request: NextPromptRequest):
    try:
        from backend.gemini_service import gemini_service
        options = await gemini_service.generate_next_prompts(
            chapter_num=request.chapter_num,
            chapter_outline=request.chapter_outline,
            recent_memory=request.recent_memory
        )
        return {"options": options}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# PUBLISHER HUB ROUTES
# ==========================================

class SplitRequest(BaseModel):
    text: str
    mode: str = "chapter"  # "chapter" or "token"
    value: int = 10

class ExportSplitRequest(BaseModel):
    episodes: List[str]
    title: str = "작품"
    author: str = "작가"
    format_type: str = "txt"  # "txt" or "epub"

class SpellCheckRequest(BaseModel):
    text: str
    model: str = "models/gemini-2.5-flash"

@app.post("/publisher/check-spell")
async def publisher_check_spell(request: SpellCheckRequest):
    """원고 맞춤법 및 오탈자 검사"""
    try:
        report = await gemini_service.check_spell(request.text, request.model)
        return {"report": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/publisher/upload")
async def publisher_upload(file: UploadFile = File(...)):
    """파일 업로드 → 텍스트 추출 (TXT/EPUB 지원)"""
    try:
        file_bytes = await file.read()
        filename = file.filename or "unknown.txt"
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"

        if ext == "epub":
            text = import_service.parse_epub(file_bytes)
        elif ext in ("txt", "text"):
            text = import_service.parse_txt(file_bytes)
        else:
            raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식: .{ext}")

        return {
            "text": text,
            "filename": filename,
            "char_count": len(text),
            "format": ext,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/publisher/split")
async def publisher_split(request: SplitRequest):
    """텍스트를 스마트 분할"""
    try:
        episodes = import_service.smart_split(
            text=request.text,
            mode=request.mode,
            value=request.value,
        )
        metadata = import_service.get_split_metadata(episodes)
        return {"episodes": episodes, "metadata": metadata}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/publisher/export-split")
async def publisher_export_split(request: ExportSplitRequest):
    """분할 결과를 ZIP으로 내보내기"""
    try:
        zip_buffer = export_service.create_serial_zip(
            episodes=request.episodes,
            title=request.title,
            author=request.author,
            format_type=request.format_type,
        )
        from urllib.parse import quote
        encoded_filename = quote(f"{request.title}_split.zip")
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
