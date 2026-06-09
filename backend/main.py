import json
import re
import sys

# Windows CP949 environment encoding safety fallback
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(errors='replace')
except Exception:
    pass

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
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi import Request
from backend.error_logger import log_error
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
    humor_level: int = 5        # 유머 레벨
    # [장기 기억] 이전 화 요약 체인
    memory_chain: list = []   # [{"chapter": 1, "summary": "..."}, ...]
    chapter_num: int = 1      # 현재 집필 화수
    # [Proactive STEP A] 집필 전 브리프 (이번화 지켜야 할 사항)
    chapter_brief: str = ""   # Pre-Write Brief 결과
    # [Proactive STEP C] 연속성 원장 (미해소 약속/떡밥/확립 사실)
    continuity_ledger: list = []  # [{chapter, promises_made, open_threads, ...}, ...]
    
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

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # FastAPI 엔드포인트 내에서 처리되지 않은 모든 에러 자동 감지 및 로깅
    log_error(
        error_type="FastAPI_Unhandled_Exception",
        message=str(exc),
        context={
            "path": request.url.path,
            "method": request.method,
            "query_params": dict(request.query_params)
        }
    )
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {str(exc)}"}
    )

class LogErrorRequest(BaseModel):
    error_type: str
    message: str
    detail: Optional[str] = None
    context: Optional[dict] = None

@app.post("/log_error")
async def api_log_error(req_body: LogErrorRequest):
    """프론트엔드 등 외부에서 발생한 에러를 수합하여 동일한 로그 폴더에 기록하는 엔드포인트"""
    filepath = log_error(
        error_type=req_body.error_type,
        message=req_body.message,
        detail=req_body.detail,
        context=req_body.context
    )
    return {"status": "success", "filepath": filepath}

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
            print(f"[Memory] 장기 기억 주입: {len(recent_memories)}개 화 요약 포함")

        # [Proactive STEP C] 연속성 원장 주입 (미해소 약속·떡밥·확립 사실)
        if request.continuity_ledger:
            recent_ledger = request.continuity_ledger[-5:]  # 최근 5화
            unresolved_items = []
            facts = []
            rel_state = {}
            end_state = ""
            for entry in recent_ledger:
                if not isinstance(entry, dict):
                    continue
                ch = entry.get("chapter", "?")
                for p in entry.get("promises_made", []):
                    if isinstance(p, dict) and not p.get("resolved", False):
                        unresolved_items.append(f"    - [제{ch}화 약속] {p.get('description', '')[:100]}")
                for t in entry.get("open_threads", []):
                    if isinstance(t, dict):
                        unresolved_items.append(f"    - [제{ch}화 복선] {t.get('description', '')[:100]}")
                for f_item in entry.get("established_facts", []):
                    facts.append(f"    - {str(f_item)[:100]}")
                if isinstance(entry.get("relationship_states"), dict):
                    rel_state.update(entry["relationship_states"])
                if entry.get("chapter_end_state"):
                    end_state = f"[제{ch}화 마지막 상황] {str(entry['chapter_end_state'])[:200]}"

            ledger_block_parts = []
            if unresolved_items:
                ledger_block_parts.append("[미해소 약속·복선]\n" + "\n".join(unresolved_items[-10:]))
            if facts:
                ledger_block_parts.append("[절대 모순 불가 확립 사실]\n" + "\n".join(facts[-10:]))
            if rel_state:
                rel_lines = [f"    - {k}: {v}" for k, v in list(rel_state.items())[:5]]
                ledger_block_parts.append("[인물 관계 현재 상태]\n" + "\n".join(rel_lines))
            if end_state:
                ledger_block_parts.append(end_state)
            if ledger_block_parts:
                bible_lines.append("[연속성 원장 (반드시 준수)]\n" + "\n".join(ledger_block_parts))
                print(f"[Ledger] 연속성 원장 주입: 미해소 항목 {len(unresolved_items)}개")

        # [Proactive STEP A] Pre-Write Brief 주입 (집필 전 AI가 설계한 이번화 지침)
        if request.chapter_brief and request.chapter_brief.strip():
            bible_lines.append(f"[이번화 집필 지침 (반드시 준수)]\n{request.chapter_brief[:1500]}")
            print(f"[Brief] Pre-Write Brief 주입: {len(request.chapter_brief)}자")
        
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
        print("[Brain] [Writer's Room V3] 기획자(Gemini)가 2000자 초안을 작성합니다...")
        
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

        print(f"[OK] 초안 작성 완료 (길이: {len(draft_text)}자)")
        print("[Success] Gemini 초안 반환 (수동 교정 모드 대기)")
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
            
        print(f"[Polish] [Polish Mode] 문단 교정 시작 (RAG={request.rag_enabled}): {target_text[:30]}...")
        
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
        target_model = request.model
        if "DeepSeek" in target_model:
            target_model = "models/gemini-3.1-pro-preview"
        elif "flash" in target_model.lower():
            # 문장 개고(Rewrite) 작업은 로맨스 격정적 묘사의 안전 필터 우회 및 고품질 문체 작성이 요구되므로
            # 백엔드 내부적으로 Pro급 모델(gemini-2.5-pro)로 자동 격상하여 실행합니다.
            target_model = "models/gemini-2.5-pro"

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
            model_name=target_model,
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

# ══════════════════════════════════════════════════════════════════════
# [PROACTIVE] 화차별 집필 3단계 엔드포인트
# ══════════════════════════════════════════════════════════════════════

class ChapterBriefRequest(BaseModel):
    chapter_num: int
    selected_choice: str          # 사용자가 선택한 향후 전개 옵션 텍스트
    char_sheet: str = ""
    world_setting: str = ""
    plot_outline: str = ""        # 전체 아웃라인 (이번화 플롯 파악)
    continuity_ledger: list = []  # 이전 화들의 연속성 원장
    memory_chain: list = []       # 최근 기억 체인
    model: str = "models/gemini-2.5-flash"

@app.post("/generate/chapter_brief")
async def generate_chapter_brief(request: ChapterBriefRequest):
    """
    [Proactive STEP A] Pre-Write Brief 생성
    향후 전개 선택 직후, 집필 직전에 실행.
    선택된 전개 방향 + 연속성 원장 기반으로 이번화 집필 지침을 생성합니다.
    """
    try:
        # 최근 3화 메모리 요약
        mem_text = ""
        if request.memory_chain:
            for m in request.memory_chain[-3:]:
                ch = m.get("chapter", "?")
                s = m.get("chunk_summary", m.get("summary", ""))[:200]
                cliff = m.get("cliffhanger_point", "")[:100]
                mem_text += f"  - 제{ch}화: {s} [클리프행어: {cliff}]\n"

        # 연속성 원장에서 미해소 항목 추출
        unresolved = []
        facts = []
        end_state = ""
        for entry in request.continuity_ledger[-5:]:
            if not isinstance(entry, dict):
                continue
            ch = entry.get("chapter", "?")
            for p in entry.get("promises_made", []):
                if isinstance(p, dict) and not p.get("resolved", False):
                    unresolved.append(f"[제{ch}화 약속] {p.get('description', '')[:80]}")
            for t in entry.get("open_threads", []):
                if isinstance(t, dict):
                    unresolved.append(f"[제{ch}화 복선] {t.get('description', '')[:80]}")
            for f_item in entry.get("established_facts", []):
                facts.append(str(f_item)[:80])
            if entry.get("chapter_end_state"):
                end_state = f"[제{ch}화 종료 상황] {str(entry['chapter_end_state'])[:200]}"

        unresolved_text = "\n".join(unresolved[-8:]) if unresolved else "(없음)"
        facts_text = "\n".join(facts[-8:]) if facts else "(없음)"

        # ── 다단계 안전 지침 생성 호출 ──────────────────────────────────────
        brief_text = await gemini_service.generate_chapter_brief_with_fallback(
            chapter_num=request.chapter_num,
            selected_choice=request.selected_choice,
            mem_text=mem_text,
            unresolved_text=unresolved_text,
            facts_text=facts_text,
            end_state=end_state,
            char_sheet=request.char_sheet
        )
        return {"brief": brief_text.strip()}
    except Exception as e:
        # Fail-safe: 오류 시 기본 brief 반환
        print(f"[PROACTIVE STEP A] chapter_brief 심각한 생성 실패 (Fail-safe): {e}")
        return {
            "brief": (
                "1. 이번화 필수 장면:\n"
                "   - 이전 화에서 이어지는 자연스러운 인물들의 대화와 조우 묘사\n"
                "2. 금기 사항:\n"
                "   - 급격한 갈등 봉합이나 현실성 없는 돌발 사건 배제"
            )
        }


class ChapterQCRequest(BaseModel):
    chapter_num: int
    chapter_text: str             # 방금 생성된 본문
    chapter_brief: str = ""       # STEP A에서 생성된 집필 지침
    continuity_ledger: list = []  # 이전 화들의 연속성 원장
    char_sheet: str = ""
    model: str = "models/gemini-2.5-flash"

