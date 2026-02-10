# -*- coding: utf-8 -*-
"""Romance AI Streamlit Frontend

This file implements the Streamlit UI, user authentication, per‑user project
persistence, and all interactive features (idea generator, story writer, etc.).
The changes focus on three user‑experience issues:
1. **Login persistence** – after a successful login the URL now contains
   `?user=<username>` using `st.experimental_set_query_params`. The query
   parameters survive a page refresh.
2. **Automatic project loading** – when the app starts (or after a refresh) it
   automatically opens the most‑recently‑modified project for the logged‑in user.
   The project can also be forced via a `project` query parameter.
3. **Visibility of storage location** – the absolute path of the user’s
   `story_data/<username>` directory is shown in the sidebar, and a button
   allows copying it to the clipboard.
"""

import os
import json
import glob
import hashlib
import base64
from io import BytesIO
from datetime import datetime
import re

import streamlit as st
import requests
from dotenv import load_dotenv
from docx import Document
import pandas as pd

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
load_dotenv()
# Environment Configuration
ENV = os.getenv("ENV", "dev") # 'dev' or 'prod'

if ENV == "prod":
    BACKEND_URL = os.getenv("BACKEND_URL", "https://romance-ai-backend-46410417920.asia-southeast1.run.app")
    print(f"Server starting in [PRODUCTION] mode. Backend: {BACKEND_URL}")
else:
    BACKEND_URL = "http://localhost:8000"
    print(f"Server starting in [DEVELOPMENT] mode. Backend: {BACKEND_URL}")

# ---------------------------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------------------------
USER_DB_FILE = "users.json"
BASE_DATA_DIR = "story_data"


