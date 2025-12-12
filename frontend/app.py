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

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

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


def generate_story(prompt: str, temperature: float, model: str, style: str, persona: str) -> str:
    current = st.session_state.get("current_story", "")
    chars = st.session_state.get("char_sheet", "")
    world = st.session_state.get("world_setting", "")
    recent_memory = "\n".join(st.session_state.get("memory_chain", [])[-3:]) if st.session_state.get("memory_chain") else "No previous chapter memory."
    full_prompt = f"""
You are a best‑selling romance novelist. Write the next section of the story.

[WRITING STYLE GUIDE]
- **Tone/Style**: {style}
- **Author Persona/Voice**: {persona if persona else "Professional, Engaging"}
- **Directive**: "Show, Don't Tell". Focus on sensory details and emotional resonance rather than abstract summaries.

[STORY BIBLE]
- Characters: {chars}
- World Setting: {world}

[PREVIOUS CHAPTER SUMMARY (MEMORY)]
{recent_memory}

[CURRENT STORY CONTEXT]
{current[-3000:] if current else "No story yet."}

[USER REQUEST]
Genre: Romance.
Action: {prompt}

Write the next scene naturally.
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
            "last_prompt": st.session_state.get("last_prompt", ""),
            # Persist Idea Generator
            "ig_genre": st.session_state.get("ig_genre", "전통로맨스"),
            "ig_spice": st.session_state.get("ig_spice", "19금(없음)"),
            "ig_trends": st.session_state.get("ig_trends", True),
            "ig_moods": st.session_state.get("ig_moods", []),
            "ig_male": st.session_state.get("ig_male", []),
            "ig_female": st.session_state.get("ig_female", []),
            "ig_arc": st.session_state.get("ig_arc", ""),
        }
        save_project(username, st.session_state.current_project, payload)

    # ---------- Settings sidebar ----------
    with st.sidebar:
        st.title("Settings")
        temperature = st.slider("Creativity (Temperature)", 0.1, 1.0, 0.7, key="setting_temperature", on_change=auto_save)
        model_options = [
            "gemini-2.5-flash-preview-09-2025",
            "gemini-3-pro-preview",
            "gemini-1.5-flash",
            "gemini-2.0-flash-exp",
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
        target_vols = st.number_input("Target Volumes", 1, 100, 1, key="setting_target_vols", on_change=auto_save)
        st.markdown("---")
        with st.expander("Help"):
            st.write("1. Create Project\n2. Fill Character Sheet\n3. Generate Story\n4. Save Memory")

    # ---------- Main UI ----------
    st.title(f"💖 Romance AI: {st.session_state.current_project}")
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
            st.markdown("### 🎭 Create Your Perfect Setup")
            # Basics
            c1, c2, c3 = st.columns(3)
            with c1:
                genre_options = [
                    "전통로맨스",
                    "사극(하)로맨스", "사극(중)로맨스", "사극(상)로맨스",
                    "현대로맨스",
                    "판타지(약)로맨스", "판타지(중)로맨스", "판타지(강)로맨스",
                ]
                selected_genre = st.selectbox("Genre (장르)", genre_options, key="ig_genre", on_change=auto_save)
            with c2:
                spice_options = ["19금(없음)", "19금(하)", "19금(중)", "19금(상)"]
                selected_spice = st.selectbox("Spice Level (수위)", spice_options, key="ig_spice", on_change=auto_save)
            with c3:
                apply_trends = st.checkbox("🔥 Apply Trends (최신 유행)", value=True, key="ig_trends", on_change=auto_save)
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
                                "char_arc": char_arc,
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
                if st.button("Use this Idea to Start Story"):
                    st.session_state.current_story = f"[Story Setup]\n{st.session_state.idea_suggestion}\n\n[Chapter 1]\n"
                    auto_save()
                    st.rerun()
        # Story workspace
        st.text_area("Current Story", value=st.session_state.current_story, height=500, disabled=True)
        user_input = st.text_input("Next Prompt (What happens next?):", key="last_prompt", on_change=auto_save)
        if st.button("Generate / Continue"):
            if user_input:
                with st.spinner("Writing..."):
                    new_text = generate_story(user_input, temperature, selected_model, selected_style, custom_persona)
                    if new_text and not new_text.startswith("[Error"):
                        st.session_state.current_story += "\n" + new_text
                        auto_save()
                        st.rerun()
        if st.button("Clear Story"):
            st.session_state.current_story = ""
            auto_save()
            st.rerun()

    # ----- Right column – AI tools -----
    with col2:
        st.subheader("AI Editor Tools")
        # Critique
        if st.button("Request AI Critique"):
            if st.session_state.current_story:
                with st.spinner("Feedback..."):
                    try:
                        res = requests.post(
                            f"{BACKEND_URL}/analyze/feedback",
                            json={"text": st.session_state.current_story, "model": selected_model},
                        )
                        if res.status_code == 200:
                            st.session_state.critique = res.json().get("critique")
                            auto_save()
                        else:
                            st.error(res.text)
                    except Exception as e:
                        st.error(e)
        if st.session_state.get("critique"):
            with st.expander("View Critique", expanded=True):
                st.write(st.session_state.critique)
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
        # Marketing data
        st.markdown("---")
        st.markdown("**Marketing & Export**")
        if st.button("🏷️ Analyze Title/Blurb"):
            if st.session_state.current_story:
                with st.spinner("Analyzing..."):
                    try:
                        res = requests.post(
                            f"{BACKEND_URL}/analyze/title",
                            json={"text": st.session_state.current_story, "model": selected_model},
                        )
                        if res.status_code == 200:
                            data = res.json().get("result", {})
                            st.write(f"**Titles**: {data.get('titles')}")
                            st.write(f"**Summary**: {data.get('summary')}")
                            # Excel export
                            rows = []
                            for t in data.get("titles", []):
                                rows.append({"Type": "Title", "Content": t})
                            rows.append({"Type": "Blurb", "Content": data.get("blurb")})
                            df = pd.DataFrame(rows)
                            output = BytesIO()
                            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                                df.to_excel(writer, index=False)
                            st.download_button("📥 Excel Download", output.getvalue(), "marketing.xlsx")
                        else:
                            st.error(res.text)
                    except Exception as e:
                        st.error(e)
        # Cover art
        st.markdown("---")
        st.markdown("**Cover Art**")
        if st.button("🎨 Design & Generate Cover"):
            with st.spinner("Generating..."):
                try:
                    # 1. Prompt generation
                    res1 = requests.post(
                        f"{BACKEND_URL}/analyze/cover_prompt",
                        json={"text": st.session_state.current_story, "model": selected_model},
                    )
                    if res1.status_code == 200:
                        prompt = res1.json().get("cover_prompt")
                        st.info(f"Prompt: {prompt}")
                        # 2. Image generation
                        res2 = requests.post(
                            f"{BACKEND_URL}/generate/cover_image",
                            json={"prompt": prompt},
                        )
                        if res2.status_code == 200 and "image_base64" in res2.json():
                            img = base64.b64decode(res2.json()["image_base64"])
                            st.image(img)
                    else:
                        st.error(res1.text)
                except Exception as e:
                    st.error(e)
        st.markdown("---")
        st.download_button("Download TXT", create_download_file(st.session_state.current_story), "story.txt")

if __name__ == "__main__":
    main()