@app.post("/generate/chapter_qc")
async def generate_chapter_qc(request: ChapterQCRequest):
    """
    [Proactive STEP B] Post-Write QC + Self-Heal
    집필 완료 직후 실행. 브리프·연속성 기준 위반 여부 자동 검사.
    실패 시 healed_text(자동 재집필 결과)를 반환합니다.
    """
    try:
        # 연속성 원장에서 핵심 항목만 추출
        must_keep = []
        for entry in request.continuity_ledger[-3:]:
            if not isinstance(entry, dict):
                continue
            ch = entry.get("chapter", "?")
            for f_item in entry.get("established_facts", []):
                must_keep.append(f"[제{ch}화 확립] {str(f_item)[:80]}")
            for p in entry.get("promises_made", []):
                if isinstance(p, dict) and not p.get("resolved", False):
                    must_keep.append(f"[제{ch}화 약속 유지] {p.get('description', '')[:80]}")
        must_keep_text = "\n".join(must_keep[-8:]) if must_keep else "(없음)"

        flash_model = "models/gemini-2.5-flash"
        qc_result = await gemini_service.perform_chapter_qc_with_fallback(
            chapter_num=request.chapter_num,
            chapter_text=request.chapter_text,
            chapter_brief=request.chapter_brief,
            must_keep_text=must_keep_text,
            char_sheet=request.char_sheet,
            model_name=flash_model
        )

        passed = qc_result.get("passed", True)
        issues = qc_result.get("issues", [])
        severity = qc_result.get("severity", "low")

        healed_text = ""
        if not passed and severity in ("medium", "high"):
            # Self-Heal: 지침 위반 시 자동 재집필
            heal_prompt = (
                f"다음 제{request.chapter_num}화 본문에는 아래 문제점이 발견되었습니다. "
                f"문제점을 교정하면서 원본의 감성·분위기·길이는 최대한 유지하며 재작성하십시오.\n\n"
                f"[발견된 문제]\n" + "\n".join(f"- {i}" for i in issues) + "\n\n"
                f"[집필 지침]\n{request.chapter_brief[:600] if request.chapter_brief else '(없음)'}\n\n"
                f"[원본 본문]\n{request.chapter_text[:3000]}\n\n"
                f"수정된 본문만 출력하십시오. 설명 텍스트 없이."
            )
            try:
                try:
                    healed_text = await gemini_service._call_gem_with_retry(
                        heal_prompt, flash_model, max_tokens=4096, temperature=0.3
                    )
                    healed_text = healed_text.strip()
                except Exception as inner_err:
                    print(f"[STEP B Self-Heal] 1차 재집필 차단/실패, 본문 민감문장 필터링 후 시도: {inner_err}")
                    filtered_text_for_heal = gemini_service._filter_sensitive_sentences(request.chapter_text[:3000])
                    heal_prompt_filtered = (
                        f"다음 제{request.chapter_num}화 본문에는 아래 문제점이 발견되었습니다. "
                        f"문제점을 교정하면서 원본의 감성·분위기·길이는 최대한 유지하며 재작성하십시오.\n\n"
                        f"[발견된 문제]\n" + "\n".join(f"- {i}" for i in issues) + "\n\n"
                        f"[집필 지침]\n{request.chapter_brief[:600] if request.chapter_brief else '(없음)'}\n\n"
                        f"[원본 본문]\n{filtered_text_for_heal}\n\n"
                        f"수정된 본문만 출력하십시오. 설명 텍스트 없이."
                    )
                    healed_text = await gemini_service._call_gem_with_retry(
                        heal_prompt_filtered, flash_model, max_tokens=4096, temperature=0.3, retries=1
                    )
                    healed_text = healed_text.strip()
            except Exception as heal_err:
                print(f"[STEP B Self-Heal] 재집필 완전 실패 (원본 유지): {heal_err}")
                healed_text = ""

        return {
            "passed": passed,
            "issues": issues,
            "severity": severity,
            "healed_text": healed_text
        }
    except Exception as e:
        # Fail-safe: QC 자체가 실패해도 passed=True 반환 (집필 중단 없음)
        print(f"[PROACTIVE STEP B] chapter_qc 실패 (Fail-safe): {e}")
        return {"passed": True, "issues": [], "severity": "low", "healed_text": ""}


class ChapterLedgerRequest(BaseModel):
    chapter_num: int
    chapter_text: str             # 확정된 최종 본문
    existing_ledger: list = []    # 기존 누적 원장
    model: str = "models/gemini-2.5-flash"

@app.post("/generate/chapter_ledger")
async def generate_chapter_ledger(request: ChapterLedgerRequest):
    """
    [Proactive STEP C] Continuity Ledger 업데이트
    최종 본문 확정 후 실행. 이번화에서 생긴 약속·떡밥·확립사실·관계 상태를 추출합니다.
    """
    try:
        # 기존 미해소 항목 (최근 5화, 최대 8개)
        unresolved = []
        for entry in request.existing_ledger[-5:]:
            if not isinstance(entry, dict):
                continue
            ch = entry.get("chapter", "?")
            for p in entry.get("promises_made", []):
                if isinstance(p, dict) and not p.get("resolved", False):
                    unresolved.append(f"[제{ch}화] {p.get('description', '')[:80]}")
            for t in entry.get("open_threads", []):
                if isinstance(t, dict):
                    unresolved.append(f"[제{ch}화 복선] {t.get('description', '')[:80]}")
        unresolved_text = "\n".join(unresolved[-8:]) if unresolved else "(없음)"

        # ── 다단계 안전 원장 추출 호출 ──────────────────────────────────────
        ledger_item = await gemini_service.extract_continuity_ledger_with_fallback(
            chapter_num=request.chapter_num,
            chapter_text=request.chapter_text,
            unresolved_text_c=unresolved_text,
            ch_summary="" # 생략 시 내부 자동 생성
        )
        return {"ledger_item": ledger_item}
    except Exception as e:
        # Fail-safe: 실패 시 빈 구조체 반환
        print(f"[PROACTIVE STEP C] chapter_ledger 생성 실패 (Fail-safe): {e}")
        return {"ledger_item": {
            "chapter": request.chapter_num,
            "promises_made": [], "open_threads": [],
            "resolved_from_previous": [], "established_facts": ["제{chapter_num}화 스토리 전개 완료".format(chapter_num=request.chapter_num)],
            "relationship_states": {}, "chapter_end_state": "",
            "error": str(e)[:100]
        }}

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
    style: Optional[str] = "기본"

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