def hash_password(password: str) -> str:
    """Return a SHA256 hash of *password* (hex string)."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def generate_session_token(username: str, password_hash: str) -> str:
    """Generate a simple stateless session token."""
    return hashlib.sha256(f"{username}{password_hash}".encode("utf-8")).hexdigest()


def load_users() -> dict:
    if os.path.exists(USER_DB_FILE):
        try:
            with open(USER_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_users(users: dict) -> None:
    try:
        with open(USER_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"Save User Error: {e}")


def login_system() -> None:
    """Render the login / registration UI.

    Successful login stores the username in ``st.session_state.user`` and also
    updates the URL query parameters so that a page reload keeps the user logged
    in.
    """
    st.title("🔒 Romance AI: Login / Register")
    col1, col2 = st.columns([1, 1])
    users = load_users()

    # ---------- Login ----------
    with col1:
        st.subheader("Login")
        with st.form("login_form"):
            username = st.text_input("Username", key="login_user")
            password = st.text_input("Password", type="password", key="login_pass")
            submitted = st.form_submit_button("Login")

            if submitted:
                if not re.match(r'^[a-zA-Z0-9]+$', username):
                    st.error("Access denied: Please use an alphanumeric ID (English/Numbers only).")
                elif username in users and users[username] == hash_password(password):
                    st.session_state.user = username
                    # Persist via query params with validation token
                    token = generate_session_token(username, users[username])
                    st.query_params["user"] = username
                    st.query_params["token"] = token
                    st.success(f"Welcome back, {username}!")
                    st.rerun()
                else:
                    st.error("Invalid username or password.")

    # ---------- Register ----------
    with col2:
        st.subheader("Register")
        with st.form("register_form"):
            reg_user = st.text_input("New Username", key="reg_user")
            reg_pass = st.text_input("New Password", type="password", key="reg_pass")
            submitted = st.form_submit_button("Register")
            if submitted:
                if not re.match(r'^[a-zA-Z0-9]+$', reg_user):
                     st.error("Username must contain only English letters and numbers.")
                elif reg_user in users:
                    st.error("Username already exists.")
                elif not reg_user or not reg_pass:
                    st.error("Please fill in both fields.")
                else:
                    users[reg_user] = hash_password(reg_pass)
                    save_users(users)
                    st.success("Registration successful! Please login.")

# ---------------------------------------------------------------------------
# Project persistence helpers
# ---------------------------------------------------------------------------

def get_user_project_dir(username: str) -> str:
    user_dir = os.path.join(BASE_DATA_DIR, username)
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    return user_dir


def list_projects(username: str) -> list:
    """Return a list of project names (without extension)."""
    user_dir = get_user_project_dir(username)
    files = glob.glob(os.path.join(user_dir, "*.json"))
    return [os.path.basename(f).replace(".json", "") for f in files]


def list_projects_sorted(username: str) -> list:
    """Return projects sorted by modification time (newest first)."""
    user_dir = get_user_project_dir(username)
    files = glob.glob(os.path.join(user_dir, "*.json"))
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return [os.path.basename(p).replace(".json", "") for p in files]


def load_project(username: str, project_name: str) -> dict:
    user_dir = get_user_project_dir(username)
    path = os.path.join(user_dir, f"{project_name}.json")
    if os.path.exists(path):
        try:
            os.utime(path, None)  # Touch file to update mtime for "last active" sorting
        except Exception:
            pass
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_project(username: str, project_name: str, data: dict) -> None:
    user_dir = get_user_project_dir(username)
    path = os.path.join(user_dir, f"{project_name}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"Failed to auto-save project: {e}")

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def create_download_file(text: str, format: str = "txt"):
    if format == "txt":
        return text.encode("utf-8")
    elif format == "docx":
        doc = Document()
        doc.add_heading('Romance Novel', 0)
        for para in text.split('\n'):
            if para.strip():
                doc.add_paragraph(para.strip())
        bio = BytesIO()
        doc.save(bio)
        bio.seek(0)
        return bio.getvalue()
    else:
        return text.encode("utf-8")


def generate_story(prompt: str, temperature: float, model: str, style: str, persona: str, humor_level: int = 0) -> str:
    current = st.session_state.get("current_story", "")
    chars = st.session_state.get("char_sheet", "")
    world = st.session_state.get("world_setting", "")
    recent_memory = "\n".join(st.session_state.get("memory_chain", [])[-3:]) if st.session_state.get("memory_chain") else "No previous chapter memory."
    
    # Humor Logic
    humor_instruction = ""
    if humor_level >= 9:
        humor_instruction = "7. **Extreme Comedy**: Absurdist humor, chaotic situations, and laugh-out-loud slapstick."
    elif humor_level >= 7:
        humor_instruction = "7. **High-End Situational Comedy**: Sharp wit, perfect 'Tiki-Taka' banter, and strong situational irony. Characters should constantly bicker or misunderstand each other in funny ways."
    elif humor_level >= 4:
        humor_instruction = "7. **Light Comedy**: Use witty dialogue and occasional funny situations to keep the tone light."
    elif humor_level >= 1:
        humor_instruction = "7. **Subtle Wit**: Add a touch of humor or playfulness to the dialogue."
    
    full_prompt = f"""
    [Role]
    You are a best-selling Romance Novelist. Write the next scene with high emotional impact.

    [Style Guide]
    - **Tone**: {style}
    - **Persona**: {persona if persona else "Professional, Engaging"}
    - **Rule #1**: Show, Don't Tell. (e.g., Instead of "he was sad", describe his tears or trembling hands).

    [Story Context]
    - Characters: {chars}
    - World: {world}
    - Previous Context: {recent_memory}
    - Recent Story: {current[-3000:] if current else "Start of story."}
    - Plot Plan: {st.session_state.get('plot_outline', 'None')}

    [User Request]
    "{prompt}"

    [Writing Instructions]
    1. **Show, Don't Tell**: Do not label emotions (e.g., "he was sad"). Describe the physical manifestation (e.g., "his throat tightened," "he stared at the cold coffee").
    2. **Cinematic Depth**: Frame the scene like a movie. Use lighting, silence, and ambient sound to build tension.
    3. **Psychological Nuance**: Explore the character's internal contradictions. (e.g., He wants to hate her, but his eyes follow her).
    4. **Originality**: Avoid clichés. If the situation is typical, twist the reaction or outcome.
    5. **Pacing**: Slow down during key emotional realizations.
    6. **Humor Level ({humor_level}/10)**: {humor_instruction}

    Write the next scene in **Natural, High-Quality Korean (Web-novel style)**.
    Focus on **immersion** and **emotional resonance**.
    """
    try:
        response = requests.post(
            f"{BACKEND_URL}/generate/romance",
            json={"prompt": full_prompt, "max_length": 1500, "temperature": temperature, "model": model},
        )
        if response.status_code == 200:
            return response.json().get("generated_text", "")
        else:
            return f"\n[Error: {response.text}]"
    except Exception as e:
        return f"\n[Error connecting to backend: {e}]"

# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Romance AI Creator", page_icon="💖", layout="wide")

    # ---------- Auto‑login via query params ----------
    if "user" not in st.session_state:
        st.session_state.user = None
    
    # Initialize Session State Variables
    if "batch_job_id" not in st.session_state:
        st.session_state.batch_job_id = None
    if "auto_merge_trigger" not in st.session_state:
        st.session_state.auto_merge_trigger = None
    if "auto_merge_enabled" not in st.session_state:
        st.session_state.auto_merge_enabled = False
    if not st.session_state.user:
        qp = st.query_params
        if "user" in qp and "token" in qp:
            saved_user = qp["user"].strip()
            # Enforce clean usernames even for auto-login
            if not re.match(r'^[a-zA-Z0-9]+$', saved_user):
                st.session_state.user = None
            else:
                saved_token = qp["token"]
                users = load_users()
                if saved_user in users:
                    expected_token = generate_session_token(saved_user, users[saved_user])
                    if saved_token == expected_token:
                        st.session_state.user = saved_user
                    else:
                        st.warning("Previous session expired or invalid. Please login again.")
                else:
                     # Only show error if we expected to find the user
                     st.warning("User record not found. Please login again.")
    if not st.session_state.user:
        login_system()
        return

    username = st.session_state.user

    # [Persistence Fix] Ensure URL always has the token while logged in
    # This prevents the token from disappearing and breaking the session on refresh
    users_lookup = load_users()
    if username in users_lookup:
        valid_token = generate_session_token(username, users_lookup[username])
        qp = st.query_params
        if qp.get("user") != username or qp.get("token") != valid_token:
            st.query_params["user"] = username
            st.query_params["token"] = valid_token
            # No rerun needed here, it updates the URL for the next reload

    # ---------- Sidebar – logout & project manager ----------
    with st.sidebar:
        st.write(f"👤 **{username}**")
        if st.button("Logout"):
            st.session_state.user = None
            # clear all query params (including project)
            st.query_params.clear()
            st.rerun()
        st.title("🗂️ Project Manager")



        # Load projects sorted by newest first
        existing_projects = list_projects_sorted(username)

        # If a project is supplied via URL, honour it (and verify it exists)
        qp = st.query_params
        if "project" in qp and qp["project"] in existing_projects:
            st.session_state.current_project = qp["project"]
        elif "current_project" not in st.session_state:
            # default to most recent project if any
            st.session_state.current_project = existing_projects[0] if existing_projects else None

        # Project selection UI
        mode = st.radio("Project Action", ["Load Existing", "Create New"], horizontal=True)
        if mode == "Load Existing":
            if existing_projects:
                sel = st.selectbox("Select Project", existing_projects, index=0 if not st.session_state.current_project else existing_projects.index(st.session_state.current_project))
                if st.button("Load"):
                    st.session_state.current_project = sel
                    # update URL so refresh keeps this project
                    # update URL so refresh keeps this project
                    # Must preserve token
                    token = st.query_params.get("token", "")
                    st.query_params["user"] = username
                    st.query_params["project"] = sel
                    if token:
                        st.query_params["token"] = token
                    st.rerun()
            else:
                st.warning("No projects found. Create one!")
        else:  # Create New
            new_name = st.text_input("New Project Name", placeholder="My_Romance_Novel_1")
            if new_name and st.button("Create & Switch"):
                clean = "".join(ch for ch in new_name if ch.isalnum() or ch in "_- ").strip().replace(" ", "_")
                # Create empty project file immediately so it persists
                save_project(username, clean, {
                    "current_story": "",
                    "char_sheet": "",
                    "world_setting": "",
                    "memory_chain": [],
                    "critique": None,
                    "idea_suggestion": "",
                    "custom_persona_input": ""
                })
                st.session_state.current_project = clean
                st.query_params["user"] = username
                st.query_params["project"] = clean
                # Must preserve token
                token = st.query_params.get("token", "")
                if token:
                    st.query_params["token"] = token
                st.rerun()



    # If no project selected, show welcome screen
    if not st.session_state.get("current_project"):
        st.title("Welcome! Please create or load a project to start.")
        return

    # ---------- Load project data (once per project change) ----------
    if "loaded_project" not in st.session_state or st.session_state.loaded_project != st.session_state.current_project:
        data = load_project(username, st.session_state.current_project)
        st.session_state.current_story = data.get("current_story", "")
        st.session_state.char_sheet = data.get("char_sheet", "")
        st.session_state.world_setting = data.get("world_setting", "")
        st.session_state.memory_chain = data.get("memory_chain", [])
        st.session_state.critique = data.get("critique")
        st.session_state.idea_suggestion = data.get("idea_suggestion", "")
        st.session_state.custom_persona_input = data.get("custom_persona_input", "")
        # Persist Settings
        st.session_state.setting_temperature = data.get("setting_temperature", 0.7)
        st.session_state.setting_model = data.get("setting_model", "gemini-2.5-flash-preview-09-2025")
        st.session_state.setting_style = data.get("setting_style", "기본")
        st.session_state.setting_preset = data.get("setting_preset", "Direct Input")
        st.session_state.setting_target_vols = data.get("setting_target_vols", 1)
        st.session_state.setting_target_vols = data.get("setting_target_vols", 1)
        st.session_state.setting_humor = data.get("setting_humor", 0) # Default 0
        st.session_state.last_prompt = data.get("last_prompt", "")

        # Persist Idea Generator
        st.session_state.ig_genre = data.get("ig_genre", "전통로맨스")
        st.session_state.ig_spice = data.get("ig_spice", "19금(없음)")
        st.session_state.ig_trends = data.get("ig_trends", True)
        st.session_state.ig_moods = data.get("ig_moods", [])
        st.session_state.ig_male = data.get("ig_male", [])
        st.session_state.ig_female = data.get("ig_female", [])
        st.session_state.ig_arc = data.get("ig_arc", "")

        st.session_state.loaded_project = st.session_state.current_project

    # ---------- Auto‑save helper ----------
    def auto_save() -> None:
        payload = {
            "current_story": st.session_state.get("current_story", ""),
            "char_sheet": st.session_state.get("char_sheet", ""),
            "world_setting": st.session_state.get("world_setting", ""),
            "memory_chain": st.session_state.get("memory_chain", []),
            "critique": st.session_state.get("critique"),
            "idea_suggestion": st.session_state.get("idea_suggestion", ""),
            "custom_persona_input": st.session_state.get("custom_persona_input", ""),
            # Persist Settings
            "setting_temperature": st.session_state.get("setting_temperature", 0.7),
            "setting_model": st.session_state.get("setting_model", "gemini-2.5-flash-preview-09-2025"),
            "setting_style": st.session_state.get("setting_style", "기본"),
            "setting_preset": st.session_state.get("setting_preset", "Direct Input"),
            "setting_target_vols": st.session_state.get("setting_target_vols", 1),
            "setting_humor": st.session_state.get("setting_humor", 0),
            "last_prompt": st.session_state.get("last_prompt", ""),
            # Persist Idea Generator
            "ig_genre": st.session_state.get("ig_genre", "전통로맨스"),
            "ig_spice": st.session_state.get("ig_spice", "19금(없음)"),
            "ig_trends": st.session_state.get("ig_trends", True),
            "ig_moods": st.session_state.get("ig_moods", []),
            "ig_male": st.session_state.get("ig_male", []),
            "ig_female": st.session_state.get("ig_female", []),
            "ig_arc": st.session_state.get("ig_arc", ""),
            "plot_outline": st.session_state.get("plot_outline", ""),
        }
        save_project(username, st.session_state.current_project, payload)

    # ---------- Settings sidebar ----------
    with st.sidebar:
        st.title("Settings")
        temperature = st.slider("Creativity (Temperature)", 0.1, 1.0, key="setting_temperature", on_change=auto_save)
        humor_level = st.slider("Humor Level (유머 감각)", 0, 10, key="setting_humor", help="0: Serious, 10: Hilarious/Slapstick", on_change=auto_save)
        
        model_options = [
            "gemini-2.5-flash-preview-09-2025",
            "gemini-3-pro-preview",
            "gemini-1.5-flash",
            "gemini-2.0-flash-exp",
            "DeepSeek-7B (Fine-tuned)",
        ]
        selected_model = st.selectbox("AI Version", model_options, key="setting_model", on_change=auto_save)
        st.markdown("---")
        st.markdown("✍️ **Writing Style**")
        style_options = ["기본", "웹소설체", "감성적", "담백한", "고전", "유머러스"]
        selected_style = st.selectbox("Style Preset", style_options, key="setting_style", on_change=auto_save)
        st.markdown("---")
        st.markdown("🧑‍💻 **Persona**")
        persona_presets = {
            "Direct Input": "",
            "김은숙 st": "김은숙 작가 스타일로, 인물 간의 대사가 빠르고 재치 있게...",
            "지브리 st": "지브리 애니메이션처럼, 서정적이고 아름답게...",
            "박찬욱 st": "박찬욱 감독 스타일로, 우아하고 잔혹하게...",
            "막장 드라마": "아침 드라마처럼, 자극적이고 빠르게...",
        }

        sel_preset = st.selectbox("Persona Inspiration", list(persona_presets.keys()), key="setting_preset", on_change=auto_save)
        if "last_preset" not in st.session_state or st.session_state.last_preset != sel_preset:
            st.session_state.custom_persona_input = persona_presets.get(sel_preset, "")
            st.session_state.last_preset = sel_preset
        # Note: on_change for text_input requires a callback or checking state. 
        # For simplicity, we trust the 'custom_persona_input' state sync but force explicit auto_save on change
        def update_persona():
             st.session_state.custom_persona_input = st.session_state.custom_persona_ui
             auto_save()
             
        custom_persona = st.text_input("Custom Persona", value=st.session_state.custom_persona_input, key="custom_persona_ui", on_change=update_persona)
        
        st.markdown("---")
        st.markdown("📅 **Structure**")
        target_vols = st.number_input("Target Volumes", 1, 100, key="setting_target_vols", on_change=auto_save)
        st.markdown("---")
        with st.expander("Help"):
            st.write("1. Create Project\n2. Fill Character Sheet\n3. Generate Story\n4. Save Memory")

    # ---------- Main UI ----------
    st.title(f"💖 Romance AI: {st.session_state.current_project}")
    
    tab_write, tab_batch, tab_review, tab_art = st.tabs(["✍️ Story Engine", "🏭 Novel Factory (Batch)", "🧐 Editor's Desk", "🎨 Art Studio"])

    # ==========================================
    # TAB 1: STORY ENGINE (Classic)
    # ==========================================
    with tab_write:
        col1, col2 = st.columns([2, 1])

        # ----- Left column – core workflow -----
        with col1:
            # Story Bible
            with st.expander("📚 Story Bible", expanded=False):
                c1, c2 = st.columns(2)
                with c1:
                    new_char = st.text_area(
                        "Character Sheet",
                        value=st.session_state.char_sheet,
                        height=150,
                        placeholder="예시:\n- 김철수: 24세, 까칠한 천재 해커. 과거의 상처가 있음.\n- 이영희: 28세, 열정적인 형사. 철수를 의심하지만 끌림.",
                    )
                with c2:
                    new_world = st.text_area(
                        "World Setting",
                        value=st.session_state.world_setting,
                        height=150,
                        placeholder="예시:\n- 플로팅 아일랜드: 하늘에 떠 있는 3개의 거대 섬.\n- 마법 설정: 왕족만 별의 마법을 쓸 수 있음.",
                    )
                if new_char != st.session_state.char_sheet or new_world != st.session_state.world_setting:
                    st.session_state.char_sheet = new_char
                    st.session_state.world_setting = new_world
                    auto_save()

            # Idea Generator (full version)
            with st.expander("✨ Need Inspiration? (Magic Idea Generator)", expanded=False):
                st.markdown("### 🎭 Create Your Setup")
                # Basics
                c1, c2, c3 = st.columns(3)
                with c1:
                    genre_options = [
                        "전통로맨스", "사극(하)로맨스", "사극(중)로맨스", "사극(상)로맨스",
                        "현대로맨스", "판타지(약)로맨스", "판타지(중)로맨스", "판타지(강)로맨스",
                    ]
                    selected_genre = st.selectbox("Genre (장르)", genre_options, key="ig_genre", on_change=auto_save)
                with c2:
                    spice_options = ["19금(없음)", "19금(하)", "19금(중)", "19금(상)"]
                    selected_spice = st.selectbox("Spice Level (수위)", spice_options, key="ig_spice", on_change=auto_save)
                with c3:
                    if "ig_trends" not in st.session_state:
                        st.session_state.ig_trends = True
                    apply_trends = st.checkbox("🔥 Apply Trends (최신 유행)", key="ig_trends", on_change=auto_save)
                # Mood
                mood_tags = [
                    "검성코드", "격정멜로", "금지된사랑", "달달물", "로맨틱", "막장드라마",
                    "반전남녀", "순수남녀", "신파", "악녀시점", "애잔물", "위기탈출",
                    "위험한사랑", "육아물", "잔잔물", "질투물", "케미커플", "티격태격",
                    "피폐물", "하드코어", "힐링",
                ]
                selected_moods = st.multiselect("Mood & Atmosphere (분위기)", mood_tags, key="ig_moods", on_change=auto_save)
                # Male Lead
                male_tags = [
                    "개천용", "거만남", "계략남", "군인", "그리스인", "까칠남", "나쁜남자", "냉혹남",
                    "뇌섹남", "능글남", "다정남", "대형견남", "동정남", "라틴남", "러시아인",
                    "마피아/범죄자", "목장주", "미소년", "바람둥이", "법조인", "병약남", "보디가드",
                    "사기꾼", "사별남", "사이다남", "상처남", "소방관", "순정남", "시크남",
                    "아랍인(세이크)", "애교남", "언론인", "연예인남", "연하남", "영국인", "오만남",
                    "촌사람", "왕족/귀족", "외국인남", "요섹남", "운동선수", "의료업", "이탈리아인",
                    "이혼남", "인기남", "재벌남", "전남친", "절륜남", "존댓말남", "직진남", "진중남",
                    "짐승남", "짝사랑남", "차도남", "천재", "철벽남", "초식남", "카리스마남",
                    "카우보이", "평범", "프랑스인", "후계자", "후회남", "훈남",
                ]
                selected_male = st.multiselect("Male Lead (남자주인공)", male_tags, key="ig_male", on_change=auto_save)
                # Female Lead
                female_tags = [
                    "4차원/엉뚱녀", "가정부/메이드", "건어물녀", "걸크러시", "결혼식들러리", "계략녀",
                    "귀여운여인", "금지옥엽", "기자", "까칠녀", "꽃미녀", "남장여자", "뇌섹녀",
                    "능글녀", "당당/당찬녀", "도도녀/무심녀", "동정녀", "디자이너", "라틴녀", "모델",
                    "몰락재벌집 딸", "미망인", "미혼모", "백치미(둔녀)", "베이비시터", "병약녀", "비서",
                    "사이다녀", "상처녀", "생활고여주", "서비스업", "신비녀", "악녀", "애교녀",
                    "연예인녀", "영국인", "왕족/귀족", "외유내강녀", "웨딩플래너", "의료업", "이혼녀",
                    "자상녀", "재벌녀/상속녀", "전부인", "절륜녀", "직진녀", "짝사랑녀", "차도녀",
                    "철벽녀", "청순녀/순진녀", "친절녀", "카우걸", "캔디", "커리어우먼", "터프녀",
                    "털털녀", "파티셰", "평범", "환골탈태녀", "후회녀",
                ]
                selected_female = st.multiselect("Female Lead (여자주인공)", female_tags, key="ig_female", on_change=auto_save)
                # Character arc
                char_arc = st.text_input(
                    "Character Arc (성격/관계 변화)",
                    placeholder="예: 혐관 -> 찐사랑, 차가움 -> 다정함",
                    key="ig_arc",
                    on_change=auto_save
                )
                if st.button("🎲 Generate Random Story Concept"):
                    with st.spinner("Brainstorming creative ideas..."):
                        try:
                            res = requests.post(
                                f"{BACKEND_URL}/generate/idea",
                                json={
                                    "genre": selected_genre,
                                    "spice_level": selected_spice,
                                    "model": selected_model,
                                    "apply_trends": apply_trends,
                                    "moods": selected_moods,
                                    "male_tags": selected_male,
                                    "female_tags": selected_female,
                                    "arc": char_arc,
                                    "char_sheet": st.session_state.get("char_sheet", ""),
                                    "world_setting": st.session_state.get("world_setting", "")
                                },
                            )
                            if res.status_code == 200:
                                st.session_state.idea_suggestion = res.json().get("idea")
                                auto_save()
                            else:
                                st.error(f"Error: {res.text}")
                        except Exception as e:
                            st.error(f"Connection Error: {e}")
                if st.session_state.get("idea_suggestion"):
                    st.text_area(
                        "Suggested Setup (Editable):",
                        value=st.session_state.idea_suggestion,
                        height=200,
                        key="idea_input",
                    )
                    if st.button("� Copy Idea to Editor (for Manual Ref)"):
                        if st.session_state.get("current_story") and len(st.session_state.get("current_story")) > 50:
                             st.error("Current Story is not empty. Clear it first or manually copy the idea.")
                        else:
                            st.session_state.current_story = f"[Story Setup]\n{st.session_state.idea_suggestion}\n\n"
                            auto_save()
                            st.success("Idea copied to Editor! (Optional for Batch Mode)")
                            st.rerun()

            # --- 🏷️ Book Packaging (Metadata) ---
            with st.expander("🏷️ Book Packaging (Title/Intro/Tags)", expanded=False):
                st.info("Generates Title, Blurb, and Keywords based on your Story Content (Post-Writing).")
                if st.button("✨ Generate Metadata"):
                    if not st.session_state.get("current_story") or len(st.session_state.get("current_story")) < 500:
                        st.error("Please write the story first (min 500 chars) to generate accurate metadata.")
                    else:
                        with st.spinner("Reading story and crafting packaging..."):
                            settings_payload = {
                                "genre": st.session_state.get("ig_genre", ""),
                                "mood": ", ".join(st.session_state.get("ig_moods", [])),
                                "trends": "True" if st.session_state.get("ig_trends") else "False",
                                "characters": st.session_state.get("char_sheet", ""),
                                "world": st.session_state.get("world_setting", "")
                            }
                            # Use current_story (Use raw story, backend can handle length)
                            context_text = st.session_state.get("current_story")
                            
                            try:
                                res = requests.post(
                                    f"{BACKEND_URL}/generate/packaging", 
                                    json={
                                        "settings": settings_payload, 
                                        "outline": context_text,
                                        "model": selected_model
                                    }
                                )
                                if res.status_code == 200:
                                    pkg = res.json()
                                    st.session_state.pkg_titles = pkg.get("titles", [])
                                    st.session_state.pkg_blurb = pkg.get("blurb", "")
                                    st.session_state.pkg_keywords = pkg.get("keywords", [])
                                else:
                                    st.error(f"Error: {res.text}")
                            except Exception as e:
                                st.error(f"Analysis Error: {e}")

                if st.session_state.get("pkg_titles"):
                    st.write("### 📢 Titles")
                    for t in st.session_state.pkg_titles:
                        st.write(f"- {t}")
                    
                    st.write("### 📝 Blurb (Introduction)")
                    st.info(st.session_state.pkg_blurb)
                    
                    st.write("### 🏷️ Keywords")
                    st.caption(" ".join(st.session_state.pkg_keywords))

            # Plot Generator Integration
            with st.expander("📝 Plot Generator", expanded=False):
                st.markdown("### Generate structure")
                if st.button("Generate Plot Outline"):
                    if not st.session_state.get("ig_genre"):
                        st.error("Please select a Genre in the Idea Generator first.")
                    else:
                        with st.spinner("Designing plot..."):
                            settings_payload = {
                                "genre": st.session_state.get("ig_genre", ""),
                                "spice": st.session_state.get("ig_spice", ""),
                                "mood": ", ".join(st.session_state.get("ig_moods", [])),
                                "chars": st.session_state.get("char_sheet", ""),
                                "world": st.session_state.get("world_setting", ""),
                                "arc": st.session_state.get("ig_arc", ""),
                                "trends": "True" if st.session_state.get("ig_trends") else "False",
                                "idea_premise": st.session_state.get("idea_suggestion", "") # Pass the generated idea!
                            }
                            try:
                                res = requests.post(f"{BACKEND_URL}/analyze/plot", json={"settings": settings_payload, "model": selected_model})
                                if res.status_code == 200:
                                    st.session_state.plot_outline = res.json().get("plot", "")
                                    auto_save()
                                else:
                                    st.error(f"Error: {res.text}")
                            except Exception as e:
                                st.error(f"Connection Error: {e}")

                st.text_area(
                    "Plot Outline", 
                    value=st.session_state.get("plot_outline", ""),
                    height=300,
                    key="plot_outline_input",
                    on_change=lambda: [st.session_state.update({"plot_outline": st.session_state.plot_outline_input}), auto_save()]
                )



                # --- 🔮 Plot Evaluator ---
                st.markdown("---")
                st.subheader("🔮 Commercial Success Prediction")
                if st.button("Analyze Plot Potential"):
                    if not st.session_state.get("plot_outline"):
                         st.error("Please generate or write a Plot Outline first.")
                    else:
                         with st.spinner("Analyzing Market Trends & Reader Psychology..."):
                             settings_payload = {
                                "genre": st.session_state.get("ig_genre", ""),
                                "mood": ", ".join(st.session_state.get("ig_moods", [])),
                                "characters": st.session_state.get("char_sheet", ""),
                                "world": st.session_state.get("world_setting", ""),
                                "trends": "True" if st.session_state.get("ig_trends") else "False"
                             }
                             try:
                                 res = requests.post(
                                     f"{BACKEND_URL}/analyze/prediction", 
                                     json={
                                         "settings": settings_payload, 
                                         "outline": st.session_state.plot_outline,
                                         "model": selected_model
                                     }
                                 )
                                 if res.status_code == 200:
                                     st.session_state.prediction_report = res.json().get("report")
                                 else:
                                     st.error(f"Error: {res.text}")
                             except Exception as e:
                                 st.error(f"Connection Error: {e}")

                if "prediction_report" in st.session_state:
                    report = st.session_state.prediction_report
                    if report and "error" not in report:
                        # 1. Scores
                        c1, c2 = st.columns(2)
                        with c1:
                            st.metric("💰 Commercial Success", f"{report.get('commercial_score', 0)}/100")
                            st.progress(report.get('commercial_score', 0) / 100)
                        with c2:
                            st.metric("🔥 Binge-Reading Factor", f"{report.get('binge_score', 0)}/100")
                            st.progress(report.get('binge_score', 0) / 100)
                        
                        # 2. Target Audience
                        st.info(f"🎯 **Target Audience**: {report.get('target_audience', {}).get('gender', 'Unknown')} in {report.get('target_audience', {}).get('age', 'Unknown')} (Buying Power: {report.get('target_audience', {}).get('buying_power', 'Unknown')})")
                        
                        # 3. SWOT
                        st.markdown("#### 📊 SWOT Analysis")
                        swot = report.get('swot', {})
                        c1, c2 = st.columns(2)
                        c1.success(f"**Strengths**:\n" + "\n".join([f"- {x}" for x in swot.get('strengths', [])]))
                        c2.error(f"**Weaknesses**:\n" + "\n".join([f"- {x}" for x in swot.get('weaknesses', [])]))
                        c1.info(f"**Opportunities**:\n" + "\n".join([f"- {x}" for x in swot.get('opportunities', [])]))
                        c2.warning(f"**Threats**:\n" + "\n".join([f"- {x}" for x in swot.get('threats', [])]))

                        # 4. Advice
                        # 4. Advice & Auto-Improve
                        st.write("### 💡 Improvement Advice")
                        initial_advice = report.get('improvement_advice', 'No advice generated.')
                        
                        # Allow user to edit the advice before applying
                        user_advice = st.text_area(
                            "Review & Edit Improvement Instructions:", 
                            value=initial_advice,
                            height=150,
                            help="You can modify these instructions before the AI rewrites the plot."
                        )
                        
                        if st.button("✨ Auto-Improve Plot with these Instructions"):
                            with st.spinner("Refining plot structure..."):
                                try:
                                    settings_payload = {
                                        "genre": st.session_state.get("ig_genre", ""),
                                        "mood": ", ".join(st.session_state.get("ig_moods", [])),
                                        "characters": st.session_state.get("char_sheet", ""),
                                        "world": st.session_state.get("world_setting", "")
                                    }
                                    res = requests.post(
                                        f"{BACKEND_URL}/analyze/improve_plot", 
                                        json={
                                            "settings": settings_payload, 
                                            "outline": st.session_state.plot_outline,
                                            "advice": user_advice,
                                            "model": selected_model
                                        }
                                    )
                                    if res.status_code == 200:
                                        st.session_state.plot_outline = res.json().get("plot", "")
                                        auto_save()
                                        st.success("Plot updated based on advice!")
                                        st.rerun()
                                    else:
                                        st.error(f"Error: {res.text}")
                                except Exception as e:
                                    st.error(f"Connection Error: {e}")

                        st.caption(f"Overall Review: {report.get('overall_review', '')}")
            # Check for active batch job
            is_job_running = False
            if st.session_state.batch_job_id:
                try:
                    # Check status without blocking
                    # In a real app, we might poll less frequently or use a background thread
                    # Here we just check if it exists in session
                    pass 
                    # We rely on the user to refresh in Tab 2, but we can infer 'running' if ID exists
                    # Ideally, we should check status. For now, let's assume if ID exists, it might be running.
                    # To be precise, let's just show a warning if ID exists.
                    pass
                except:
                    pass

            # Auto-Merge Logic (from Tab 2)
            # Auto-Merge Logic (from Tab 2)
            if st.session_state.get("auto_merge_trigger"):
                # Append and clear trigger
                new_content = st.session_state.auto_merge_trigger
                timestamp = str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                separator = f"\n\n{'-'*20}\n[Batch Merged at {timestamp}]\n{'-'*20}\n"
                
                if st.session_state.current_story:
                    st.session_state.current_story += separator + new_content
                else:
                     st.session_state.current_story = new_content
                     
                st.session_state.auto_merge_trigger = None
                st.success("✅ Batch Job Completed! Content Auto-Merged to 'Current Story'.")
                auto_save()
                st.rerun()

            def update_current_story():
                st.session_state.current_story = st.session_state.current_story_input
                auto_save()

            # Lock if job is running (optional, but requested)
            # We need a way to know if job is truly running. 
            # For simplicity, we'll let the user write, but warn them.
            # Or strict lock:
            # is_locked = True if st.session_state.batch_job_id else False
            
            st.text_area("Current Story (Editable)", value=st.session_state.current_story, height=500, key="current_story_input", on_change=update_current_story)
            
            user_input = st.text_input("Next Prompt (What happens next?):", key="last_prompt")
            
            c1, c2 = st.columns([1, 1])
            with c1:
                if st.button("Generate / Continue"):
                    if user_input:
                        with st.spinner("Writing..."):
                            new_text = generate_story(
                                user_input, 
                                temperature, 
                                selected_model, 
                                selected_style, 
                                st.session_state.custom_persona_input,
                                st.session_state.setting_humor
                            )
                            if new_text and not new_text.startswith("[Error"):
                                st.session_state.current_story += "\n" + new_text
                                auto_save()
                                st.rerun()
            with c2:
                if st.button("Clear Story"):
                    st.session_state.current_story = ""
                    auto_save()
                    st.rerun()

        # ----- Right column – AI tools -----
        with col2:
            st.subheader("AI Editor Tools")
            # Critique
            # Critique & Auto-Fix
            st.markdown("### 🕵️ Auto-Editor")
            
            # Scope Selection
            analysis_scope = st.radio(
                "Target Scope:",
                ["Entire Story (All Text)", "Last Chapter Only (Auto-Detect)"],
                index=1, # Default to Last Chapter
                horizontal=True,
                help="Select 'Last Chapter' to faster analysis and avoid rewriting successful previous chapters."
            )

            if st.button("Run Deep Analysis"):
                if st.session_state.current_story:
                    
                    # Determine Text to Analyze
                    target_text = st.session_state.current_story
                    if "Last Chapter" in analysis_scope:
                        # Simple split by '## Chapter' or double newline if no headers
                        if "## Chapter" in target_text:
                            # Split and take the last part
                            parts = target_text.split("## Chapter")
                            # Re-add header
                            target_text = "## Chapter" + parts[-1]
                        else:
                            # Fallback: Last 5000 chars if no chapters defined
                            if len(target_text) > 5000:
                                target_text = target_text[-5000:]
                    
                    st.session_state.analysis_target_text = target_text # Store what we analyzed
                    
                    with st.spinner(f"Analyzing ({len(target_text)} chars)..."):
                        try:
                            # 1. Get Comprehensive Review
                            res = requests.post(
                                f"{BACKEND_URL}/analyze/review",
                                json={"text": target_text, "model": selected_model},
                            )
                            if res.status_code == 200:
                                st.session_state.critique_json = res.json()
                                # Convert to readable string for display
                                scores = st.session_state.critique_json.get("scores", {})
                                feedback = st.session_state.critique_json.get("feedback", {})
                                display_text = f"**Scope**: {analysis_scope}\n"
                                display_text += f"**Scores**: Consistency {scores.get('consistency')}, Creativity {scores.get('creativity')}\n\n"
                                display_text += f"**Feedback**: {feedback}\n\n"
                                display_text += f"**Overall**: {st.session_state.critique_json.get('overall_critique')}"
                                st.session_state.critique = display_text # Backward compatibility for display
                                auto_save()
                            else:
                                st.error(res.text)
                        except Exception as e:
                            st.error(f"Analysis Error: {e}")

            if st.session_state.get("critique"):
                with st.expander("View Analysis Report", expanded=True):
                    st.write(st.session_state.critique)
                    
                    # Auto-Fix Button (Only if JSON exists)
                    if st.session_state.get("critique_json"):
                        st.markdown("---")
                    # Auto-Fix Button (Only if JSON exists)
                    if st.session_state.get("critique_json"):
                        st.markdown("---")
                        st.caption("✨ AI can rewrite this chapter based on the report above.")
                        if st.button("✨ Auto-Fix Chapter (Self-Healing)"):
                             target_text = st.session_state.get("analysis_target_text", "")
                             if not target_text:
                                 st.error("No analysis target found. Please run analysis again.")
                             else:
                                 with st.spinner("Healing the story..."):
                                    try:
                                        res = requests.post(
                                            f"{BACKEND_URL}/generate/rewrite",
                                            json={
                                                "text": target_text, 
                                                "critique": st.session_state.critique_json,
                                                "model": selected_model
                                            }
                                        )
                                        if res.status_code == 200:
                                            new_text = res.json().get("rewritten_text")
                                            if new_text and len(new_text) > 100:
                                                # Update Logic based on Scope
                                                current_full = st.session_state.current_story
                                                if "Last Chapter" in analysis_scope and "## Chapter" in current_full:
                                                    # Re-assemble: Previous Parts + New Text
                                                    parts = current_full.rsplit("## Chapter", 1) # Split from right, once
                                                    if len(parts) == 2:
                                                        previous_part = parts[0]
                                                        # Ensure header is preserved/restored if needed, 
                                                        # but 'new_text' likely contains header if AI did its job? 
                                                        # Actually rewrite usually returns content. 
                                                        # Let's assume we need to attach it to '## Chapter' + header if missing, 
                                                        # OR simply replace the text block.
                                                        # Safest: Replace the text we analyzed (which had '## Chapter' added if manual split)
                                                        st.session_state.current_story = previous_part + new_text
                                                    else:
                                                        # Fallback if split failed unexpectedly
                                                        st.session_state.current_story = new_text
                                                else:
                                                    # Entire Story or Last 5000 chars fallback
                                                    if len(current_full) > 5000 and "Last Chapter" in analysis_scope:
                                                         # We only rewrote the last 5000 chars
                                                         st.session_state.current_story = current_full[:-len(target_text)] + new_text
                                                    else:
                                                         st.session_state.current_story = new_text
                                                
                                                st.success("Chapter Auto-Fixed! (Content updated)")
                                                st.rerun()
                                            else:
                                                st.error("Rewrite returned empty text.")
                                        else:
                                            st.error(res.text)
                                    except Exception as e:
                                        st.error(f"Rewrite Error: {e}")
            # Consistency
            if st.button("🕵️ Consistency Check"):
                if st.session_state.current_story:
                    with st.spinner("Checking..."):
                        try:
                            res = requests.post(
                                f"{BACKEND_URL}/analyze/consistency",
                                json={
                                    "text": st.session_state.current_story,
                                    "char_sheet": st.session_state.char_sheet,
                                    "world_setting": st.session_state.world_setting,
                                    "model": selected_model,
                                },
                            )
                            if res.status_code == 200:
                                report = res.json().get("report", {})
                                if report.get("name_errors"):
                                    st.error(f"Name Errors: {report['name_errors']}")
                                else:
                                    st.success("Names Consistent")
                                if report.get("plot_errors"):
                                    st.warning(f"Plot Conflicts: {report['plot_errors']}")
                            else:
                                st.error(res.text)
                        except Exception as e:
                            st.error(f"Conn Error: {e}")
            st.markdown("---")
            with st.expander("📦 Export / Publish", expanded=False):
                if st.session_state.get("current_story"):
                    # Metadata Inputs
                    export_title = st.text_input("Book Title", value=st.session_state.current_project, key="export_title_input")
                    col_meta1, col_meta2 = st.columns(2)
                    with col_meta1:
                        export_author = st.text_input("Author Name", value=st.session_state.user, key="export_author_input")
                    with col_meta2:
                        export_publisher = st.text_input("Publisher (출판사)", value="", placeholder="e.g., My Romance Books", key="export_publisher_input")

                    # 0. Full TXT (Clean & Simple)
                    if st.button("📄 Download Full TXT"):
                        settings_payload = {
                             "title": export_title,
                             "author": export_author,
                             "publisher": export_publisher,
                             "content": st.session_state.current_story,
                             "export_type": "txt"
                        }
                        try:
                            res = requests.post(f"{BACKEND_URL}/export/download", json=settings_payload)
                            if res.status_code == 200:
                                 st.download_button(
                                     label="⬇️ Click to Save TXT",
                                     data=res.content,
                                     file_name=f"{export_title}.txt",
                                     mime="text/plain"
                                 )
                            else:
                                st.error(f"Export Failed: {res.text}")
                        except Exception as e:
                            st.error(f"Conn Error: {e}")

                    # 1. Full EPUB
                    if st.button("📘 Download Full EPUB"):
                        settings_payload = {
                             "title": export_title,
                             "author": export_author,
                             "publisher": export_publisher,
                             "content": st.session_state.current_story,
                             "export_type": "epub"
                        }
                        try:
                            res = requests.post(f"{BACKEND_URL}/export/download", json=settings_payload)
                            if res.status_code == 200:
                                 st.download_button(
                                     label="⬇️ Click to Save EPUB",
                                     data=res.content,
                                     file_name=f"{export_title}.epub",
                                     mime="application/epub+zip"
                                 )
                            else:
                                st.error(f"Export Failed: {res.text}")
                        except Exception as e:
                            st.error(f"Conn Error: {e}")

                    # 2. Serial TXT (Split)
                    if st.button("✂️ Download Serial TXT (ZIP)"):
                        settings_payload = {
                             "title": export_title,
                             "author": export_author,
                             "publisher": export_publisher,
                             "content": st.session_state.current_story,
                             "export_type": "txt_zip"
                        }
                        try:
                            res = requests.post(f"{BACKEND_URL}/export/download", json=settings_payload)
                            if res.status_code == 200:
                                 st.download_button(
                                     label="⬇️ Click to Save ZIP (TXT)",
                                     data=res.content,
                                     file_name=f"{st.session_state.current_project}_serial_txt.zip",
                                     mime="application/zip"
                                 )
                            else:
                                st.error(f"Export Failed: {res.text}")
                        except Exception as e:
                            st.error(f"Conn Error: {e}")

                    # 3. Serial EPUB (Split)
                    if st.button("📚 Download Serial EPUB (ZIP)"):
                        settings_payload = {
                             "title": export_title,
                             "author": export_author,
                             "publisher": export_publisher,
                             "content": st.session_state.current_story,
                             "export_type": "epub_zip"
                        }
                        try:
                            res = requests.post(f"{BACKEND_URL}/export/download", json=settings_payload)
                            if res.status_code == 200:
                                 st.download_button(
                                     label="⬇️ Click to Save ZIP (EPUB)",
                                     data=res.content,
                                     file_name=f"{export_title}_serial_epub.zip",
                                     mime="application/zip"
                                 )
                            else:
                                st.error(f"Export Failed: {res.text}")
                        except Exception as e:
                            st.error(f"Conn Error: {e}")
            
            # Legacy simple download (hidden or kept as fallback? User said 'there is existing Download TXT', implied replacement or move)
            # Re-adding simple download as fallback if needed, but the new section covers it.
            # st.download_button("Download TXT (Simple)", create_download_file(st.session_state.current_story), "story.txt")

    # ==========================================
    # TAB 2: NOVEL FACTORY (Batch)
    # ==========================================
    with tab_batch:
        st.header("🏭 50-Chapter Automated Novel Factory")
        st.info("Generates a full novel (50 chapters) in one click using Hierarchical Generation.")
        
        # Auto-Merge Option
        c1, c2 = st.columns(2)
        with c1:
            auto_merge = st.checkbox("☑️ Auto-append to Current Story on completion", value=True)
        with c2:
            use_outline = st.checkbox("📋 Use 'Plot Outline' as Blueprint", value=True, help="If checked, the batch generator will follow the outline in Tab 1.")

        if st.button(f"🚀 Start Production ({st.session_state.get('setting_target_vols', 1) * 25} Chapters)"):
            with st.spinner("Initializing Batch Job..."):
                settings = {
                    "genre": st.session_state.get("ig_genre", "Romance"),
                    "theme": st.session_state.get("ig_arc", "Love"),
                    "characters": st.session_state.get("char_sheet", "Unknown"),
                    "conflict": "Standard Romance Conflict" 
                }
                
                # Prepare reference outline
                ref_outline = st.session_state.get("plot_outline", "") if use_outline else ""
                
                try:
                    res = requests.post(
                        f"{BACKEND_URL}/generate/batch_start",
                        json={
                            "settings": settings, 
                            "target_vols": st.session_state.get("setting_target_vols", 1),
                            "model_writer": "DeepSeek-7B (Fine-tuned)",
                            "model_planner": selected_model,
                            "reference_outline": ref_outline
                        }
                    )
                    if res.status_code == 200:
                        job_id = res.json().get("job_id")
                        st.session_state.batch_job_id = job_id
                        st.session_state.auto_merge_enabled = auto_merge 
                        st.success(f"Job Started! ID: {job_id}")
                    else:
                        st.error(f"Failed to start: {res.text}")
                except Exception as e:
                    st.error(f"Error: {e}")

        # Batch Monitor
        if "batch_job_id" in st.session_state:
            st.markdown("---")
            st.subheader(f"Monitor Job: {st.session_state.batch_job_id}")
            if st.button("🔄 Refresh Status"):
                try:
                    res = requests.get(f"{BACKEND_URL}/generate/batch_status/{st.session_state.batch_job_id}")
                    if res.status_code == 200:
                        status = res.json()
                        st.write(f"**Status**: {status.get('status')}")
                        st.progress(status.get('progress', 0))
                        
                        # Show logs
                        with st.expander("Logs"):
                            for log in status.get('log', []):
                                st.text(log)
                                
                        # Show Results
                        if status.get('results'):
                            st.subheader("Generated Chapters")
                            for ch in status['results']:
                                with st.expander(f"Chapter {ch['chapter_num']}: {ch['title']}"):
                                    st.write(ch['text'][:500] + "...")
                                    st.info(f"Review Score: {ch.get('review', {}).get('scores', 'N/A')}")
                        
                        # Auto-Merge Trigger
                        if status.get("status") == "completed" and st.session_state.get("auto_merge_enabled"):
                            # Aggregate text
                            full_text = "\n\n".join([f"## Chapter {ch['chapter_num']}: {ch['title']}\n{ch['text']}" for ch in status['results']])
                            st.session_state.auto_merge_trigger = full_text
                            del st.session_state.batch_job_id # Clear job to unlock
                            st.success("Job Done! Switch to Story Engine tab to see merged content.")
                            
                    else:
                        st.error("Job not found")
                except Exception as e:
                    st.error(str(e))

    # ==========================================
    # TAB 3: EDITOR'S DESK (Review)
    # ==========================================
    with tab_review:
        st.header("🧐 Comprehensive Review & Auto-Fix")
        
        # Optimization: Analysis Scope
        scope_option = st.radio(
            "Analysis Scope (Performance Optimization)",
            ["Last 3 Chapters (approx. 10k chars)", "Full Text (Slow)"],
            index=0,
            horizontal=True,
            help="For long novels (>50k chars), 'Full Text' may be slow. Use 'Last 3 Chapters' for quicker feedback."
        )

        def get_analysis_text():
            text = st.session_state.current_story
            if scope_option.startswith("Last"):
                return text[-12000:] if len(text) > 12000 else text # 12k chars safety buffer
            return text

        # 1. Review Section
        if st.button("Run Deep Analysis"):
             target_text = get_analysis_text()
             if target_text:
                with st.spinner(f"Analyzing {len(target_text)} chars..."):
                    try:
                        res = requests.post(
                            f"{BACKEND_URL}/analyze/review_comprehensive",
                            json={"text": target_text, "model": selected_model}
                        )
                        if res.status_code == 200:
                             st.session_state.review_result = res.json()["review"]
                             auto_save()
                        else:
                             st.error(res.text)
                    except Exception as e:
                        st.error(f"Connection Error: {e}")
             else:
                 st.warning("No text to analyze.")

        if "review_result" in st.session_state:
            review = st.session_state.review_result
            st.subheader(f"Score: {review.get('scores', 'N/A')}")
            
            with st.expander("Detailed Critique", expanded=True):
                st.markdown(review.get("feedback"))
                
            with st.expander("Improvement Suggestions"):
                st.markdown(review.get("improvement_suggestions"))

            # 2. Auto-Fix (Rewriting)
            st.markdown("### 🛠️ Auto-Fix Assistant")
            
            if st.button("Generate Fix based on Critique"):
                target_text = get_analysis_text() # Use same scope for fix
                with st.spinner("Rewriting story segment..."):
                    try:
                        # Prepare Critique Summary
                        critique_summary = f"Feedback: {review.get('feedback')}\nSuggestions: {review.get('improvement_suggestions')}"
                        
                        res = requests.post(
                            f"{BACKEND_URL}/analyze/rewrite",
                            json={
                                "text": target_text,
                                "critique": critique_summary,
                                "char_sheet": st.session_state.char_sheet,
                                "world_setting": st.session_state.world_setting,
                                "model": selected_model
                            }
                        )
                        if res.status_code == 200:
                            st.session_state.rewritten_text = res.json().get("rewritten")
                        else:
                            st.error(res.text)
                    except Exception as e:
                        st.error(str(e))

            # 3. Diff View & Actions
            if st.session_state.get("rewritten_text"):
                st.markdown("### 🔄 Review Fix Proposal")
                
                col_orig, col_new = st.columns(2)
                with col_orig:
                    # Show relevant original text
                    orig_display = get_analysis_text()
                    st.text_area("Original (Scope)", value=orig_display, height=400, disabled=True)
                with col_new:
                    st.text_area("Proposed Fix", value=st.session_state.rewritten_text, height=400, key="fix_preview")
                
                # Action Buttons
                b1, b2, b3 = st.columns([1, 1, 1])
                
                if b1.button("✅ Accept Fix"):
                    # Logic to replace ONLY the analyzed part if using partial scope
                    # This is tricky. Simple replace works if scope is full.
                    # If scope is partial, we need to replace the suffix.
                    
                    full_text = st.session_state.current_story
                    new_segment = st.session_state.rewritten_text
                    
                    if scope_option.startswith("Last") and len(full_text) > 12000:
                        # Replace last 12000 chars
                        prefix = full_text[:-12000]
                        st.session_state.current_story = prefix + new_segment
                    else:
                        st.session_state.current_story = new_segment

                    # Sync with input widget if used
                    if "current_story_input" in st.session_state:
                         st.session_state.current_story_input = st.session_state.current_story
                    
                    # Cleanup
                    del st.session_state.rewritten_text
                    del st.session_state.review_result
                    auto_save()
                    st.success("Fix Applied Successfully!")
                    st.rerun()
                
                if b2.button("🔄 Regenerate (Try Again)"):
                    # Trigger regeneration (same logic as Generate Fix)
                    with st.spinner("Regenerating fix..."):
                        try:
                            critique_summary = f"Feedback: {review.get('feedback')}\nSuggestions: {review.get('improvement_suggestions')}"
                            res = requests.post(
                                f"{BACKEND_URL}/analyze/rewrite",
                                json={
                                    "text": st.session_state.current_story,
                                    "critique": critique_summary,
                                    "char_sheet": st.session_state.char_sheet,
                                    "world_setting": st.session_state.world_setting,
                                    "model": selected_model
                                }
                            )
                            if res.status_code == 200:
                                st.session_state.rewritten_text = res.json().get("rewritten")
                                st.rerun()
                            else:
                                st.error(res.text)
                        except Exception as e:
                            st.error(str(e))

                if b3.button("❌ Cancel"):
                    del st.session_state.rewritten_text
                    st.rerun()

    # ==========================================
    # TAB 4: ART STUDIO (Production)
    # ==========================================
    with tab_art:
        st.header("🎨 Cover Art Studio (Imagen 3)")
        
        # 1. Prompt Generation
        if st.button("Generate Prompt from Story"):
            with st.spinner("Extracting imagery..."):
                try:
                    res = requests.post(f"{BACKEND_URL}/analyze/cover_prompt", json={"text": st.session_state.current_story})
                    if res.status_code == 200:
                        st.session_state.cover_prompt = res.json().get("cover_prompt")
                    else:
                        st.error(res.text)
                except Exception as e:
                    st.error(str(e))
        
        prompt_input = st.text_area("Image Prompt", value=st.session_state.get("cover_prompt", ""), height=100)
        
        # 2. Image Generation
        if st.button("✨ Generate Image (Imagen 3)"):
            if prompt_input:
                with st.spinner("Painting..."):
                    try:
                        res = requests.post(f"{BACKEND_URL}/generate/imagen3", json={"prompt": prompt_input})
                        if res.status_code == 200 and "image_base64" in res.json():
                            img_data = base64.b64decode(res.json()["image_base64"])
                            st.image(img_data, caption="Generated by Imagen 3")
                        else:
                            st.error(res.text)
                    except Exception as e:
                         st.error(str(e))


    # ==========================================
    # TAB 5: NOVEL FACTORY (Batch Production)
    # ==========================================
    with tab_batch:
        st.header("🏭 Novel Factory (Batch Generation)")
        
        # 1. Job Control
        c1, c2 = st.columns([1, 1])
        with c1:
            st.subheader("🚀 Start Production")
            batch_writer_model = st.selectbox("Writer Model", model_options, key="batch_writer", index=4) # Default DeepSeek
            batch_planner_model = st.selectbox("Planner Model", ["gemini-2.0-pro-exp-02-05", "gemini-1.5-pro-latest"], key="batch_planner")
            
            # Additional Settings
            st.write("Current Settings:")
            st.info(f"Creativity: {temperature} | Humor: {st.session_state.setting_humor}/10 | Style: {selected_style}")
            
            # Auto-Merge Option
            auto_merge = st.checkbox("☑️ Auto-Append to Current Story", value=st.session_state.auto_merge_enabled, key="auto_merge_chk")
            if auto_merge != st.session_state.auto_merge_enabled:
                st.session_state.auto_merge_enabled = auto_merge

            # Self-Healing Option
            self_healing = st.toggle("🩺 Enable Self-Healing (Quality Control)", value=False, help="If enabled, AI will automatically rewrite chapters with low review scores (<70). Increases generation time.")

            if st.button("Start Production (50 Chapters)"):
                # Prepare Settings Payload
                batch_settings = {
                    "genre": st.session_state.get("ig_genre", "Romance"),
                    "spice": st.session_state.get("ig_spice", "Unknown"),
                    "mood": ", ".join(st.session_state.get("ig_moods", [])),
                    "chars": st.session_state.get("char_sheet", ""),
                    "world": st.session_state.get("world_setting", ""),
                    "style": selected_style,
                    "persona": st.session_state.custom_persona_input,
                    "humor_level": st.session_state.setting_humor,
                    "idea_premise": st.session_state.get("idea_suggestion", ""),
                    "creativity": temperature
                }
                
                with st.spinner("Initializing Factory..."):
                    try:
                        res = requests.post(
                            f"{BACKEND_URL}/generate/batch_start",
                            json={
                                "settings": batch_settings,
                                "target_vols": 50,
                                "model_writer": batch_writer_model,
                                "model_planner": batch_planner_model,
                                "reference_outline": st.session_state.get("plot_outline", "") if st.session_state.get("use_plot_outline") else "",
                                "self_healing": self_healing
                            }
                        )
                        if res.status_code == 200:
                            job_id = res.json().get("job_id")
                            st.session_state.batch_job_id = job_id
                            st.success(f"Job Started! ID: {job_id}")
                        else:
                            st.error(f"Failed to start: {res.text}")
                    except Exception as e:
                        st.error(f"Connection Error: {e}")

        with c2:
            st.subheader("📺 Monitor Job")
            if st.session_state.batch_job_id:
                st.write(f"Active Job: `{st.session_state.batch_job_id}`")
                if st.button("🔄 Refresh Status"):
                    try:
                        res = requests.get(f"{BACKEND_URL}/generate/batch_status/{st.session_state.batch_job_id}")
                        if res.status_code == 200:
                            status = res.json()
                            st.session_state.batch_status = status
                            
                            # Check for completion (simple check)
                            if status.get("status") == "completed":
                                st.success("Job Done!")
                                if st.session_state.auto_merge_enabled:
                                    # Collect text
                                    full_text = ""
                                    for ch in status.get("results", []):
                                        full_text += f"\n\n## Chapter {ch['chapter_num']}: {ch['title']}\n{ch['text']}"
                                    
                                    if st.session_state.auto_merge_trigger != full_text: # Prevent double trigger
                                         st.session_state.auto_merge_trigger = full_text
                                         st.success("Auto-Merged to Story Engine!")

                        else:
                            st.error("Job not found or error.")
                    except Exception as e:
                       st.error(str(e))
                
                # Display Status
                if "batch_status" in st.session_state:
                    stat = st.session_state.batch_status
                    st.progress(stat.get("progress", 0) / 100)
                    st.write(f"Status: **{stat.get('status')}**")
                    
                    with st.expander("Logs", expanded=False):
                        for log in stat.get("log", []):
                            st.text(log)
                    
                    st.subheader("Generated Chapters")
                    for ch in stat.get("results", []):
                        with st.expander(f"Chapter {ch['chapter_num']}: {ch['title']}"):
                            st.write(ch['text'])
                            st.info(f"Review Score: {ch.get('review', {}).get('scores', 'N/A')}")
            else:
                st.info("No active job.")


if __name__ == "__main__":
    main()