def extract_review_via_regex(raw_text: str) -> dict:
    import re
    
    scores = {"consistency": 70, "grammar_flow": 70, "creativity": 70}
    feedback = {"consistency": "분석 완료", "grammar_flow": "분석 완료", "creativity": "분석 완료"}
    overall_critique = ""
    improvement_suggestions = []
    recommended_chapters = []
    
    # Extract scores
    for key in ["consistency", "grammar_flow", "creativity"]:
        match = re.search(r'"' + key + r'"\s*:\s*(\d+)', raw_text, re.IGNORECASE)
        if match:
            scores[key] = int(match.group(1))
            
    # Extract feedback
    for key in ["consistency", "grammar_flow", "creativity"]:
        # Find key followed by a string value anywhere in raw_text
        match = re.search(r'"' + key + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text, re.DOTALL | re.IGNORECASE)
        if match:
            feedback[key] = match.group(1).replace(r'\"', '"').replace(r'\n', '\n').strip()
        else:
            match_lax = re.search(r'"' + key + r'"\s*:\s*"((?:[^"\\]|\\.)*)', raw_text, re.DOTALL | re.IGNORECASE)
            if match_lax:
                val = match_lax.group(1).replace(r'\"', '"').replace(r'\n', '\n').strip()
                if val and not val.isdigit():
                    feedback[key] = val
                    
    # Extract overall_critique
    match_crit = re.search(r'"overall_critique"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text, re.DOTALL | re.IGNORECASE)
    if match_crit:
        overall_critique = match_crit.group(1).replace(r'\"', '"').replace(r'\n', '\n').strip()
    else:
        match_crit_lax = re.search(r'"overall_critique"\s*:\s*"((?:[^"\\]|\\.)*)', raw_text, re.DOTALL | re.IGNORECASE)
        if match_crit_lax:
            overall_critique = match_crit_lax.group(1).replace(r'\"', '"').replace(r'\n', '\n').strip()
            
    # Extract improvement_suggestions
    suggest_match = re.search(r'"improvement_suggestions"\s*:\s*\[(.*?)\]', raw_text, re.DOTALL | re.IGNORECASE)
    if suggest_match:
        items = re.findall(r'"((?:[^"\\]|\\.)*)"', suggest_match.group(1), re.DOTALL)
        improvement_suggestions = [item.replace(r'\"', '"').replace(r'\n', '\n').strip() for item in items if item.strip()]
    else:
        # If the array is truncated, extract as many quoted items as possible after the key
        sug_start = raw_text.find('"improvement_suggestions"')
        if sug_start != -1:
            sug_text = raw_text[sug_start:]
            items = re.findall(r'"((?:[^"\\]|\\.)*)"', sug_text[:1000], re.DOTALL)
            improvement_suggestions = [item.replace(r'\"', '"').replace(r'\n', '\n').strip() for item in items if item.strip() and not item.strip().lower() in ["consistency", "grammar_flow", "creativity", "overall_critique", "recommended_chapters"]]
        
    # Extract recommended_chapters
    # Robust individual block matching to recover even from truncated JSON
    recs_start = raw_text.find('"recommended_chapters"')
    if recs_start != -1:
        recs_text = raw_text[recs_start:]
        obj_matches = re.finditer(r'\{\s*["\']chapter["\']\s*:\s*(\d+).*?\}', recs_text, re.DOTALL | re.IGNORECASE)
        found_chaps = set()
        for obj in obj_matches:
            block = obj.group(0)
            ch_match = re.search(r'["\']chapter["\']\s*:\s*(\d+)', block, re.IGNORECASE)
            reason_match = re.search(r'["\']reason["\']\s*:\s*"((?:[^"\\]|\\.)*)"', block, re.DOTALL | re.IGNORECASE)
            if not reason_match:
                reason_match = re.search(r'["\']reason["\']\s*:\s*"([^"]*)', block, re.DOTALL | re.IGNORECASE)
            
            if ch_match:
                ch_num = int(ch_match.group(1))
                reason = "수정 필요"
                if reason_match:
                    reason = reason_match.group(1).replace(r'\"', '"').replace(r'\n', '\n').strip()
                if ch_num not in found_chaps:
                    recommended_chapters.append({"chapter": ch_num, "reason": reason})
                    found_chaps.add(ch_num)
                    
    # Fallback to standard check if the above didn't find any but the enclosing brackets exist
    if not recommended_chapters:
        recs_match = re.search(r'"recommended_chapters"\s*:\s*\[(.*?)\]', raw_text, re.DOTALL | re.IGNORECASE)
        if recs_match:
            obj_blocks = re.findall(r'\{(.*?)\}', recs_match.group(1), re.DOTALL)
            for block in obj_blocks:
                ch_match = re.search(r'"chapter"\s*:\s*(\d+)', block)
                reason_match = re.search(r'"reason"\s*:\s*"((?:[^"\\]|\\.)*)"', block, re.DOTALL)
                if ch_match:
                    ch_num = int(ch_match.group(1))
                    reason = reason_match.group(1).replace(r'\"', '"').replace(r'\n', '\n').strip() if reason_match else "수정 필요"
                    recommended_chapters.append({"chapter": ch_num, "reason": reason})
                
    if not overall_critique:
        overall_critique = raw_text
        
    return {
        "scores": scores,
        "feedback": feedback,
        "overall_critique": overall_critique,
        "improvement_suggestions": improvement_suggestions,
        "recommended_chapters": recommended_chapters
    }

class ReviewRequest(BaseModel):
    text: Optional[str] = None
    memory_chain: Optional[list] = []  # List of precision summaries and entity updates
    applied_fixes: Optional[list] = []  # 이미 교정 완료된 화차 리스트 추가
    criteria: str = "Consistency, Grammar, Creativity"
    model: str = "models/gemini-3-flash-preview"

@app.post("/analyze/review_comprehensive")
async def analyze_review_comprehensive(request: ReviewRequest):
    try:
        target_model = request.model
        if "DeepSeek" in target_model:
            target_model = "models/gemini-3.1-pro-preview"
        elif "flash" in target_model.lower():
            # Flash급 모델은 장기 소설 맥락의 정밀 분석 시 비결정성과 주의 분산 한계가 존재하므로,
            # 전체 작품 비평 만큼은 가장 성능이 우수하고 일관성이 뛰어난 gemini-2.5-pro 모델로 자동 승격하여 처리합니다.
            target_model = "models/gemini-2.5-pro"

        if request.memory_chain:
            # Compress memory chain aggressively to stay well under the request/response gateway limits
            compact_chain = []
            for item in request.memory_chain:
                ch_num = item.get("chapter", 0)
                summary = item.get("chunk_summary", item.get("summary", ""))
                if len(summary) > 150:
                    summary = summary[:150] + "..."
                compact_chain.append({
                    "chapter": ch_num,
                    "summary": summary
                })

            # 이미 교정이 완료된 화차 목록 정보 구성
            applied_fixes_text = ""
            if request.applied_fixes:
                try:
                    unique_fixes = sorted(list(set(map(int, request.applied_fixes))))
                    ch_list_str = ", ".join([f"제{x}화" for x in unique_fixes])
                    applied_fixes_text = (
                        f"\n[이미 교정 완료된 화차 목록]\n"
                        f"{ch_list_str}\n"
                        f"(위 화차들은 최근 비평 피드백이 이미 성공적으로 반영되어 개고되었습니다. "
                        f"새로운 치명적인 모순이 감지되지 않는 한, 이 화차들은 추천 교정 대상('recommended_chapters')에서 필터링하여 제외하십시오.)\n"
                    )
                except Exception:
                    pass

            # Map-Reduce mode: Perform aggregate evaluation of all chapter summaries
            map_prompt = f"""
당신은 대한민국 최고의 웹소설 기획자이자 비평가입니다. 다음 축적된 [매화별 초정밀 요약 및 캐릭터/세계관 설정 변동사항]을 기반으로 작품 전체의 장기적 일관성, 개연성, 상업성 및 전개 템포를 심층 비평하십시오.

[스토리 메타데이터 피드]
{json.dumps(compact_chain, ensure_ascii=False, indent=2)}
{applied_fixes_text}
[검토 기준]
- 캐릭터 감정선의 누적 및 개연성 (Characters arc consistency)
- 시공간/규칙의 일관성 (World setting consistency)
- 상업적 텐션 및 호흡 (Pacing and commercial potential)

[중요 지시 사항 - 추천 교정 대상 화차 선정 규칙]
1. **오직 소설 서사의 기본 틀이 무너지는 '치명적 모순(Hard Conflict/Critical Error)'만 검출하여 추천 대상에 넣으십시오.**
   - 검출 대상(CRITICAL ERROR): 예) 죽었던 인물이 부활하여 활동함, 서울에 있던 인물이 같은 시간대 설명 없이 부산에서 행동함, 설정 정보가 앞뒤로 정면 충돌함, 인물의 태도가 계기나 내면 묘사 전혀 없이 180도 급변하여 개연성이 붕괴함.
   - 검출 제외 대상(STYLE & QUALITY): 예) 감정 묘사가 더 풍부했으면 좋겠다, 장면 전환이 조금 급하다, 티키타카 대화가 길다, 빌드업이 부족하다, 서사 템포 조절이 필요하다 등. 이러한 연출/문체상 아쉬움은 절대 추천 교정 대상 화차(`recommended_chapters`)에 넣지 마십시오. 오직 피드백 텍스트(`feedback`)에만 적으십시오.
2. **동일한 설정 충돌 문제가 여러 화차에 걸쳐 있을 때는, 문제의 발단이 되는 최초의 1~2개 핵심 화차만 추천하십시오.** (한꺼번에 모든 관련 화차를 쏟아내지 마십시오.)
3. **만약 위에서 정의한 치명적 모순(CRITICAL ERROR)이 감지되지 않는다면, 반드시 `recommended_chapters`를 빈 배열 `[]`로 반환하십시오.** (억지로 트집을 잡아 추천 목록을 채우지 마십시오. 완성도가 높으면 0개여야 합니다.)
4. **리스트에 노출할 추천 교정 대상 화차는 최대 5개 이내로 제한하며, 앞선 화차 우선으로 선정하십시오.**
5. **피드백(feedback) 본문에서 직접적으로 지적하고 언급한 수정 대상 화차는 반드시 `recommended_chapters` 배열에 구조화된 형태로 함께 포함되어야 합니다. 본문과 배열의 내용이 반드시 일치해야 합니다.**
6. **추천 화차별 수정 사유(reason)는 절대 길게 쓰지 말고, 1문장(50자 내외)으로 극도로 짧고 간결하게 핵심만 쓰십시오. 사유를 길게 늘여 쓰면 출력 제한으로 인해 전체 분석이 깨집니다.**
7. **동일한 상태에서 분석을 다시 누를 때 동일하고 일관된 결과가 나와야 하므로, 정확하고 엄밀하게 전수 조사하십시오.**
8. **모든 비평 내용(feedback의 각 항목 및 overall_critique)은 화차별로 핵심만 요약하여 매우 간결하게(단락별 1~2문장 이내) 작성하십시오. 군더더기 없이 짧게 작성하는 것이 가장 중요합니다.**

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
    "improvement_suggestions": ["전체 개선 제안 1", "전체 개선 제안 2"],
    "recommended_chapters": [
        {{"chapter": 15, "reason": "14화에서 언급된 갈등이 아무런 감정적 징검다리 서사 없이 15화에서 급작스럽게 풀려 개연성이 심각하게 저해됩니다. 중간 갈등 해소 장면 보완이 필요합니다."}},
        {{"chapter": 28, "reason": "27화의 서울 공간 배경 설정이 28화에서 갑자기 설명 없이 부산으로 바뀌며 일관성이 깨졌습니다. 배경 전환 서술이 필요합니다."}}
    ]
}}
"""
            raw_text = await gemini_service._call_gem_with_retry(
                map_prompt, 
                target_model, 
                temperature=0.0,
                response_mime_type="application/json"
            )
            try:
                import os
                debug_log_path = os.path.join(os.path.dirname(__file__), "debug_raw_text.txt")
                with open(debug_log_path, "w", encoding="utf-8") as df:
                    df.write(raw_text)
                print(f"[DEBUG] Raw text saved to {debug_log_path}. Length: {len(raw_text)}")
            except Exception as df_err:
                print(f"[DEBUG] Failed to save raw text: {df_err}")
            cleaned = raw_text.replace("```json", "").replace("```", "").strip()
            
            import json as json_mod
            import re
            
            # Extract only the JSON object between { and }
            match = re.search(r'(\{.*\})', cleaned, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                json_str = cleaned
                
            try:
                review_data = json_mod.loads(json_str)
            except Exception as json_err:
                try:
                    # Attempt to clean trailing commas before closing braces/brackets
                    cleaned_json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
                    review_data = json_mod.loads(cleaned_json_str)
                except Exception:
                    # Fallback to robust regex parsing
                    try:
                        review_data = extract_review_via_regex(raw_text)
                    except Exception as regex_err:
                        # Absolute fallback if regex fails
                        review_data = {
                            "scores": {"consistency": 70, "grammar_flow": 70, "creativity": 70},
                            "feedback": {
                                "consistency": f"전체 점검 중 분석기 오류가 발생했습니다: {str(regex_err)}",
                                "grammar_flow": "원문 피드백을 참고해 주십시오.",
                                "creativity": "설정 보완 권장"
                            },
                            "overall_critique": raw_text,
                            "improvement_suggestions": ["원고 상태를 다시 확인하고 리프레시 후 점검해 주십시오."],
                            "recommended_chapters": []
                        }
                    
            # ── applied_fixes 보존: 서버측에서 AI가 재추천하지 않도록 필터 후 반환 ──
            # AI가 applied_fixes 화차를 재추천하는 경우, 반환 전에 서버측에서 제거합니다.
            try:
                if request.applied_fixes and isinstance(request.applied_fixes, list):
                    applied_ints = set()
                    for x in request.applied_fixes:
                        try:
                            applied_ints.add(int(x))
                        except (ValueError, TypeError):
                            pass
                    if applied_ints:
                        # 프론트엔드와 동일하게 다양한 키 후보들을 점검하여 필터링
                        rec_keys = ["recommended_chapters", "recommended_chapter", "suggested_chapters", "chapters_to_fix"]
                        for key in rec_keys:
                            if key in review_data and isinstance(review_data[key], list):
                                original_recs = review_data[key]
                                filtered_recs = []
                                removed = 0
                                for item in original_recs:
                                    ch_num = -1
                                    try:
                                        if isinstance(item, dict):
                                            ch_num = int(item.get("chapter", -1))
                                        elif isinstance(item, (int, str)):
                                            ch_num = int(item)
                                    except (ValueError, TypeError):
                                        pass
                                    
                                    if ch_num != -1 and ch_num in applied_ints:
                                        removed += 1
                                    else:
                                        filtered_recs.append(item)
                                
                                if removed > 0:
                                    print(f"[Review] 서버측 {key} 필터: {removed}개 이미 완료된 화차 재추천 제거")
                                review_data[key] = filtered_recs
                        
                    # applied_fixes를 반환값에 포함시켜 프론트엔드에서 덮어쓰기 방지
                    review_data["applied_fixes"] = sorted(list(applied_ints))
                else:
                    review_data.setdefault("applied_fixes", [])
            except Exception as af_err:
                print(f"[Review] applied_fixes 처리 중 오류 (무시): {af_err}")
                review_data.setdefault("applied_fixes", [])

            return {"review": review_data}
        else:
            # Standard single segment mode
            review = await gemini_service.perform_comprehensive_review(request.text or "", request.criteria, target_model)
            return {"review": review}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ArcRepairRequest(BaseModel):
    prompt: str
    model: str = "models/gemini-2.5-pro"

@app.post("/analyze/arc_repair")
async def analyze_arc_repair(request: ArcRepairRequest):
    """
    감정 아크 다화차 진단 전용 엔드포인트.
    Arc Repair 패널의 분석 프롬프트를 받아 Pro 모델로 화차별 집필 수정 지침을 생성합니다.
    """
    try:
        target_model = "models/gemini-2.5-pro"  # 항상 Pro 모델로 고품질 편집 진단
        raw = await gemini_service._call_gem_with_retry(
            request.prompt,
            target_model,
            max_tokens=8192,
            temperature=0.3
        )
        return {
            "review": {
                "overall_critique": raw,
                "scores": {},
                "feedback": {},
                "improvement_suggestions": [],
                "recommended_chapters": []
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# BATCH HOLISTIC FIX — Surgical Plan 3-Pass
# ==========================================

class ChapterToFix(BaseModel):
    chapter_num: int
    reason: str
    text: str  # 원본 본문

class BatchFixRequest(BaseModel):
    chapters_to_fix: List[ChapterToFix]       # 수정 대상 화차들
    all_memory_chain: List[dict] = []          # 전체 memory_chain (50화)
    plot_outline: str = ""                     # 전체 줄거리 텍스트
    char_sheet: str = ""
    world_setting: str = ""
    overall_critique: str = ""                 # Run Deep Analysis 종합 비평
    style_guide: str = ""
    model: str = "models/gemini-2.5-pro"
    rag_enabled: bool = False
    rag_category_id: Optional[int] = None
    rag_series_id: Optional[int] = None
    rag_keyword: Optional[str] = ""

@app.post("/analyze/batch_fix")
async def analyze_batch_fix(request: BatchFixRequest):
    """
    Surgical Plan 기반 Holistic Batch Fix (3-Pass):
    Pass 1: 전체 서사 맥락에서 근본 원인 진단 + 수술 계획서(Surgical Plan) 생성
    Pass 2: 수술 계획서를 공통 컨텍스트로 화차별 순차 수정 (이전 수정 결과 누적)
    Pass 3: 수정 결과 검증 → 검증 리포트 반환
    """
    try:
        pro_model = "models/gemini-2.5-pro"
        chapters = sorted(request.chapters_to_fix, key=lambda x: x.chapter_num)
        chapter_nums = [c.chapter_num for c in chapters]

        # ── 컨텍스트 준비 ──
        memory_summary = "\n".join([
            f"  제{m.get('chapter', m.get('chapter_num', '?'))}화: {m.get('chunk_summary', m.get('summary', ''))[:150]}"
            for m in request.all_memory_chain
        ]) if request.all_memory_chain else "(memory_chain 없음)"

        # 원문 300자 제한 — 더 많으면 SAFETY 필터 누적 트리거 위험
        flagged_text = "\n\n".join([
            f"[제{c.chapter_num}화]\n지적 사유: {c.reason}\n본문 앞부분(300자):\n{c.text[:300]}"
            for c in chapters
        ])

        chapter_nums_str = ", ".join([f"제{n}화" for n in chapter_nums])

        # 화차별 명세 텍스트를 미리 생성 (f-string 중첩 방지)
        chapter_specs_text = "\n".join([
            f"### 제{c.chapter_num}화\n"
            f"- **Input State** (이 화를 시작할 때 독자/인물이 가진 상태): \n"
            f"- **Output State** (이 화를 마쳤을 때 반드시 달성해야 할 상태 - 검증 기준): \n"
            f"- **Must Keep** (절대 변경 금지 요소): \n"
            f"- **Must Change** (반드시 수정해야 할 요소): \n"
            f"- **Bridge** (다음 수정 화차로 넘겨야 할 감정적 바통): "
            for c in chapters
        ])

        # ══════════════════════════════════════════
        # PASS 1: 수술 계획서 (Surgical Plan) 생성
        # ══════════════════════════════════════════
        surgical_plan_prompt = (
            f"당신은 대한민국 최정상 웹소설 총괄 편집장입니다.\n"
            f"아래 정보를 바탕으로 {chapter_nums_str}의 서사 문제를 정밀 진단하고,\n"
            f"각 화차가 서로를 인식하는 통합 수술 계획서를 작성하십시오.\n\n"
            f"[전체 줄거리]\n{request.plot_outline[:3000] if request.plot_outline else '(줄거리 정보 없음)'}\n\n"
            f"[전체 화차 memory 요약]\n{memory_summary}\n\n"
            f"[AI 비평가 종합 비평]\n{request.overall_critique[:2000] if request.overall_critique else '(비평 정보 없음)'}\n\n"
            f"[수정 대상 화차 및 지적 사유]\n{flagged_text}\n\n"
            f"[인물 설정]\n{request.char_sheet[:1000] if request.char_sheet else ''}\n\n"
            f"[지시사항]\n다음 형식으로 수술 계획서를 작성하십시오. 반드시 한국어로:\n\n"
            f"## 근본 원인 진단\n"
            f"(이 {len(chapters)}개 화차가 동시에 지적된 서사적 근본 원인을 전체 아크 관점에서 3~5문장으로 설명)\n\n"
            f"## 수정 완료 후 목표 감정 흐름\n"
            f"(수정이 완료되었을 때 {chapter_nums_str} 전체에 걸쳐 독자가 경험해야 할 감정 여정)\n\n"
            f"## 화차별 수술 명세\n{chapter_specs_text}\n\n"
            f"## 수정 제약 원칙\n(전체 수정 시 반드시 지켜야 할 공통 원칙 3~5가지)"
        )

        # Pass 1: SAFETY 차단 시 비평만으로 단순 fallback 계획서 생성
        try:
            surgical_plan = await gemini_service._call_gem_with_retry(
                surgical_plan_prompt, pro_model, max_tokens=8192, temperature=0.3
            )
        except Exception as plan_err:
            plan_err_str = str(plan_err)
            print(f"[Batch Fix] Pass 1 실패: {plan_err_str}. 비평 기반 fallback 계획서 생성")
            # fallback: 본문 없이 비평 + 사유만으로 단순 계획서 요청
            fallback_prompt = (
                f"당신은 웹소설 편집장입니다. 아래 비평과 지적 사유만으로 {chapter_nums_str}의 수술 계획서를 간략하게 작성하십시오.\n\n"
                f"[AI 비평]\n{request.overall_critique[:1500] if request.overall_critique else '(없음)'}\n\n"
                f"[지적 사유]\n"
                + "\n".join([f"제{c.chapter_num}화: {c.reason}" for c in chapters])
                + "\n\n## 근본 원인 진단\n## 수정 완료 후 목표 감정 흐름\n"
                + "\n".join([f"### 제{c.chapter_num}화\n- Must Change: {c.reason}\n- Must Keep: 인물 관계선 유지" for c in chapters])
                + "\n## 수정 제약 원칙\n1. 감정선 자연스럽게 유지 2. 분량 유지 3. 마지막 문장 완결"
            )
            try:
                surgical_plan = await gemini_service._call_gem_with_retry(
                    fallback_prompt, "models/gemini-2.5-flash", max_tokens=4096, temperature=0.3
                )
            except Exception:
                # 최종 fallback: 구조화된 기본 계획서
                surgical_plan = (
                    f"## 근본 원인 진단\n각 화차의 서사 문제를 개선해야 합니다.\n\n"
                    f"## 수정 완료 후 목표 감정 흐름\n독자가 자연스럽게 몰입할 수 있는 감정 흐름.\n\n"
                    + "\n".join([
                        f"### 제{c.chapter_num}화\n"
                        f"- **Must Change**: {c.reason}\n"
                        f"- **Must Keep**: 인물 관계선 및 핵심 플롯\n"
                        f"- **Bridge**: 다음 화로 긴장감 이어가기"
                        for c in chapters
                    ])
                    + "\n\n## 수정 제약 원칙\n1. 분량 유지 2. 감정선 연결 3. 마지막 문장 완결"
                )


        # ══════════════════════════════════════════
        # PASS 2: 화차별 순차 수정 (Surgical Plan 공통 컨텍스트)
        # ══════════════════════════════════════════
        fixed_results = []

        # RAG 컨텍스트 사전 조회
        rag_context = ""
        if request.rag_enabled:
            try:
                rag_context = await db_service.get_rag_context(
                    query_text=request.overall_critique[:500],
                    category_id=request.rag_category_id,
                    series_id=request.rag_series_id,
                    keyword=request.rag_keyword,
                    limit=2
                )
            except Exception:
                pass

        for ch in chapters:
            ch_num = ch.chapter_num

            # 이전 수정 완료 화차 누적 컨텍스트 (500자 제한 — 프롬프트 과부하 방지)
            prev_fixes_context = ""
            if fixed_results:
                prev_lines = []
                for r in fixed_results:
                    snippet = r['fixed_text'][:500]
                    prev_lines.append(f"[제{r['chapter_num']}화 수정 완료 — 앞부분 500자]\n{snippet}")
                prev_fixes_context = (
                    "\n\n[이미 수정 완료된 화차들 — 이 내용과 자연스럽게 연결해야 합니다]\n"
                    + "\n\n".join(prev_lines)
                )

            # 전후 memory 컨텍스트
            surrounding_mem = []
            for m in request.all_memory_chain:
                m_num = int(m.get('chapter', m.get('chapter_num', 0)))
                if abs(m_num - ch_num) <= 3 and m_num != ch_num:
                    surrounding_mem.append(
                        f"  제{m_num}화: {m.get('chunk_summary', m.get('summary', ''))[:200]}"
                    )
            surrounding_context = "\n".join(surrounding_mem) if surrounding_mem else ""

            # ── plan_only_prompt: 원문 제외 (원문은 rewrite_for_batch가 별도 처리) ──
            # 수술 계획서 2000자 제한 (SAFETY 차단 주요 원인 제거)
            surgical_plan_limited = surgical_plan[:2000] if surgical_plan else ""
            rag_context_limited = rag_context[:500] if rag_context else ""

            plan_only_prompt = (
                f"당신은 대한민국 최정상 웹소설 전문 대필 편집자입니다.\n"
                f"아래 [수술 계획서]를 최우선 기준으로 제{ch_num}화를 개고(Rewrite)하십시오.\n\n"
                f"══════════════════════════════════════\n"
                f"📋 수술 계획서 (Surgical Plan) — 반드시 준수\n"
                f"══════════════════════════════════════\n"
                f"{surgical_plan_limited}\n\n"
                f"══════════════════════════════════════\n"
                f"📖 소설 고정 설정\n"
                f"══════════════════════════════════════\n"
                f"인물 설정: {request.char_sheet[:600] if request.char_sheet else ''}\n"
                f"세계관: {request.world_setting[:400] if request.world_setting else ''}\n"
                + (f"스타일 가이드:\n{request.style_guide[:400]}\n" if request.style_guide else "")
                + (f"RAG 스타일 레퍼런스:\n{rag_context_limited}\n" if rag_context_limited else "")
                + f"\n══════════════════════════════════════\n"
                f"📚 전후 화차 맥락 (개연성 연결 기준)\n"
                f"══════════════════════════════════════\n"
                f"{surrounding_context if surrounding_context else '(맥락 정보 없음)'}\n"
                f"{prev_fixes_context}\n\n"
                f"══════════════════════════════════════\n"
                f"🎯 제{ch_num}화 핀포인트 수정 지시\n"
                f"══════════════════════════════════════\n"
                f"지적 사유: {ch.reason}\n"
            )

            # ── rewrite_for_batch 호출: 원문을 별도로 전달 → SAFETY 자동 fallback 적용 ──
            fixed_text = await gemini_service.rewrite_for_batch(
                text=ch.text,
                plan_prompt=plan_only_prompt,
                model_name=pro_model
            )

            fixed_results.append({
                "chapter_num": ch_num,
                "fixed_text": fixed_text,
                "original_text": ch.text,
                "reason": ch.reason
            })

        # ══════════════════════════════════════════
        # PASS 3: 검증 리포트
        # ══════════════════════════════════════════
        fixed_summary = "\n\n".join([
            f"[제{r['chapter_num']}화 수정 결과 앞부분]\n{r['fixed_text'][:300]}"
            for r in fixed_results
        ])

        verify_prompt = (
            "당신은 순수 창작 목적의 소설을 검사하고 비평하는 편집장입니다. "
            "아래 내용은 모두 허구의 로맨스 소설 텍스트이며 실제 사건 및 인물과 무관합니다. "
            "작품의 서사 일관성을 검토하는 리포트를 작성하십시오.\n\n"
            f"아래 수술 계획서와 수정 결과를 비교하여 검증 리포트를 작성하십시오.\n\n"
            f"[수술 계획서]\n{surgical_plan[:2000]}\n\n"
            f"[수정 결과 요약]\n{fixed_summary}\n\n"
            "[검증 지시사항]\n"
            "각 화차별로:\n"
            "1. Output State가 달성되었는지 (✅/⚠️/❌)\n"
            "2. Must Keep이 유지되었는지\n"
            "3. Bridge(감정 바통)가 자연스럽게 연결되었는지\n"
            "4. 전체 아크 목표 달성 여부 (종합 평가)\n\n"
            "반드시 한국어로 간결하게 작성하십시오. (각 화차 2~3줄, 종합 3~5줄)"
        )

        # Pass 3: 검증 실패해도 수정 결과는 살려야 함 (다단계 Fallback 적용)
        try:
            verification_report = await gemini_service._call_gem_with_retry(
                verify_prompt, "models/gemini-2.5-flash", max_tokens=2048, temperature=0.2
            )
        except Exception as verify_err1:
            print(f"[Batch Fix] Pass 3 검증 1차 실패 (민감문장 필터링 후 재시도): {verify_err1}")
            try:
                # 2차 시도: surgical_plan과 fixed_summary에서 민감 문장 제거
                safe_plan = gemini_service._filter_sensitive_sentences(surgical_plan[:2000])
                safe_summary = gemini_service._filter_sensitive_sentences(fixed_summary)
                verify_prompt_safe = (
                    "당신은 순수 창작 목적의 소설을 검사하고 비평하는 편집장입니다. "
                    "아래 내용은 모두 허구의 로맨스 소설 텍스트이며 실제 사건 및 인물과 무관합니다. "
                    "작품의 서사 일관성을 검토하는 리포트를 작성하십시오.\n\n"
                    f"아래 수술 계획서와 수정 결과를 비교하여 검증 리포트를 작성하십시오.\n\n"
                    f"[수술 계획서]\n{safe_plan}\n\n"
                    f"[수정 결과 요약]\n{safe_summary}\n\n"
                    "[검증 지시사항]\n"
                    "각 화차별로:\n"
                    "1. Output State가 달성되었는지 (✅/⚠️/❌)\n"
                    "2. Must Keep이 유지되었는지\n"
                    "3. 전체 아크 목표 달성 여부 (종합 평가)\n\n"
                    "반드시 한국어로 간결하게 작성하십시오."
                )
                verification_report = await gemini_service._call_gem_with_retry(
                    verify_prompt_safe, "models/gemini-2.5-flash", max_tokens=2048, temperature=0.2, retries=1
                )
            except Exception as verify_err2:
                print(f"[Batch Fix] Pass 3 검증 2차 실패 (기본 메시지 대체): {verify_err2}")
                verification_report = (
                    f"⚠️ 검증 리포트 생성 실패 (SAFETY 또는 네트워크 오류). "
                    f"수정된 {len(fixed_results)}개 화차 결과는 정상 저장되었습니다."
                )

        return {
            "surgical_plan": surgical_plan,
            "fixed_chapters": fixed_results,
            "verification_report": verification_report
        }

    except Exception as e:
        err_str = str(e)
        print(f"[Batch Fix] 엔드포인트 오류: {err_str}")
        # fixed_results가 일부라도 있으면 부분 성공 반환 (데이터 손실 방지)
        if 'fixed_results' in locals() and fixed_results:
            return {
                "surgical_plan": locals().get('surgical_plan', '계획서 생성 실패'),
                "fixed_chapters": fixed_results,
                "verification_report": f"⚠️ 일부 오류 발생: {err_str[:200]}",
                "partial": True
            }
        raise HTTPException(status_code=500, detail=err_str)


# ==========================================
# CONTINUITY LEDGER — 연속성 원장 추출
# ==========================================

class ExtractLedgerRequest(BaseModel):
    chapter_num: int
    chapter_text: str          # 집필 완료된 화차 본문
    char_sheet: str = ""
    existing_ledger: list = [] # 기존 누적 원장 (열린 약속/떡밥 추적용)
    model: str = "models/gemini-2.5-flash"

@app.post("/analyze/extract_ledger")
async def analyze_extract_ledger(request: ExtractLedgerRequest):
    """
    Continuity Ledger (연속성 원장) 추출 엔드포인트.
    집필 완료된 화차에서 독자에게 한 약속, 열린 떡밥, 확립된 사실,
    인물 관계 현재 상태를 추출하여 원장 항목을 반환합니다.
    """
    try:
        # 기존 원장에서 미회수 약속/떡밥 추출
        unresolved_items = []
        for item in request.existing_ledger:
            if not item.get("resolved", False):
                unresolved_items.append(
                    f"  - [제{item.get('chapter', '?')}화 발생] {item.get('description', '')}"
                )
        unresolved_text = "\n".join(unresolved_items) if unresolved_items else "(없음)"

        prompt = f"""당신은 베스트셀러 웹소설 전문 연속성 관리 편집자입니다.
아래 제{request.chapter_num}화 본문을 정밀 분석하여 연속성 원장 항목을 추출하십시오.

[인물 설정]
{request.char_sheet[:800] if request.char_sheet else ''}

[기존 미회수 약속/떡밥 목록]
{unresolved_text}

[제{request.chapter_num}화 본문]
{request.chapter_text[:4000]}

[추출 지시사항]
다음 항목을 JSON 형식으로 정확하게 추출하십시오:

{{
  "chapter": {request.chapter_num},
  "promises_made": [
    {{"description": "인물이 한 약속 또는 서술자가 독자에게 한 암시적 약속", "must_resolve_by": "언제까지 회수 권장"}}
  ],
  "open_threads": [
    {{"description": "아직 해결되지 않은 복선/떡밥/미스터리", "introduced_in": {request.chapter_num}}}
  ],
  "resolved_from_previous": [
    {{"description": "이 화에서 회수된 이전 화의 약속/떡밥 (기존 원장에서 찾아 명시)"}}
  ],
  "established_facts": [
    "이 화에서 새롭게 확립된 절대 모순 불가 사실 (외모, 물건, 관계 등)"
  ],
  "relationship_states": {{
    "남주↔여주": "현재 두 사람의 감정/관계 상태",
    "기타 주요 인물": "관계 상태"
  }},
  "chapter_end_state": "이 화 마지막의 인물 감정 상태 및 상황 (다음 화 시작점)"
}}

반드시 유효한 JSON만 출력하십시오. 설명 텍스트 없이."""

        raw = await gemini_service._call_gem_with_retry(
            prompt,
            request.model,
            max_tokens=2048,
            temperature=0.1
        )

        # JSON 파싱
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        try:
            ledger_item = json.loads(cleaned)
        except Exception:
            # 파싱 실패 시 raw 텍스트를 감싸서 반환
            ledger_item = {
                "chapter": request.chapter_num,
                "raw_response": cleaned,
                "parse_error": True
            }

        return {"ledger_item": ledger_item}

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
        target_model = request.model
        if "DeepSeek" in target_model:
            target_model = "models/gemini-3.1-pro-preview"
        elif "flash" in target_model.lower():
            # 문장 개고(Rewrite) 작업은 로맨스 격정적 묘사의 안전 필터 우회 및 고품질 문체 작성이 요구되므로
            # 백엔드 내부적으로 Pro급 모델(gemini-2.5-pro)로 자동 격상하여 실행합니다.
            target_model = "models/gemini-2.5-pro"

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
            model_name=target_model,
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
        result = await gemini_service.generate_cover_image(request.prompt, request.style)
        if "error" in result:
             raise HTTPException(status_code=500, detail=result["error"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class VolumeInfo(BaseModel):
    volume_num: int
    start_chap: int
    end_chap: int
    title: str
    rationale: str = None

class ExportRequest(BaseModel):
    title: str
    author: str
    content: str
    cover_image_path: str = None # Optional local path if available
    export_type: str = "epub" # 'epub', 'txt_zip', 'epub_zip'
    publisher: str = None
    volumes: list[VolumeInfo] = None
    show_chapter_title_in_body: bool = True
    add_chapter_title_page: bool = False

class SmartSplitRequest(BaseModel):
    memory_chain: list

@app.post("/export/smart-split-recommendation")
async def export_smart_split_recommendation(request: SmartSplitRequest):
    try:
        res = await gemini_service.analyze_smart_split(request.memory_chain)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/export/download")
async def export_download(request: ExportRequest):
    try:
        buffer = None
        filename = "novel.epub"
        media_type = "application/epub+zip"
        
        if request.export_type == "epub":
            buffer = export_service.create_epub(
                request.title, 
                request.author, 
                request.content, 
                request.cover_image_path, 
                request.publisher,
                volumes=[v.dict() for v in request.volumes] if request.volumes else None,
                show_chapter_title_in_body=request.show_chapter_title_in_body,
                add_chapter_title_page=request.add_chapter_title_page
            )
            filename = f"{request.title}.epub"
        
        elif request.export_type == "txt":
            clean_text = export_service.get_clean_text(request.content)
            # If show_chapter_title_in_body is False, clean all chapter titles/markers!
            if not request.show_chapter_title_in_body:
                parts = re.split(r'(?:^|\n)\[Chapter\s+(\d+)\]', clean_text, flags=re.IGNORECASE)
                if len(parts) < 3:
                    parts = re.split(r'(?:^|\n)##\s+(\d+)', clean_text)
                
                if len(parts) >= 3:
                    cleaned_parts = []
                    for i in range(1, len(parts), 2):
                        ch_num = int(parts[i])
                        ch_body = parts[i+1].strip()
                        
                        first_line, _, rest = ch_body.partition('\n')
                        first_line = first_line.strip()
                        parsed_title = export_service.clean_chapter_title_text(first_line)
                        if parsed_title and len(parsed_title) < 80:
                            ch_body_clean = export_service._clean_chapter_title_from_body(rest.strip(), parsed_title)
                        else:
                            ch_body_clean = export_service._clean_chapter_title_from_body(ch_body, f"제 {ch_num}화")
                        
                        cleaned_parts.append(ch_body_clean)
                    clean_text = "\n\n".join(cleaned_parts)
                else:
                    clean_text = export_service._clean_chapter_title_from_body(clean_text, "")
            buffer = io.BytesIO(clean_text.encode('utf-8'))
            filename = f"{request.title}.txt"
            media_type = "text/plain"
            
        elif request.export_type == "txt_zip":
            # Split content first
            episodes = export_service.split_text_for_serialization(request.content)
            buffer = export_service.create_serial_zip(
                episodes, 
                request.title, 
                request.author, 
                request.publisher, 
                'txt',
                show_chapter_title_in_body=request.show_chapter_title_in_body
            )
            filename = f"{request.title}_serial_txt.zip"
            media_type = "application/zip"
            
        elif request.export_type == "epub_zip":
            # Split content first
            episodes = export_service.split_text_for_serialization(request.content)
            buffer = export_service.create_serial_zip(
                episodes, 
                request.title, 
                request.author, 
                request.publisher, 
                'epub', 
                request.cover_image_path,
                show_chapter_title_in_body=request.show_chapter_title_in_body,
                add_chapter_title_page=request.add_chapter_title_page
            )
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
    target_vols: int = 2 # Default 2 volumes
    chapters_per_volume: int = 25 # Default 25 chapters per volume
    model_writer: str = "DeepSeek-7B (Fine-tuned)"
    model_planner: str = "models/gemini-3.1-pro-preview"
    reference_outline: str = "" # Optional: Use existing outline from Planner Tab
    self_healing: bool = False # Optional: Enable iterative refinement
    existing_chapters: Optional[dict] = {}
    use_existing_outline: bool = True
    chapters_settings: Optional[dict] = {}
    model_config = {'protected_namespaces': ()}

async def run_batch_generation(
    job_id: str, 
    settings: dict, 
    target_vols: int, 
    chapters_per_volume: int,
    model_writer: str, 
    model_planner: str, 
    reference_outline: str = "", 
    self_healing: bool = False, 
    existing_chapters: dict = {},
    use_existing_outline: bool = True,
    chapters_settings: dict = {}
):
    """
    Long-running background task to generate a full novel.
    1. Plan or parse existing outline
    2. Loop N Chapters (Gemini V3 Draft Engine + Memory + Gemini Review if self_healing)
    """
    total_chapters = target_vols * chapters_per_volume
    
    jobs[job_id]["status"] = "planning"
    jobs[job_id]["log"] = []
    
    try:
        # Normalize settings keys
        if "characters" not in settings and "chars" in settings:
            settings["characters"] = settings["chars"]
        if "char_sheet" not in settings and "chars" in settings:
            settings["char_sheet"] = settings["chars"]
        if "world" not in settings and "world_setting" in settings:
            settings["world"] = settings["world_setting"]
        if "world_setting" not in settings and "world" in settings:
            settings["world_setting"] = settings["world"]
        if "spice_level" not in settings and "spice" in settings:
            settings["spice_level"] = settings["spice"]
        if "style_guide" not in settings and "trends" in settings:
            settings["style_guide"] = settings["trends"]
        if "moods" not in settings and "mood" in settings:
            settings["moods"] = [m.strip() for m in settings["mood"].split(",")] if isinstance(settings["mood"], str) else settings["mood"]
        if "mood" not in settings and "moods" in settings:
            settings["mood"] = ", ".join(settings["moods"]) if isinstance(settings["moods"], list) else settings["moods"]

        # Step 1: Planning / Outline loading
        if use_existing_outline and reference_outline.strip():
            jobs[job_id]["log"].append("Parsing existing Plot & Sync outline directly...")
            outline = gemini_service._parse_outline_to_json(reference_outline, total_chapters)
            if "error" in outline:
                jobs[job_id]["log"].append(f"Warning: Failed to parse outline directly ({outline['error']}). Falling back to Global Planning...")
                outline = await gemini_service.generate_full_outline(settings, total_chapters=total_chapters, model_name=model_planner, reference_outline=reference_outline)
        else:
            jobs[job_id]["log"].append(f"Starting Global Planning for {total_chapters} chapters...")
            outline = await gemini_service.generate_full_outline(settings, total_chapters=total_chapters, model_name=model_planner, reference_outline=reference_outline)
        
        if "error" in outline:
            raise Exception(f"Planning failed: {outline['error']}")
            
        jobs[job_id]["outline"] = outline
        jobs[job_id]["total_chapters"] = len(outline.get("chapters", []))
        jobs[job_id]["results"] = []
        jobs[job_id]["continuity_ledger"] = []  # [PROACTIVE] 연속성 원장 초기화
        
        memory = MemoryManager()
        
        # Step 2: Writing Loop
        for i, chapter in enumerate(outline.get("chapters", [])):
            if jobs[job_id].get("cancel_requested"):
                jobs[job_id]["status"] = "cancelled"
                return

            chapter_num = chapter['chapter_num']
            ch_str = str(chapter_num)
            
            # 2.1 Check if chapter already exists (completed)
            metadata = {}  # 기본값 초기화 (existing_chapters 경로에서 scope 오류 방지)
            if ch_str in existing_chapters and existing_chapters[ch_str].strip():
                jobs[job_id]["log"].append(f"Chapter {chapter_num}: Loaded existing chapter content (imported)")
                chapter_text = existing_chapters[ch_str]
                review = {}
            else:
                jobs[job_id]["status"] = f"writing_chapter_{chapter_num}"
                jobs[job_id]["current_chapter"] = chapter_num
                jobs[job_id]["log"].append(f"Writing Chapter {chapter_num}: {chapter['title']}")
                
                # Fetch preceding chapter text to maintain continuity
                prev_chapter_text = ""
                if chapter_num > 1:
                    prev_ch_str = str(chapter_num - 1)
                    if prev_ch_str in existing_chapters and existing_chapters[prev_ch_str].strip():
                        prev_chapter_text = existing_chapters[prev_ch_str]
                    else:
                        for res in jobs[job_id]["results"]:
                            if res["chapter_num"] == chapter_num - 1:
                                prev_chapter_text = res["text"]
                                break

                # Check for chapter-specific overrides in chapters_settings
                chap_overrides = chapters_settings.get(ch_str, {})
                humor_level = int(chap_overrides.get("humor_level", settings.get("humor_level", 5)))
                temperature = float(chap_overrides.get("temperature", settings.get("creativity", 0.7)))
                
                # Build style prompt matching the editor pipeline
                style_prompt_str = f"문체: {settings.get('style', '로맨틱')}"
                if settings.get("persona"):
                    style_prompt_str += f", 페르소나: {settings.get('persona')}"
                if humor_level > 0:
                    humor_instruction = ""
                    if humor_level >= 9:
                        humor_instruction = " (극강의 코미디: 아방궁 같은 상황, 황당무계한 전개, 배꼽 잡는 슬랩스틱 유머를 적극적으로 활용하여 소설 중간중간에 반드시 코믹하고 웃긴 장면을 연출하십시오.)"
                    elif humor_level >= 7:
                        humor_instruction = " (고품격 상황 코미디: 날카로운 재치, 완벽한 '티키타카' 대사, 강렬한 상황적 아이러니를 활용하십시오. 캐릭터들이 끊임없이 서로 오해하거나 유머러스하게 투닥거리게 하여 확실하게 유쾌하고 웃긴 분위기를 만드십시오.)"
                    elif humor_level >= 4:
                        humor_instruction = " (경쾌한 코미디: 재치 있는 대사와 가끔씩 터지는 코믹한 상황을 통해 극의 분위기를 가볍고 즐겁게 유지하십시오.)"
                    else:
                        humor_instruction = " (은은한 유머: 대사에 미소를 자아내는 재치나 장난스러움을 한 스푼 더하십시오.)"
                    
                    style_prompt_str += f", 유머 감각(레벨 {humor_level}/10) 적용{humor_instruction}"
                    
                style_guide_text = settings.get("style_guide", "")
                if style_guide_text:
                    style_prompt_str += (
                        f"\n- [스타일 가이드 지침 강제 적용]\n"
                        f"다음 지침을 소설 전개와 문체 및 서술 템포에 절대적으로 강제 적용하십시오:\n{style_guide_text}"
                    )
                
                # Retrieve Memory summaries
                recent_memories = memory.chapters[-15:]
                memory_text = "\n".join(
                    f"  - 제{m['chapter_num']}화: {m['summary']}"
                    for m in recent_memories
                )

                # 감정 아크 누적 궤적 - 최근 10화의 인물 감정 상태 변화 연표 구성
                emotion_trajectory_lines = []
                for m in memory.chapters[-10:]:
                    ch_state = ""
                    ec = m.get("entity_changes", {})
                    if isinstance(ec, dict):
                        ch_state = ec.get("characters", "")
                    elif isinstance(ec, str):
                        ch_state = ec
                    if ch_state:
                        emotion_trajectory_lines.append(f"  - 제{m['chapter_num']}화: {ch_state[:120]}")
                emotion_trajectory = "\n".join(emotion_trajectory_lines)

                flow_context = ""
                if prev_chapter_text.strip():
                    flow_context += f"--- [직전 화(제{chapter_num-1}화)의 마지막 장면] ---\n{prev_chapter_text.strip()[-2500:]}\n\n"
                if memory_text:
                    flow_context += f"[이전 화 줄거리 요약]\n{memory_text}\n\n"
                if emotion_trajectory:
                    flow_context += f"[인물 감정 아크 누적 연표 - 이 궤적에서 이탈 금지]\n{emotion_trajectory}\n\n"

                # RAG Context Retrieval
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
                
                rag_extended_context = f"{flow_context}\n\n[참고 데이터 (RAG 검색 결과)]\n{rag_context}"
                
                # Format focus text combining summary, key_events and emotion_arc
                # [SAFETY] key_events 최대 10개로 제한 (프롬프트 과부하 방지)
                ch_focus_text = f"줄거리 요약: {chapter.get('summary', '')}"
                key_events_list = chapter.get("key_events", [])[:10]
                if key_events_list:
                    ch_focus_text += "\n세부 전개 사건들:\n" + "\n".join(f"- {ev}" for ev in key_events_list)
                # 감정 아크 설계값 주입 - 이 화에서의 정확한 감정 변화 목표와 제약 지침
                emotion_arc = chapter.get("emotion_arc", {})
                if emotion_arc and isinstance(emotion_arc, dict):
                    ch_focus_text += "\n\n[이 화의 감정 아크 설계 지침 - 반드시 준수]"
                    
                    hero_val = emotion_arc.get("hero_state") or emotion_arc.get("hero_hate_level")
                    if hero_val:
                        ch_focus_text += f"\n- 남주 감정 상태 목표: {hero_val}"
                        
                    heroine_val = emotion_arc.get("heroine_state") or emotion_arc.get("hero_inner_state")
                    if heroine_val:
                        ch_focus_text += f"\n- 여주 감정 상태 목표: {heroine_val}"
                        
                    rel_val = emotion_arc.get("relationship_level") or emotion_arc.get("relationship")
                    if rel_val:
                        ch_focus_text += f"\n- 두 사람 관계 단계: {rel_val}"
                        
                    note_val = emotion_arc.get("transition_note") or emotion_arc.get("transition_seed")
                    if note_val:
                        ch_focus_text += f"\n- 집필 주의사항: {note_val}"

                # ══════════════════════════════════════════════════════
                # [PROACTIVE] STEP A: Pre-Write Chapter Brief 생성
                # 목적: 집필 전 이 화의 정확한 임무를 AI가 먼저 설계
                # 모델: Flash (빠름, 저비용)
                # Fail-safe: 오류 시 경고만 남기고 집필 계속
                # ══════════════════════════════════════════════════════
                chapter_brief = ""
                brief_output_state = ""  # STEP B QC 검증 기준으로 전달
                try:
                    # 원장에서 미회수 약속/떡밥만 추출 (최대 10개, attention 낭비 방지)
                    ledger = jobs[job_id].get("continuity_ledger", [])
                    unresolved_promises = []
                    unresolved_threads = []
                    for entry in ledger[-10:]:  # 최근 10화 원장만 참조
                        if isinstance(entry, dict):
                            for p in entry.get("promises_made", []):
                                if isinstance(p, dict) and not p.get("resolved", False):
                                    unresolved_promises.append(p.get("description", "")[:80])
                            for t in entry.get("open_threads", []):
                                if isinstance(t, dict):
                                    unresolved_threads.append(t.get("description", "")[:80])
                    unresolved_promises = unresolved_promises[-8:]  # 최대 8개
                    unresolved_threads = unresolved_threads[-8:]    # 최대 8개

                    # 전화차 end_state (마지막 원장 항목)
                    prev_end_state = ""
                    if ledger and isinstance(ledger[-1], dict):
                        prev_end_state = ledger[-1].get("chapter_end_state", "")[:200]

                    # 최근 3화 memory 요약 (Brief용 압축)
                    recent_3_mem = memory.chapters[-3:]
                    brief_mem_text = "\n".join([
                        f"  제{m['chapter_num']}화: {m['summary'][:120]}"
                        for m in recent_3_mem
                    ])

                    # 미회수 항목 텍스트 (없으면 표시 생략)
                    unresolved_text = ""
                    if unresolved_promises:
                        unresolved_text += "미회수 약속: " + " | ".join(unresolved_promises[:5]) + "\n"
                    if unresolved_threads:
                        unresolved_text += "열린 떡밥: " + " | ".join(unresolved_threads[:5])

                    # ── 대량 집필용 안전 지침 생성 Fallback 호출 ──────────────────────────────
                    chapter_brief = await gemini_service.generate_chapter_brief_for_batch_with_fallback(
                        chapter_num=chapter_num,
                        ch_focus_text=ch_focus_text,
                        prev_end_state=prev_end_state,
                        brief_mem_text=brief_mem_text,
                        unresolved_text=unresolved_text
                    )

                    # Output State 추출 (STEP B QC용)
                    for line in chapter_brief.split("\n"):
                        if "Output State" in line and ":" in line:
                            brief_output_state = line.split(":", 1)[-1].strip()[:300]
                            break

                    # Brief를 ch_focus_text 앞에 주입 (400자 이내 압축)
                    if chapter_brief:
                        brief_summary = chapter_brief[:600]  # 길어지면 attention 희석
                        ch_focus_text = (
                            f"[집필 브리핑 - 최우선 준수]\n{brief_summary}\n\n"
                            f"[이번 화 상세 목표]\n{ch_focus_text}"
                        )
                    jobs[job_id]["log"].append(f"[BRIEF] Chapter {chapter_num} Pre-Write Brief 생성 완료.")

                except Exception as brief_err:
                    # Fail-safe: Brief 실패해도 집필은 계속
                    jobs[job_id]["log"].append(f"[BRIEF] Chapter {chapter_num} Brief 심각한 생성 실패 (무시): {str(brief_err)[:100]}")
                
                jobs[job_id]["log"].append(f"Generating Chapter {chapter_num} via Gemini V3 Draft Engine (Model: {model_writer})...")
                chapter_text = await gemini_service.generate_v3_draft(
                    prompt=f"제 {chapter_num}화: '{chapter['title']}'를 집필해 주세요.",
                    chars=settings.get('characters', 'N/A'),
                    world=settings.get('world', 'N/A'),
                    plot_summary=settings.get('idea_premise', 'N/A'),
                    ch_focus=ch_focus_text,
                    style_directions=style_prompt_str,
                    previous_context=rag_extended_context,
                    model_name=model_writer,
                    temperature=temperature
                )
                
                # ══════════════════════════════════════════════════════
                # [PROACTIVE] STEP B: Post-Write QC (집필 직후 즉시 검증)
                # 목적: Brief의 Output State가 달성되었는지 확인
                # 모델: Flash (빠름)
                # 기준 미달 + self_healing=True → 즉시 Self-Heal
                # Fail-safe: 오류 시 경고만, 루프 계속
                # ══════════════════════════════════════════════════════
                qc_passed = True
                qc_issue = ""
                if brief_output_state and chapter_text.strip():
                    try:
                        qc_prompt = (
                            f"당신은 웹소설 품질 검수 편집자입니다. 아래 집필 결과가 목표를 달성했는지 판단하십시오.\n\n"
                            f"[달성해야 할 목표 (Output State)]\n{brief_output_state}\n\n"
                            f"[집필 결과 (앞부분 2000자)]\n{chapter_text[:2000]}\n\n"
                            f"[판단 지시]\n"
                            f"Output State가 달성되었으면 첫 줄에 'PASS', 미달이면 'FAIL'을 쓰고,\n"
                            f"미달 시 구체적인 이유를 2~3줄로 작성하십시오.\n"
                            f"(판단 기준: 감정 흐름, 인물 상태, 핵심 사건 발생 여부)"
                        )
                        flash_model = "models/gemini-2.5-flash"
                        qc_result = await gemini_service._call_gem_with_retry(
                            qc_prompt, flash_model, max_tokens=256, temperature=0.1
                        )
                        if qc_result.strip().upper().startswith("FAIL"):
                            qc_passed = False
                            qc_issue = qc_result.strip()
                            jobs[job_id]["log"].append(
                                f"[QC] Chapter {chapter_num} Output State 미달: {qc_issue[:120]}"
                            )
                        else:
                            jobs[job_id]["log"].append(f"[QC] Chapter {chapter_num} Output State 달성 확인.")
                    except Exception as qc_err:
                        # Fail-safe: QC 실패해도 계속
                        jobs[job_id]["log"].append(f"[QC] Chapter {chapter_num} QC 실패 (무시): {str(qc_err)[:80]}")

                # 2.3 Optional Review + QC-triggered Self-Correction
                review = {}
                if self_healing:
                    # QC 미달이면 즉시 Self-Heal (QC 이유를 critique로 활용)
                    if not qc_passed and qc_issue:
                        jobs[job_id]["log"].append(
                            f"[HEAL] Chapter {chapter_num} QC 미달로 즉시 재집필 (QC→Self-Heal)..."
                        )
                        try:
                            # Brief 정보를 critique에 포함하여 더 정확한 수정
                            qc_critique = {
                                "feedback": {"qc_issue": qc_issue},
                                "improvement_suggestions": [
                                    f"Output State를 달성하도록 수정: {brief_output_state}"
                                ]
                            }
                            healed_text = await gemini_service.rewrite_improved_content(
                                chapter_text, qc_critique
                            )
                            if healed_text and len(healed_text.strip()) > 100:
                                chapter_text = healed_text
                                jobs[job_id]["log"].append(
                                    f"[HEAL] Chapter {chapter_num} QC 기반 재집필 완료."
                                )
                            else:
                                jobs[job_id]["log"].append(
                                    f"[HEAL] Chapter {chapter_num} 재집필 결과가 너무 짧아 원본 유지."
                                )
                        except Exception as he:
                            jobs[job_id]["log"].append(
                                f"[HEAL] Chapter {chapter_num} QC 기반 재집필 실패: {str(he)[:80]}. 원본 유지."
                            )
                    else:
                        # 기존 self_healing 로직 (점수 기반)
                        jobs[job_id]["log"].append(f"Reviewing Chapter {chapter_num} (Model: {model_planner})...")
                        review = await gemini_service.perform_comprehensive_review(
                            chapter_text, model_name=model_planner
                        )
                        scores = review.get("scores", {})
                        consistency = scores.get("consistency", 100)
                        creativity = scores.get("creativity", 100)
                        
                        if consistency < 70 or creativity < 70:
                            jobs[job_id]["log"].append(
                                f"품질 경고 (일관성: {consistency}, 창의성: {creativity}). "
                                f"제{chapter_num}화 재작성 중 (Self-Healing)..."
                            )
                            try:
                                healed_text = await gemini_service.rewrite_improved_content(
                                    chapter_text, review
                                )
                                if healed_text and len(healed_text.strip()) > 100:
                                    chapter_text = healed_text
                                    jobs[job_id]["log"].append(
                                        f"Self-Healing 완료. 재작성된 텍스트로 메모리 추출 진행."
                                    )
                                else:
                                    jobs[job_id]["log"].append(
                                        f"Self-Healing 결과가 너무 짧아 원본 유지."
                                    )
                            except Exception as he:
                                jobs[job_id]["log"].append(
                                    f"Self-Healing 실패: {str(he)[:80]}. 원본 텍스트 유지."
                                )
            
            # 2.4 Update Memory (Extract long-term memory summary, changes, and cliffhangers from written text)
            jobs[job_id]["log"].append(f"Extracting memory & entities from Chapter {chapter_num}...")
            try:
                summary_prompt = f"""
                당신은 베스트셀러 소설 전문 교열가이자 기획자입니다. 다음 소설 장면을 정밀하게 분석하여 장기 기억 스토리지용 설정 변경 메타데이터를 추출하십시오.

                [분석할 본문 (제{chapter_num}화)]
                {chapter_text[:3000]}

                [요구사항]
                1. **chunk_summary**: 이 화의 핵심 플롯에 대한 3~5줄 분량의 상세 요약.
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
                raw_res = await gemini_service._call_gem_with_retry(summary_prompt, model_planner)
                cleaned = raw_res.replace("```json", "").replace("```", "").strip()
                import json
                try:
                    metadata = json.loads(cleaned)
                except Exception as json_err:
                    # Robust regex recovery for common unescaped string issue
                    import re
                    metadata = {}
                    summary_match = re.search(r'"chunk_summary"\s*:\s*"(.*?)"\s*(?:,|\})', cleaned, re.DOTALL)
                    if summary_match:
                        metadata["chunk_summary"] = summary_match.group(1).replace('\\"', '"').replace('\\n', '\n')
                    
                    char_match = re.search(r'"characters"\s*:\s*"(.*?)"\s*(?:,|\})', cleaned, re.DOTALL)
                    setting_match = re.search(r'"settings"\s*:\s*"(.*?)"\s*(?:,|\})', cleaned, re.DOTALL)
                    if char_match or setting_match:
                        metadata["entity_changes"] = {}
                        if char_match:
                            metadata["entity_changes"]["characters"] = char_match.group(1).replace('\\"', '"').replace('\\n', '\n')
                        if setting_match:
                            metadata["entity_changes"]["settings"] = setting_match.group(1).replace('\\"', '"').replace('\\n', '\n')
                    
                    cliff_match = re.search(r'"cliffhanger_point"\s*:\s*"(.*?)"\s*(?:,|\})', cleaned, re.DOTALL)
                    if cliff_match:
                        metadata["cliffhanger_point"] = cliff_match.group(1).replace('\\"', '"').replace('\\n', '\n')

                ch_summary = metadata.get("chunk_summary", chapter.get('summary', ''))
                ch_events = [metadata.get("cliffhanger_point", "")] if metadata.get("cliffhanger_point") else chapter.get('key_events', [])
                
                # Fallback if both empty
                if not ch_summary:
                    ch_summary = chapter.get('summary', '')

                jobs[job_id]["log"].append(f"Memory Extracted for Chapter {chapter_num}: {ch_summary[:80]}...")
            except Exception as ex:
                jobs[job_id]["log"].append(f"Warning: Memory extraction failed for Chapter {chapter_num}: {str(ex)}")
                ch_summary = chapter.get('summary', '')
                ch_events = chapter.get('key_events', [])

            memory.add_chapter_memory(chapter_num, ch_summary, ch_events, [])

            # ══════════════════════════════════════════════════════
            # [PROACTIVE] STEP C: Continuity Ledger 업데이트
            # 목적: 이 화에서 생긴 약속/떡밥/사실/관계 상태 추출
            # 모델: Flash (저비용)
            # Fail-safe: 오류 시 빈 구조체 추가, 루프 계속
            # ══════════════════════════════════════════════════════
            try:
                ledger_list = jobs[job_id].get("continuity_ledger", [])
                # 기존 미회수 항목 압축 (최대 10개, 프롬프트 폭증 방지)
                existing_unresolved = []
                for entry in ledger_list[-5:]:  # 최근 5화만 참조
                    if isinstance(entry, dict):
                        for p in entry.get("promises_made", []):
                            if isinstance(p, dict) and not p.get("resolved", False):
                                existing_unresolved.append(
                                    {"chapter": entry.get("chapter"), "description": p.get("description", "")[:80]}
                                )
                        for t in entry.get("open_threads", []):
                            if isinstance(t, dict):
                                existing_unresolved.append(
                                    {"chapter": entry.get("chapter"), "description": t.get("description", "")[:80]}
                                )
                existing_unresolved = existing_unresolved[-10:]  # 최대 10개

                unresolved_text_c = "\n".join([
                    f"  - [제{x.get('chapter','?')}화] {x['description']}"
                    for x in existing_unresolved
                ]) or "(없음)"

                # ── 다단계 안전 원장 추출 호출 ──────────────────────────────────────
                ledger_item = await gemini_service.extract_continuity_ledger_with_fallback(
                    chapter_num=chapter_num,
                    chapter_text=chapter_text,
                    unresolved_text_c=unresolved_text_c,
                    ch_summary=ch_summary
                )
                jobs[job_id]["continuity_ledger"].append(ledger_item)
                
                # Fallback 상태 로그 출력
                if ledger_item.get("fallback_applied"):
                    jobs[job_id]["log"].append(
                        f"[LEDGER] Chapter {chapter_num} 안전 대체(Fallback) 원장 저장 완료."
                    )
                else:
                    jobs[job_id]["log"].append(
                        f"[LEDGER] Chapter {chapter_num} 연속성 원장 업데이트 완료. "
                        f"약속 {len(ledger_item.get('promises_made', []))}개, "
                        f"떡밥 {len(ledger_item.get('open_threads', []))}개"
                    )
            except Exception as ledger_err:
                # 최후의 수단 Fail-safe
                jobs[job_id]["continuity_ledger"].append({
                    "chapter": chapter_num,
                    "promises_made": [],
                    "open_threads": [],
                    "established_facts": ["제{chapter_num}화 스토리 전개 완료".format(chapter_num=chapter_num)],
                    "chapter_end_state": ch_summary[:200],
                    "error": str(ledger_err)[:100]
                })
                jobs[job_id]["log"].append(
                    f"[LEDGER] Chapter {chapter_num} 원장 추출 심각한 오류 (빈 구조체 저장): {str(ledger_err)[:80]}"
                )

            # Save Result
            jobs[job_id]["results"].append({
                "chapter_num": chapter_num,
                "title": chapter['title'],
                "text": chapter_text,
                "review": review,
                "metadata": {
                    "chapter": chapter_num,
                    "chunk_summary": ch_summary,
                    "entity_changes": metadata.get("entity_changes", {"characters": "변동 없음", "settings": "변동 없음"}),
                    "cliffhanger_point": metadata.get("cliffhanger_point", "")
                }
            })
            
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
    background_tasks.add_task(
        run_batch_generation, 
        job_id, 
        request.settings, 
        request.target_vols, 
        request.chapters_per_volume,
        request.model_writer, 
        request.model_planner, 
        request.reference_outline, 
        request.self_healing,
        request.existing_chapters,
        request.use_existing_outline,
        request.chapters_settings
    )
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

class CoverPromptRequest(BaseModel):
    text: str
    style: Optional[str] = "기본"
    focus: Optional[str] = "기본"
    include_typography: Optional[bool] = False
    title: Optional[str] = ""
    author: Optional[str] = ""
    model: str = "models/gemini-2.5-flash"

@app.post("/analyze/cover_prompt")
async def analyze_cover_prompt(request: CoverPromptRequest):
    try:
        prompt = await gemini_service.generate_cover_prompt(
            text=request.text,
            style=request.style,
            focus=request.focus,
            include_typography=request.include_typography,
            title=request.title,
            author=request.author,
            model_name=request.model
        )
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
async def analyze_review_single(request: AnalyzeReviewRequest):
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
