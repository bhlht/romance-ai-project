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
    # Use environment backend url if defined and starts with localhost/127, otherwise default to port 8081 locally
    env_backend = os.getenv("BACKEND_URL", "")
    if "localhost" in env_backend or "127.0.0.1" in env_backend:
        BACKEND_URL = env_backend
    else:
        BACKEND_URL = "http://localhost:8081"
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


# ── Publisher Hub Storage Helpers ──

def get_user_publisher_dir(username: str) -> str:
    pub_dir = os.path.join(BASE_DATA_DIR, username, "publisher_hub")
    if not os.path.exists(pub_dir):
        os.makedirs(pub_dir)
    return pub_dir

def list_publisher_documents(username: str) -> list:
    pub_dir = get_user_publisher_dir(username)
    files = glob.glob(os.path.join(pub_dir, "*.json"))
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return [os.path.basename(f).replace(".json", "") for f in files]

def load_publisher_document(username: str, doc_title: str) -> dict:
    pub_dir = get_user_publisher_dir(username)
    path = os.path.join(pub_dir, f"{doc_title}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_publisher_document(username: str, doc_title: str, data: dict) -> None:
    pub_dir = get_user_publisher_dir(username)
    path = os.path.join(pub_dir, f"{doc_title}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"원고 저장 실패: {e}")

def delete_publisher_document(username: str, doc_title: str) -> None:
    pub_dir = get_user_publisher_dir(username)
    path = os.path.join(pub_dir, f"{doc_title}.json")
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception as e:
            st.error(f"원고 삭제 실패: {e}")

def auto_save_publisher_doc():
    if st.session_state.get("pub_current_doc") and st.session_state.get("user"):
        save_publisher_document(
            st.session_state.user,
            st.session_state.pub_current_doc,
            {
                "raw_text": st.session_state.get("pub_raw_text", ""),
                "filename": st.session_state.get("pub_editor_filename", ""),
                "episodes": st.session_state.get("pub_episodes", []),
                "edits": st.session_state.get("pub_editor_edits", {}),
                "char_sheet": st.session_state.get("pub_local_char_sheet", ""),
                "world_setting": st.session_state.get("pub_local_world_setting", "")
            }
        )


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



def get_clean_rag_params():
    """
    Sanitizes RAG session state variables before sending to backend to avoid 422 validation errors.
    Returns: (enabled, category_id, series_id, keyword)
    """
    enabled = st.session_state.get("rag_enabled", True)
    
    cat_id = st.session_state.get("rag_category_id")
    if cat_id in ("", "None", None):
        cat_id = None
    else:
        try:
            cat_id = int(cat_id)
        except:
            cat_id = None
            
    series_id = st.session_state.get("rag_series_id")
    if series_id in ("", "None", None):
        series_id = None
    else:
        try:
            series_id = int(series_id)
        except:
            series_id = None
            
    keyword = st.session_state.get("rag_keyword", "")
    if keyword in (None, "None"):
        keyword = ""
        
    return enabled, cat_id, series_id, keyword


def fetch_rag_categories():
    try:
        res = requests.get(f"{BACKEND_URL}/rag/categories", timeout=10)
        if res.status_code == 200:
            return res.json().get("categories", [])
    except Exception as e:
        print(f"Failed to fetch RAG categories: {e}")
    return []

def fetch_rag_series(category_id=None, series_id=None, search_query=None):
    # Clean inputs
    if category_id in ("", "None", None):
        category_id = None
    else:
        try: category_id = int(category_id)
        except: category_id = None

    if series_id in ("", "None", None):
        series_id = None
    else:
        try: series_id = int(series_id)
        except: series_id = None

    if category_id is None and series_id is None and search_query is None:
        return []
    try:
        params = {}
        if category_id is not None:
            params["category_id"] = category_id
        if series_id is not None:
            params["series_id"] = series_id
        if search_query is not None:
            params["search_query"] = search_query
        res = requests.get(f"{BACKEND_URL}/rag/series", params=params, timeout=10)
        if res.status_code == 200:
            return res.json().get("series", [])
    except Exception as e:
        print(f"Failed to fetch RAG series: {e}")
    return []



def generate_story(
    prompt: str, 
    temperature: float, 
    model: str, 
    style: str, 
    persona: str, 
    humor_level: int = 0,
    chapter_num: int = 1,
    ch_focus: str = "",
    plot_summary: str = "",
    writer_memo: str = ""
) -> str:
    current_story = st.session_state.get("current_story", "")
    memory_chain = st.session_state.get("memory_chain", [])
    chars = st.session_state.get("char_sheet", "")
    world = st.session_state.get("world_setting", "")
    
    # Fetch previous chapter text if chapter_num > 1 to maintain continuity/bridge
    prev_chapter_text = ""
    if chapter_num > 1 and "chapters" in st.session_state:
        prev_chapter_text = st.session_state.chapters.get(str(chapter_num - 1), "")
    
    # RAG settings from state
    rag_enabled, rag_category_id, rag_series_id, rag_keyword = get_clean_rag_params()
    
    payload = {
        "prompt": prompt,
        "context": current_story,
        "previous_chapter_context": prev_chapter_text,
        "chars": chars,
        "world": world,
        "style": style,
        "persona": persona,
        "humor_level": humor_level,
        "chapter_num": chapter_num,
        "ch_focus": ch_focus,
        "memory_chain": memory_chain,
        "plot_summary": plot_summary,
        "writer_memo": writer_memo,
        "temperature": temperature,
        "model": model,
        "max_length": 2000,
        "rag_enabled": rag_enabled,
        "rag_category_id": rag_category_id,
        "rag_series_id": rag_series_id,
        "rag_keyword": rag_keyword,
        "style_guide": st.session_state.get("ig_style_guide", "")
    }
    # Clean payload by removing None values to avoid Pydantic v2 validation errors on old backend versions
    payload = {k: v for k, v in payload.items() if v is not None}
    
    try:
        response = requests.post(
            f"{BACKEND_URL}/generate/romance",
            json=payload, 
            timeout=600 # Increased for V3 pipeline
        )
        if response.status_code == 200:
            new_text = response.json().get("generated_text", "")
            
            # [Auto-Memory] Automatically summarize and save to Long-Term Memory
            try:
                requests.post(
                    f"{BACKEND_URL}/summarize",
                    json={
                        "text": new_text,
                        "chapter_num": chapter_num,
                        "chars": chars,
                        "model": "models/gemini-3-flash-preview"
                    },
                    timeout=60
                )
            except:
                pass # Silently fail for autum-memory as it's not critical for the draft return
                
            return new_text
        else:
            return f"[Error: 서버 오류 ({response.status_code}): {response.text}]"
            
    except Exception as e:
        return f"[Error: 연결 오류 - {str(e)}]"

# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Romance AI Creator", page_icon="💖", layout="wide")
    
    # Model Options Constants
    writer_model_options = [
        "gemini-2.5-pro",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
    ]
    assistant_model_options = [
        "gemini-2.5-flash",
        "gemini-3.5-flash",
        "gemini-2.0-flash",
        "gemini-2.5-pro",
    ]

    # ---------- Auto‑login via query params ----------
    if "user" not in st.session_state:
        st.session_state.user = None
    
    # Initialize Session State Variables
    if "clear_last_prompt_flag" not in st.session_state:
        st.session_state.clear_last_prompt_flag = False
    if st.session_state.clear_last_prompt_flag:
        st.session_state.last_prompt = ""
        st.session_state.clear_last_prompt_flag = False

    if "setting_target_vols" not in st.session_state:
        st.session_state.setting_target_vols = 1
    if "setting_target_chapters" not in st.session_state:
        st.session_state.setting_target_chapters = 50
    if "chapters_settings" not in st.session_state:
        st.session_state.chapters_settings = {}
    if "apply_plot_style" not in st.session_state:
        st.session_state.apply_plot_style = False
    if "batch_job_id" not in st.session_state:
        st.session_state.batch_job_id = None
    if "auto_merge_trigger" not in st.session_state:
        st.session_state.auto_merge_trigger = None
    if "auto_merge_enabled" not in st.session_state:
        st.session_state.auto_merge_enabled = False

    if "current_page" not in st.session_state:
        st.session_state.current_page = "✍️ Story Engine"
        
    # RAG state variables
    if "rag_enabled" not in st.session_state:
        st.session_state.rag_enabled = True
    if "rag_categories" not in st.session_state:
        st.session_state.rag_categories = fetch_rag_categories()
    if "rag_category_id" not in st.session_state:
        st.session_state.rag_category_id = None
    if "rag_series" not in st.session_state:
        st.session_state.rag_series = fetch_rag_series()
    if "rag_series_id" not in st.session_state:
        st.session_state.rag_series_id = None
    if "rag_keyword" not in st.session_state:
        st.session_state.rag_keyword = ""
    if "rag_series_search_val" not in st.session_state:
        st.session_state.rag_series_search_val = ""
        
    if not st.session_state.user:
        qp = st.query_params
        if "user" in qp and "token" in qp:
            saved_user = str(qp["user"]).strip()
            # Enforce clean usernames even for auto-login
            if not re.match(r'^[a-zA-Z0-9_\-]+$', saved_user):
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
        if st.session_state.current_page == "📦 Publisher Hub":
            st.write(f"👤 **{username} (출판 허브)**")
            if st.button("Logout"):
                st.session_state.user = None
                st.query_params.clear()
                st.rerun()
                
            st.title("📦 원고 관리자")
            
            pub_mode = st.radio("원고 관리", ["원고 불러오기", "새 원고 등록"], horizontal=True, key="pub_sidebar_mode")
            existing_docs = list_publisher_documents(username)
            
            if "pub_current_doc" not in st.session_state:
                st.session_state.pub_current_doc = existing_docs[0] if existing_docs else None
                
            if pub_mode == "원고 불러오기":
                if existing_docs:
                    items_per_page = 5
                    total_items = len(existing_docs)
                    total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
                    
                    if "pub_list_page" not in st.session_state:
                        st.session_state.pub_list_page = 0
                        
                    st.session_state.pub_list_page = max(0, min(st.session_state.pub_list_page, total_pages - 1))
                    
                    start_idx = st.session_state.pub_list_page * items_per_page
                    end_idx = min(start_idx + items_per_page, total_items)
                    
                    page_docs = existing_docs[start_idx:end_idx]
                    
                    st.markdown(f"**🗂️ 원고 목록 ({st.session_state.pub_list_page + 1}/{total_pages} Page)**")
                    
                    for doc in page_docs:
                        col_doc, col_del = st.columns([4, 1])
                        with col_doc:
                            active_style = "👉 " if st.session_state.pub_current_doc == doc else "📄 "
                            if st.button(f"{active_style}{doc}", key=f"pub_btn_load_{doc}"):
                                st.session_state.pub_current_doc = doc
                                doc_data = load_publisher_document(username, doc)
                                st.session_state.pub_raw_text = doc_data.get("raw_text", "")
                                st.session_state.pub_editor_filename = doc_data.get("filename", "")
                                st.session_state.pub_episodes = doc_data.get("episodes", [])
                                st.session_state.pub_editor_edits = doc_data.get("edits", {})
                                st.session_state.pub_local_char_sheet = doc_data.get("char_sheet", "")
                                st.session_state.pub_local_world_setting = doc_data.get("world_setting", "")
                                if "pub_editor_current_ep" not in st.session_state:
                                    st.session_state.pub_editor_current_ep = 0
                                st.rerun()
                        with col_del:
                            if st.button("🗑️", key=f"pub_btn_del_{doc}", help=f"'{doc}' 원고 삭제"):
                                delete_publisher_document(username, doc)
                                if st.session_state.pub_current_doc == doc:
                                    st.session_state.pub_current_doc = None
                                    st.session_state.pub_raw_text = ""
                                    st.session_state.pub_editor_filename = ""
                                    st.session_state.pub_episodes = []
                                    st.session_state.pub_editor_edits = {}
                                    st.session_state.pub_local_char_sheet = ""
                                    st.session_state.pub_local_world_setting = ""
                                st.rerun()
                                
                    p_col1, p_col2 = st.columns(2)
                    with p_col1:
                        if st.button("⬅️ 이전", key="pub_page_prev", disabled=(st.session_state.pub_list_page == 0)):
                            st.session_state.pub_list_page -= 1
                            st.rerun()
                    with p_col2:
                        if st.button("다음 ➡️", key="pub_page_next", disabled=(st.session_state.pub_list_page >= total_pages - 1)):
                            st.session_state.pub_list_page += 1
                            st.rerun()
                else:
                    st.warning("등록된 원고가 없습니다.")
            else:  # 새 원고 등록
                new_doc_title = st.text_input("새 작품 제목", placeholder="제목을 입력하세요")
                st.caption("비워둘 경우 파일 업로드 시 본문에서 자동 추출됩니다.")
                if st.button("새 작업 만들기", key="pub_btn_create_new"):
                    if new_doc_title:
                        clean_title = "".join(ch for ch in new_doc_title if ch.isalnum() or ch in "_- ").strip().replace(" ", "_")
                        save_publisher_document(username, clean_title, {
                            "raw_text": "",
                            "filename": f"{clean_title}.txt",
                            "episodes": [],
                            "edits": {},
                            "char_sheet": "",
                            "world_setting": ""
                        })
                        st.session_state.pub_current_doc = clean_title
                        st.session_state.pub_raw_text = ""
                        st.session_state.pub_editor_filename = f"{clean_title}.txt"
                        st.session_state.pub_episodes = []
                        st.session_state.pub_editor_edits = {}
                        st.session_state.pub_local_char_sheet = ""
                        st.session_state.pub_local_world_setting = ""
                        st.rerun()
                    else:
                        st.error("제목을 입력해 주세요.")
        else:
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
                        "custom_persona_input": "",
                        "apply_plot_style": False
                    })
                    st.session_state.current_project = clean
                    st.query_params["user"] = username
                    st.query_params["project"] = clean
                    # Must preserve token
                    token = st.query_params.get("token", "")
                    if token:
                        st.query_params["token"] = token
                    st.rerun()

    # If no project selected, show welcome screen (except for Publisher Hub)
    if st.session_state.current_page != "📦 Publisher Hub" and not st.session_state.get("current_project"):
        st.title("Welcome! Please create or load a project to start.")
        return

    # ---------- Load project data (once per project change) ----------
    if st.session_state.current_page != "📦 Publisher Hub" and st.session_state.get("current_project"):
        if "loaded_project" not in st.session_state or st.session_state.loaded_project != st.session_state.current_project:
            data = load_project(username, st.session_state.current_project)
            st.session_state.custom_persona_input = data.get("custom_persona_input", "")
            st.session_state.plot_outline = data.get("plot_outline", "")
            st.session_state.char_sheet = data.get("char_sheet", "")
            st.session_state.world_setting = data.get("world_setting", "")
            st.session_state.memory_chain = data.get("memory_chain", [])
            st.session_state.critique = data.get("critique")
            st.session_state.idea_suggestion = data.get("idea_suggestion", "")
            
            # --- Multi-Chapter Support ---
            raw_chapters = data.get("chapters", {})
            # Migration: If it's an old project with only current_story, put it in Chapter 1
            curr_story = data.get("current_story", "")
            if not raw_chapters and curr_story:
                raw_chapters = {"1": curr_story}
            
            st.session_state.chapters = raw_chapters
            if "current_chapter_idx" not in st.session_state:
                # First priority: check saved active chapter
                saved_idx = data.get("current_chapter_idx")
                if saved_idx is not None:
                    st.session_state.current_chapter_idx = int(saved_idx)
                elif raw_chapters:
                    st.session_state.current_chapter_idx = max([int(k) for k in raw_chapters.keys()])
                else:
                    st.session_state.current_chapter_idx = 1
            
            # Sync current_story with the selected chapter
            idx_str = str(st.session_state.current_chapter_idx)
            st.session_state.current_story = st.session_state.chapters.get(idx_str, "")
            # Persist Settings
            st.session_state.setting_temperature = data.get("setting_temperature", 0.7)
            st.session_state.setting_model_writer = data.get("setting_model_writer", data.get("setting_model", "gemini-2.5-pro"))
            st.session_state.setting_model_assistant = data.get("setting_model_assistant", "gemini-2.5-flash")
            st.session_state.setting_style = data.get("setting_style", "기본")
            st.session_state.setting_preset = data.get("setting_preset", "Direct Input")
            # Load structural settings directly from json without guards, as we want file updates to take precedence
            st.session_state.setting_target_vols = data.get("setting_target_vols", 1)
            st.session_state.setting_target_chapters = data.get("setting_target_chapters", 50)
            st.session_state.setting_humor = data.get("setting_humor", 0) # Default 0
            st.session_state.last_prompt = data.get("last_prompt", "")
    
            # Persist Idea Generator
            st.session_state.ig_genre = data.get("ig_genre", "전통로맨스")
            st.session_state.ig_spice = data.get("ig_spice", "19금(없음)")
            st.session_state.ig_style_guide = data.get("ig_style_guide", "빠른 전개,\n짧은 문장,\n짧은 문단,\n대화 중심,\n강한 훅(hook),\n대사 55%,\n행동 25%,\n내면 15%,\n배경 설명 5%")
            st.session_state.ig_moods = data.get("ig_moods", [])
            st.session_state.ig_male = data.get("ig_male", [])
            st.session_state.ig_female = data.get("ig_female", [])
            st.session_state.ig_arc = data.get("ig_arc", "")
            
            # Load RAG settings
            st.session_state.rag_enabled = data.get("rag_enabled", True)
            
            raw_cat_id = data.get("rag_category_id")
            if raw_cat_id in ("", "None", None):
                st.session_state.rag_category_id = None
            else:
                try: st.session_state.rag_category_id = int(raw_cat_id)
                except: st.session_state.rag_category_id = None
                
            raw_series_id = data.get("rag_series_id")
            if raw_series_id in ("", "None", None):
                st.session_state.rag_series_id = None
            else:
                try: st.session_state.rag_series_id = int(raw_series_id)
                except: st.session_state.rag_series_id = None
                
            st.session_state.rag_keyword = data.get("rag_keyword", "")
            if st.session_state.rag_keyword in (None, "None"):
                st.session_state.rag_keyword = ""
                
            st.session_state.rag_series_search_val = ""
            
            # Load additional UI states
            st.session_state.prediction_report = data.get("prediction_report")
            st.session_state.apply_plot_style = data.get("apply_plot_style", False)
            st.session_state.pkg_titles = data.get("pkg_titles", [])
            st.session_state.pkg_blurb = data.get("pkg_blurb", "")
            st.session_state.pkg_keywords = data.get("pkg_keywords", [])
            st.session_state.chapters_settings = data.get("chapters_settings", {})
            st.session_state.review_result = data.get("review_result")
            
            # Load RAG series cache
            series_cache = []
            if st.session_state.rag_category_id is not None:
                series_cache = fetch_rag_series(category_id=st.session_state.rag_category_id)
                
            if st.session_state.rag_series_id is not None:
                already_loaded = any(s["series_id"] == st.session_state.rag_series_id for s in series_cache)
                if not already_loaded:
                    saved_series_list = fetch_rag_series(series_id=st.session_state.rag_series_id)
                    series_cache.extend(saved_series_list)
                    
            st.session_state.rag_series = series_cache
            st.session_state.loaded_project = st.session_state.current_project

    # ---------- Auto‑save helper ----------
    def auto_save() -> None:
        # Check load flag to prevent saving default values before file loading completes
        if st.session_state.get("loaded_project") != st.session_state.get("current_project"):
            return
            
        # Before saving, sync the current_story from UI to the chapters dict
        if "chapters" not in st.session_state:
            st.session_state.chapters = {}
        
        idx_str = str(st.session_state.get("current_chapter_idx", 1))
        st.session_state.chapters[idx_str] = st.session_state.get("current_story", "")

        payload = {
            "current_chapter_idx": st.session_state.get("current_chapter_idx", 1),
            "chapters": st.session_state.chapters, # New multi-chapter field
            "current_story": st.session_state.get("current_story", ""), # Keep for backward compatibility
            "char_sheet": st.session_state.get("char_sheet", ""),
            "world_setting": st.session_state.get("world_setting", ""),
            "memory_chain": st.session_state.get("memory_chain", []),
            "critique": st.session_state.get("critique"),
            "idea_suggestion": st.session_state.get("idea_suggestion", ""),
            "custom_persona_input": st.session_state.get("custom_persona_input", ""),
            # Persist Settings
            "setting_temperature": st.session_state.get("setting_temperature", 0.7),
            "setting_model_writer": st.session_state.get("setting_model_writer", "gemini-2.5-pro"),
            "setting_model_assistant": st.session_state.get("setting_model_assistant", "gemini-2.5-flash"),
            "setting_style": st.session_state.get("setting_style", "기본"),
            "setting_preset": st.session_state.get("setting_preset", "Direct Input"),
            "setting_target_vols": st.session_state.setting_target_vols,
            "setting_target_chapters": st.session_state.setting_target_chapters,
            "setting_humor": st.session_state.setting_humor,
            "last_prompt": st.session_state.get("last_prompt", ""),
            # Persist Idea Generator
            "ig_genre": st.session_state.get("ig_genre", "전통로맨스"),
            "ig_spice": st.session_state.get("ig_spice", "19금(없음)"),
            "ig_style_guide": st.session_state.get("ig_style_guide", "빠른 전개,\n짧은 문장,\n짧은 문단,\n대화 중심,\n강한 훅(hook),\n대사 55%,\n행동 25%,\n내면 15%,\n배경 설명 5%"),
            "ig_moods": st.session_state.get("ig_moods", []),
            "ig_male": st.session_state.get("ig_male", []),
            "ig_female": st.session_state.get("ig_female", []),
            "ig_arc": st.session_state.get("ig_arc", ""),
            "plot_outline": st.session_state.get("plot_outline", ""),
            # RAG Settings
            "rag_enabled": st.session_state.get("rag_enabled", True),
            "rag_category_id": st.session_state.get("rag_category_id"),
            "rag_series_id": st.session_state.get("rag_series_id"),
            "rag_keyword": st.session_state.get("rag_keyword", ""),
            # Additional UI states
            "prediction_report": st.session_state.get("prediction_report"),
            "apply_plot_style": st.session_state.get("apply_plot_style", False),
            "pkg_titles": st.session_state.get("pkg_titles", []),
            "pkg_blurb": st.session_state.get("pkg_blurb", ""),
            "pkg_keywords": st.session_state.get("pkg_keywords", []),
            "chapters_settings": st.session_state.get("chapters_settings", {}),
            "review_result": st.session_state.get("review_result"),
        }
        save_project(username, st.session_state.current_project, payload)

    def on_style_preset_change() -> None:
        new_style = st.session_state.setting_style
        guide_mapping = {
            "기본": "빠른 전개,\n짧은 문장,\n짧은 문단,\n대화 중심,\n강한 훅(hook),\n대사 55%,\n행동 25%,\n내면 15%,\n배경 설명 5%",
            "웹소설체": "빠른 전개,\n짧은 문장,\n짧은 문단,\n대화 중심,\n강한 훅(hook),\n대사 55%,\n행동 25%,\n내면 15%,\n배경 설명 5%",
            "감성적": "서정적인 묘사,\n인물의 내밀한 심리 묘사 강화,\n아련하고 감성적인 분위기,\n풍부한 은유와 감각적 형용사 사용,\n내면 40%,\n배경 설명 30%,\n대사 20%,\n행동 10%",
            "담백한": "불필요한 미사여구 배제,\n간결하고 객관적인 3인칭 묘사,\n대사보다는 행동과 절제된 감정 표현 위주,\n행동 50%,\n내면 20%,\n대사 20%,\n배경 설명 10%",
            "고전": "중후하고 고전적인 문체,\n격식 있는 어조와 어휘 사용,\n세밀한 서사 및 역사/배경 설정 묘사,\n대화보다 깊이 있는 지문 묘사 중심,\n배경 설명 40%,\n내면 30%,\n대사 15%,\n행동 15%",
            "유머러스": "재치 있고 가벼운 대사 티키타카,\n코믹하고 과장된 상황 연출,\n웃음을 자아내는 행동 묘사,\n대사 50%,\n행동 30%,\n내면 10%,\n배경 설명 10%"
        }
        st.session_state.ig_style_guide = guide_mapping.get(new_style, "")
        auto_save()

    # ---------- Settings sidebar ----------
    if st.session_state.current_page != "📦 Publisher Hub":
        with st.sidebar:
            st.markdown("<style>.stProgress {max-width:50%;}</style>", unsafe_allow_html=True)
            st.title("Settings")
            st.caption("⚙️ **프로젝트 기본값 설정**")
            st.caption("이곳의 설정값은 대량 집필(Factory) 모드 및 새로 추가되는 화차의 기본 시작 값으로 적용됩니다. 개별 화차의 스타일 수치는 에디터 본문 하단에서 언제든지 변경할 수 있습니다.")
            temperature = st.slider("기본 창의성 (Default Creativity)", 0.1, 1.0, key="setting_temperature", on_change=auto_save)
            humor_level = st.slider("기본 유머 감각 (Default Humor)", 0, 10, key="setting_humor", help="0: Serious, 10: Hilarious/Slapstick", on_change=auto_save)
            
            # Verify selected models are in options, fallback if not
            default_w_idx = 0
            w_model = st.session_state.get("setting_model_writer", "gemini-2.5-pro")
            if w_model in writer_model_options:
                default_w_idx = writer_model_options.index(w_model)
            else:
                w_model = "gemini-2.5-pro"
                st.session_state.setting_model_writer = w_model
                default_w_idx = writer_model_options.index(w_model)

            default_a_idx = 0
            a_model = st.session_state.get("setting_model_assistant", "gemini-2.5-flash")
            if a_model in assistant_model_options:
                default_a_idx = assistant_model_options.index(a_model)
            else:
                a_model = "gemini-2.5-flash"
                st.session_state.setting_model_assistant = a_model
                default_a_idx = assistant_model_options.index(a_model)

            selected_model_writer = st.selectbox(
                "AI Writer (소설 집필용)", 
                writer_model_options, 
                index=default_w_idx,
                key="setting_model_writer", 
                on_change=auto_save
            )
            selected_model_assistant = st.selectbox(
                "AI Assistant (기획/분석/검수용)", 
                assistant_model_options, 
                index=default_a_idx,
                key="setting_model_assistant", 
                on_change=auto_save
            )
            st.markdown("---")
            st.markdown("✍️ **Writing Style**")
            style_options = ["기본", "웹소설체", "감성적", "담백한", "고전", "유머러스"]
            selected_style = st.selectbox("Style Preset", style_options, key="setting_style", on_change=on_style_preset_change)
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
            
            st.markdown("📅 **Structure**")
            st.number_input(
                "Target Volumes (목표 권수)",
                min_value=1,
                max_value=100,
                key="setting_target_vols",
                on_change=auto_save
            )
            st.number_input(
                "Chapters per Volume (1권당 목표 화수)",
                min_value=1,
                max_value=200,
                key="setting_target_chapters",
                on_change=auto_save
            )
            st.markdown("---")
            
            # RAG Settings Controls
            st.markdown("🔍 **RAG Settings (Supabase pgvector)**")
            with st.expander("RAG 설정 열기", expanded=True):
                rag_enabled = st.checkbox("RAG 참조 활성화", value=st.session_state.rag_enabled, key="rag_enabled_ui")
                if st.session_state.rag_enabled != rag_enabled:
                    st.session_state.rag_enabled = rag_enabled
                    auto_save()
                    
                # Categories (ebook_t)
                categories = st.session_state.get("rag_categories", [])
                cat_options = ["전체 (선택 안 함)"] + [c["cd_tname"] for c in categories]
                
                # Find index of current selected category
                selected_cat_name = "전체 (선택 안 함)"
                selected_cat_id = st.session_state.get("rag_category_id")
                if selected_cat_id is not None:
                    for c in categories:
                        if c["cd_t"] == selected_cat_id:
                            selected_cat_name = c["cd_tname"]
                            break
                
                cat_index = cat_options.index(selected_cat_name) if selected_cat_name in cat_options else 0
                
                # Category selectbox
                sel_cat_name = st.selectbox("장르/카테고리 선택", cat_options, index=cat_index, key="rag_cat_ui")
                
                # Handle category selection change
                new_cat_id = None
                if sel_cat_name != "전체 (선택 안 함)":
                    for c in categories:
                        if c["cd_tname"] == sel_cat_name:
                            new_cat_id = c["cd_t"]
                            break
                
                # If category changed, refresh the series list
                if new_cat_id != st.session_state.rag_category_id:
                    st.session_state.rag_category_id = new_cat_id
                    st.session_state.rag_series = fetch_rag_series(category_id=new_cat_id)
                    st.session_state.rag_series_id = None # Reset series selection
                    st.session_state.rag_series_search_val = "" # Reset search query
                    st.rerun()
                    
                # Series search text input
                search_query_val = st.text_input("도서 제목 검색 (엔터 키 입력)", value=st.session_state.get("rag_series_search_val", ""), key="rag_series_search_ui")
                
                # Detect search query change
                if search_query_val != st.session_state.get("rag_series_search_val", ""):
                    st.session_state.rag_series_search_val = search_query_val
                    
                    # Fetch matching series
                    matched_series = fetch_rag_series(
                        category_id=st.session_state.rag_category_id,
                        search_query=search_query_val
                    )
                    
                    # If specific series is currently selected, preserve it in the options
                    if st.session_state.rag_series_id is not None:
                        already_in = any(s["series_id"] == st.session_state.rag_series_id for s in matched_series)
                        if not already_in:
                            saved_series_list = fetch_rag_series(series_id=st.session_state.rag_series_id)
                            matched_series.extend(saved_series_list)
                            
                    st.session_state.rag_series = matched_series
                    st.rerun()

                # Series list for selectbox options
                series_list = st.session_state.get("rag_series", [])
                series_options = ["전체 (선택 안 함)"] + [s["display_title"] for s in series_list]
                
                selected_series_title = "전체 (선택 안 함)"
                selected_series_id = st.session_state.get("rag_series_id")
                if selected_series_id is not None:
                    for s in series_list:
                        if s["series_id"] == selected_series_id:
                            selected_series_title = s["display_title"]
                            break
                            
                series_index = series_options.index(selected_series_title) if selected_series_title in series_options else 0
                
                sel_series_title = st.selectbox("도서/시리즈 선택", series_options, index=series_index, key="rag_series_ui")
                
                new_series_id = None
                if sel_series_title != "전체 (선택 안 함)":
                    for s in series_list:
                        if s["display_title"] == sel_series_title:
                            new_series_id = s["series_id"]
                            break
                
                if new_series_id != st.session_state.rag_series_id:
                    st.session_state.rag_series_id = new_series_id
                    auto_save()
                    
                # Keyword filter (matches tags or content)
                kw_val = st.text_input("특정 키워드 필터 (태그)", value=st.session_state.rag_keyword, key="rag_keyword_ui")
                if kw_val != st.session_state.rag_keyword:
                    st.session_state.rag_keyword = kw_val
                    auto_save()
                    
            st.markdown("---")
            with st.expander("🧠 장기 기억 (이전 회차 요약)", expanded=False):
                if not st.session_state.get("memory_chain"):
                    st.info("아직 저장된 기억이 없어요.")
                else:
                    for m in st.session_state.memory_chain:
                        ch_num = m.get('chapter', '?')
                        summary_text = m.get('chunk_summary', m.get('summary', ''))
                        ch_updates = m.get('entity_changes', m.get('entity_updates', {}))
                        if not ch_updates:
                            ch_updates = {}
                        
                        char_val = ch_updates.get('characters', '')
                        if isinstance(char_val, dict):
                            char_desc = " / ".join([f"{k}: {v}" for k, v in char_val.items()]) if char_val else "변동 없음"
                        else:
                            char_desc = str(char_val) if char_val else "변동 없음"
                            
                        setting_val = ch_updates.get('settings', ch_updates.get('world', ''))
                        if isinstance(setting_val, dict):
                            setting_desc = " / ".join([f"{k}: {v}" for k, v in setting_val.items()]) if setting_val else "변동 없음"
                        else:
                            setting_desc = str(setting_val) if setting_val else "변동 없음"
                            
                        cliff_str = f"<br><b>🔗 클리프행어</b>: {m.get('cliffhanger_point')}" if m.get('cliffhanger_point') else ""
                        
                        details_html = f"""
                        <details style="margin-bottom: 10px; padding: 8px; border: 1px solid #dfe1e5; border-radius: 6px; background-color: rgba(255,255,255,0.05);">
                            <summary style="cursor: pointer; font-weight: 600; font-size: 0.95rem; list-style-type: none;">📖 제 {ch_num}화 요약 팩</summary>
                            <div style="margin-top: 8px; font-size: 0.88rem; line-height: 1.5; color: #d0d3d4;">
                                <b>📝 요약</b>: {summary_text}<br>
                                <b>👥 인물변화</b>: {char_desc}<br>
                                <b>🌍 설정변화</b>: {setting_desc}
                                {cliff_str}
                            </div>
                        </details>
                        """
                        st.markdown(details_html, unsafe_allow_html=True)
                
                if st.button("현재 본문 요약 저장", key="save_mem"):
                    with st.spinner("요약 중..."):
                        try:
                            res = requests.post(
                                f"{BACKEND_URL}/summarize",
                                json={
                                    "text": st.session_state.get("current_story", ""),
                                    "chapter_num": st.session_state.get("current_chapter_idx", 1),
                                    "model": st.session_state.get("setting_model_assistant", "gemini-2.5-flash")
                                },
                                timeout=60
                            )
                            if res.status_code == 200:
                                if "memory_chain" not in st.session_state:
                                    st.session_state.memory_chain = []
                                
                                # Remove existing summary for this chapter if it exists, to avoid duplicates
                                curr_ch = st.session_state.get("current_chapter_idx", 1)
                                st.session_state.memory_chain = [m for m in st.session_state.memory_chain if m.get("chapter") != curr_ch]
                                
                                st.session_state.memory_chain.append(res.json())
                                # Sort memory chain by chapter number
                                st.session_state.memory_chain.sort(key=lambda x: int(x.get("chapter", 0)))
                                auto_save()
                                st.rerun()
                            else:
                                st.error(res.text)
                        except Exception as e:
                            st.error(e)
                
                if st.button("기억 초기화", key="clear_mem"):
                    st.session_state.memory_chain = []
                    auto_save()
                    st.rerun()

            # --- 전체 화차 네비게이션 및 진척도 표시 (사이드바 하단 추가) ---
            st.markdown("---")
            st.markdown("### 📖 전체 화차 진행 현황")
            available_chaps = sorted([int(k) for k in st.session_state.get("chapters", {}).keys()]) if st.session_state.get("chapters") else [1]
            current_idx = st.session_state.get("current_chapter_idx", 1)
            total_chaps = max(available_chaps) if available_chaps else 1
            
            # 1. 진척도 프로그레스바
            progress_val = float(current_idx) / float(total_chaps) if total_chaps > 0 else 0.0
            st.progress(min(progress_val, 1.0))
            st.caption(f"**현재 위치**: 제 {current_idx}화 / 전체 {total_chaps}화")
            
            # 2. 이전화/다음화 간편 이동 버튼
            col_nav_1, col_nav_2 = st.columns(2)
            with col_nav_1:
                if st.button("◀ 이전 화", use_container_width=True, disabled=(current_idx <= 1)):
                    auto_save()
                    st.session_state.current_chapter_idx = current_idx - 1
                    st.session_state.current_story = st.session_state.chapters.get(str(current_idx - 1), "")
                    st.session_state.last_prompt = ""
                    if "next_prompt_options" in st.session_state:
                        del st.session_state.next_prompt_options
                    auto_save()
                    st.rerun()
            with col_nav_2:
                if st.button("다음 화 ▶", use_container_width=True, disabled=(current_idx >= total_chaps)):
                    auto_save()
                    st.session_state.current_chapter_idx = current_idx + 1
                    st.session_state.current_story = st.session_state.chapters.get(str(current_idx + 1), "")
                    st.session_state.last_prompt = ""
                    if "next_prompt_options" in st.session_state:
                        del st.session_state.next_prompt_options
                    auto_save()
                    st.rerun()

            st.markdown("---")
            with st.expander("Help"):
                st.write("1. Create Project\n2. Fill Character Sheet\n3. Generate Story\n4. Save Memory")

    # ---------- Main UI ----------
    if st.session_state.current_page == "📦 Publisher Hub":
        st.title("📦 Publisher Hub (출판 허브)")
    else:
        st.title(f"💖 Romance AI: {st.session_state.current_project}")
    
    pages = ["✍️ Story Engine", "🏭 Novel Factory (Batch)", "🧐 Editor's Desk", "🎨 Art Studio", "📦 Publisher Hub"]
    selected_page = st.radio(
        "Navigation",
        pages,
        index=pages.index(st.session_state.current_page) if st.session_state.current_page in pages else 0,
        horizontal=True,
        label_visibility="collapsed",
        key="main_navigation_radio"
    )
    if selected_page != st.session_state.current_page:
        st.session_state.current_page = selected_page
        st.rerun()

    # ==========================================
    # TAB 1: STORY ENGINE (Classic)
    # ==========================================
    if st.session_state.current_page == "✍️ Story Engine":
        col1, col2 = st.columns([2, 1])

        # ----- Left column – core workflow -----
        with col1:
            # Chapter Selector
            st.markdown("### 📖 Chapter Management")
            
            # Get available chapters (numeric sorted)
            available_chapters = sorted([int(k) for k in st.session_state.chapters.keys()]) if st.session_state.get("chapters") else [1]
            chapter_options = [f"제 {i}화" for i in available_chapters] + ["📖 전체 본문 보기 (Full Draft)"]
            
            # Find current index
            curr_idx = st.session_state.get("current_chapter_idx", 1)
            selected_label = f"제 {curr_idx}화"
            if selected_label not in chapter_options:
                default_idx = 0
            else:
                default_idx = chapter_options.index(selected_label)
            
            def on_chapter_change():
                sel = st.session_state.chapter_picker
                if "전체 본문 보기" in sel:
                    st.session_state.view_all_mode = True
                else:
                    st.session_state.view_all_mode = False
                    new_idx = int(re.search(r'\d+', sel).group())
                    # Auto-save current before switching
                    auto_save()
                    st.session_state.current_chapter_idx = new_idx
                    # Load the new content
                    st.session_state.current_story = st.session_state.chapters.get(str(new_idx), "")
                    st.session_state.last_prompt = ""
                    if "next_prompt_options" in st.session_state:
                        del st.session_state.next_prompt_options
                    auto_save()

            # Chapter Picker and Management Buttons
            col_picker, col_del, col_reset = st.columns([2, 1, 1])
            with col_picker:
                selected_chapter_ui = st.selectbox(
                    "편집할 화차를 선택하세요",
                    chapter_options,
                    index=default_idx,
                    key="chapter_picker",
                    on_change=on_chapter_change
                )
            with col_del:
                st.write("") # Spacing alignment
                st.write("")
                if st.button("🗑️ 현재 화차 삭제", use_container_width=True, help="현재 선택된 화차를 삭제하고 챕터 순서를 당깁니다."):
                    curr_idx = st.session_state.current_chapter_idx
                    if "chapters" in st.session_state and str(curr_idx) in st.session_state.chapters:
                        del st.session_state.chapters[str(curr_idx)]
                        
                        # Re-index remaining chapters to close the gap
                        old_chaps = st.session_state.chapters
                        new_chaps = {}
                        for new_i, old_k in enumerate(sorted([int(k) for k in old_chaps.keys()]), start=1):
                            new_chaps[str(new_i)] = old_chaps[str(old_k)]
                        st.session_state.chapters = new_chaps
                        
                        # Reset index to previous chapter or 1, capped by available chapters
                        new_idx = max(1, curr_idx - 1)
                        if new_chaps and str(new_idx) not in new_chaps:
                            new_idx = max([int(k) for k in new_chaps.keys()])
                        st.session_state.current_chapter_idx = new_idx
                        st.session_state.current_story = st.session_state.chapters.get(str(new_idx), "")
                        auto_save()
                        st.success("화차가 성공적으로 삭제 및 정렬되었습니다.")
                        st.rerun()
            with col_reset:
                st.write("") # Spacing alignment
                st.write("")
                if st.button("🧹 전체 초기화", use_container_width=True, help="전체 챕터 본문을 삭제하고 1화부터 다시 작성합니다."):
                    st.session_state.chapters = {}
                    st.session_state.current_chapter_idx = 1
                    st.session_state.current_story = ""
                    auto_save()
                    st.success("전체 집필 챕터가 초기화되었습니다.")
                    st.rerun()

            # --- 기존 Plot Outline을 바탕으로 화차 구조 동적 생성/빌드 버튼 추가 ---
            if st.session_state.get("plot_outline"):
                if st.button("🛠️ 현재 Plot Outline 기반으로 화차 구조 생성/복원", use_container_width=True, help="기존 생성된 Plot Outline 또는 1권당 목표 화수 설정에 맞추어 전체 화차 구조를 즉시 자동 생성합니다."):
                    plot_text = st.session_state.plot_outline
                    matches = re.findall(r'(?:제\s*(\d+)\s*화|Chapter\s*(\d+))', plot_text, re.IGNORECASE)
                    found_indices = []
                    for m in matches:
                        idx_str = m[0] or m[1]
                        if idx_str:
                            found_indices.append(int(idx_str))
                    
                    target_chaps_limit = int(st.session_state.get("setting_target_chapters", 50))
                    
                    if not found_indices or len(found_indices) < 2:
                        found_indices = list(range(1, target_chaps_limit + 1))
                    else:
                        found_indices = sorted(list(set(found_indices)))
                        if len(found_indices) < target_chaps_limit:
                            for idx in range(1, target_chaps_limit + 1):
                                if idx not in found_indices:
                                    found_indices.append(idx)
                            found_indices = sorted(found_indices)
                    
                    # 기존에 작성 중이던 챕터 데이터 보존하면서 없는 챕터만 빈 값으로 초기화
                    if "chapters" not in st.session_state or not st.session_state.chapters:
                        st.session_state.chapters = {}
                    for i in found_indices:
                        if str(i) not in st.session_state.chapters:
                            st.session_state.chapters[str(i)] = ""
                            
                    st.session_state.current_chapter_idx = found_indices[0] if found_indices else 1
                    st.session_state.current_story = st.session_state.chapters.get(str(st.session_state.current_chapter_idx), "")
                    auto_save()
                    st.success(f"총 {len(found_indices)}화 분량의 화차 구조가 성공적으로 구성되었습니다!")
                    st.rerun()

            if st.session_state.get("view_all_mode"):
                st.markdown("---")
                st.markdown("### 📜 전체 원고 미리보기")
                all_text = ""
                for i in sorted([int(k) for k in st.session_state.chapters.keys()]):
                    all_text += f"## Chapter {i}\n\n" + st.session_state.chapters.get(str(i), "") + "\n\n"
                st.text_area("Read-only Full Story", value=all_text, height=600, disabled=True)
                st.info("💡 개별 회차를 수정하려면 위 선택박스에서 해당 회차를 선택해 주세요.")
            else:
                # Main Story Editor for the selected chapter
                col_editor_title, col_save_btn = st.columns([3, 1])
                with col_editor_title:
                    st.markdown(f"### ✍️ 제 {st.session_state.current_chapter_idx}화 집필 중")
                with col_save_btn:
                    if st.button("💾 프로젝트 저장", use_container_width=True, help="현재 수정한 텍스트 및 모든 설정을 즉시 디스크에 저장합니다."):
                        if "story_editor_ui" in st.session_state:
                            st.session_state.current_story = st.session_state.story_editor_ui
                        auto_save()
                        st.toast("프로젝트가 성공적으로 저장되었습니다! 💾")
                
                st.session_state.current_story = st.text_area(
                    "Story Text",
                    value=st.session_state.current_story,
                    height=500,
                    placeholder="여기에 소설 내용을 작성하거나 AI로 생성하세요...",
                    key="story_editor_ui",
                    on_change=auto_save
                )
                st.caption("💡 작성 중인 내용을 저장하려면 입력창 바깥을 누르거나 `Ctrl + Enter`를 누르세요. 혹은 우측 상단의 **[💾 프로젝트 저장]** 버튼을 클릭하세요.")
# (Previous Story Bible and Idea Generator expanders follow below...)
            # Story Bible
            with st.expander("📚 Story Bible", expanded=True):
                c1, c2 = st.columns(2)
                with c1:
                    st.text_area(
                        "Character Sheet",
                        value=st.session_state.get("char_sheet", ""),
                        key="char_sheet_input",
                        height=350,
                        placeholder="예시:\n- 김철수: 24세, 까칠한 천재 해커. 과거의 상처가 있음.\n- 이영희: 28세, 열정적인 형사. 철수를 의심하지만 끌림.",
                        on_change=lambda: [st.session_state.update({"char_sheet": st.session_state.char_sheet_input}), auto_save()],
                    )
                with c2:
                    st.text_area(
                        "World Setting",
                        value=st.session_state.get("world_setting", ""),
                        key="world_setting_input",
                        height=350,
                        placeholder="예시:\n- 플로팅 아일랜드: 하늘에 떠 있는 3개의 거대 섬.\n- 마법 설정: 왕족만 별의 마법을 쓸 수 있음.",
                        on_change=lambda: [st.session_state.update({"world_setting": st.session_state.world_setting_input}), auto_save()],
                    )

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
                    pass
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
                
                if "ig_style_guide" not in st.session_state:
                    st.session_state.ig_style_guide = "빠른 전개,\n짧은 문장,\n짧은 문단,\n대화 중심,\n강한 훅(hook),\n대사 55%,\n행동 25%,\n내면 15%,\n배경 설명 5%"
                style_guide = st.text_area(
                    "스타일 가이드:",
                    value=st.session_state.ig_style_guide,
                    height=180,
                    key="ig_style_guide",
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
                                    "model": selected_model_assistant,
                                    "apply_trends": True,
                                    "moods": selected_moods,
                                    "male_tags": selected_male,
                                    "female_tags": selected_female,
                                    "arc": char_arc,
                                    "char_sheet": st.session_state.get("char_sheet", ""),
                                    "world_setting": st.session_state.get("world_setting", "")
                                }, timeout=120,
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
                        key="idea_suggestion_input",
                        on_change=lambda: [st.session_state.update({"idea_suggestion": st.session_state.idea_suggestion_input}), auto_save()]
                    )

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
                                "trends": st.session_state.get("ig_style_guide", ""),
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
                                        "model": selected_model_assistant
                                    }, timeout=120
                                )
                                if res.status_code == 200:
                                    pkg = res.json()
                                    st.session_state.pkg_titles = pkg.get("titles", [])
                                    st.session_state.pkg_blurb = pkg.get("blurb", "")
                                    st.session_state.pkg_keywords = pkg.get("keywords", [])
                                    auto_save()
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
                
                # Checkbox OUTSIDE the button block so it persists when clicked
                apply_styles_to_plot = st.checkbox("⚙️ Apply Writer Settings (Style Preset, Humor, Persona) to Plot", key="apply_plot_style", on_change=auto_save)
                
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
                                "trends": st.session_state.get("ig_style_guide", ""),
                                "idea_premise": st.session_state.get("idea_suggestion", "") # Pass the generated idea!
                            }
                            
                            if apply_styles_to_plot:
                                settings_payload["style"] = selected_style
                                settings_payload["persona"] = st.session_state.custom_persona_input
                                settings_payload["humor_level"] = st.session_state.setting_humor
                            
                            try:
                                res = requests.post(f"{BACKEND_URL}/analyze/plot", json={"settings": settings_payload, "model": selected_model_assistant}, timeout=120)
                                if res.status_code == 200:
                                    plot_text = res.json().get("plot", "")
                                    st.session_state.plot_outline = plot_text
                                    
                                    # Parse plot text to extract chapters (e.g. 제1화, 제2화, Chapter 1, Chapter 2)
                                    matches = re.findall(r'(?:제\s*(\d+)\s*화|Chapter\s*(\d+))', plot_text, re.IGNORECASE)
                                    found_indices = []
                                    for m in matches:
                                        idx_str = m[0] or m[1]
                                        if idx_str:
                                            found_indices.append(int(idx_str))
                                    
                                    # Use target chapter setting (Default 50 if not specified)
                                    target_chaps_limit = int(st.session_state.get("setting_target_chapters", 50))
                                    
                                    # If no explicit chapter markers found, or the count is very small, default to setting range
                                    if not found_indices or len(found_indices) < 2:
                                        found_indices = list(range(1, target_chaps_limit + 1))
                                    else:
                                        found_indices = sorted(list(set(found_indices)))
                                        # Ensure we match at least the configured target chapters limit
                                        if len(found_indices) < target_chaps_limit:
                                            for idx in range(1, target_chaps_limit + 1):
                                                if idx not in found_indices:
                                                    found_indices.append(idx)
                                            found_indices = sorted(found_indices)
                                    
                                    # Populate session chapters
                                    st.session_state.chapters = {str(i): "" for i in found_indices}
                                    st.session_state.current_chapter_idx = found_indices[0] if found_indices else 1
                                    st.session_state.current_story = ""
                                    
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

                # --- 🔄 Sync Outline & Blurb ---
                if st.button("🔄 바뀐 설정에 맞게 줄거리/시놉시스 동기화 검증", use_container_width=True):
                    with st.spinner("설정 모순 분석 및 동기화된 플롯 제안서 생성 중..."):
                        try:
                            res_sync = requests.post(
                                f"{BACKEND_URL}/analyze/consistency/sync-outline",
                                json={
                                    "char_sheet": st.session_state.get("char_sheet", ""),
                                    "world_setting": st.session_state.get("world_setting", ""),
                                    "blurb": st.session_state.get("pkg_blurb", ""),
                                    "plot_outline": st.session_state.get("plot_outline", ""),
                                    "model": selected_model_assistant
                                }, timeout=150
                            )
                            if res_sync.status_code == 200:
                                st.session_state.proposed_sync_resolution = res_sync.json()
                                st.rerun()
                            else:
                                st.error("동기화 분석 실패")
                        except Exception as e:
                            st.error(f"통신 에러: {e}")

                if st.session_state.get("proposed_sync_resolution"):
                    prop_sync = st.session_state.proposed_sync_resolution
                    st.info("💡 **인물/세계관 설정 정렬된 동기화 제안** (사건 전개는 완전 보존)")
                    
                    sync_blurb = prop_sync.get("blurb_synced", "").strip()
                    sync_outline = prop_sync.get("plot_outline_synced", "").strip()
                    
                    col_sync_view1, col_sync_view2 = st.columns(2)
                    with col_sync_view1:
                        st.subheader("📖 동기화된 책 소개 (Blurb)")
                        st.text_area("Synced Blurb Preview", value=sync_blurb, height=180, disabled=True)
                    with col_sync_view2:
                        st.subheader("📝 동기화된 플롯 개요 (Plot Outline)")
                        st.text_area("Synced Outline Preview", value=sync_outline, height=180, disabled=True)
                        
                    col_sync_apply1, col_sync_apply2 = st.columns(2)
                    with col_sync_apply1:
                        if st.button("💾 동기화 제안을 블러브/플롯에 최종 반영", type="primary", use_container_width=True):
                            st.session_state.pkg_blurb = sync_blurb
                            st.session_state.plot_outline = sync_outline
                            auto_save()
                            st.success("줄거리와 시놉시스 동기화 반영 및 저장이 완료되었습니다! 💾")
                            st.session_state.pop("proposed_sync_resolution", None)
                            st.rerun()
                    with col_sync_apply2:
                        if st.button("❌ 동기화 제안 취소", key="cancel_sync_res", use_container_width=True):
                            st.session_state.pop("proposed_sync_resolution", None)
                            st.rerun()



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
                                "trends": st.session_state.get("ig_style_guide", "")
                             }
                             try:
                                 res = requests.post(
                                     f"{BACKEND_URL}/analyze/prediction", 
                                     json={
                                         "settings": settings_payload, 
                                         "outline": st.session_state.plot_outline,
                                         "model": selected_model_assistant
                                     }, timeout=120
                                 )
                                 if res.status_code == 200:
                                     st.session_state.prediction_report = res.json().get("report")
                                     auto_save()
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
                                            "model": selected_model_assistant
                                        }, timeout=120
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
            
            # Reconciled: Use the chapter editor from above, removing the redundant one here.
            
            # --- Interactive Next Prompt Choices ---
            st.markdown("### 🧭 향후 전개 제안받기")
            current_chapter_idx = st.session_state.get("current_chapter_idx", 1)
            
            # [Fix] chapter_plot을 버튼 외부로 빼서 항상 정의되게 함
            chapter_plot = ""
            if st.session_state.get("plot_outline"):
                outline_text = st.session_state.plot_outline
                lines = outline_text.split('\n')
                capture = False
                for line in lines:
                    line_clean = line.replace(" ", "").lower()
                    if f"제{current_chapter_idx}화" in line_clean or f"chapter{current_chapter_idx}" in line_clean:
                        capture = True
                    elif capture and (f"제{current_chapter_idx+1}화" in line_clean or f"chapter{current_chapter_idx+1}" in line_clean):
                        capture = False
                        break
                    if capture:
                        chapter_plot += line + "\n"
            
            if not chapter_plot.strip():
                chapter_plot = "현재 회차의 구체적인 플롯을 찾을 수 없습니다. 전체 흐름에 맞게 추천해 주세요."

            if st.button(f"✨ [제{current_chapter_idx}화] 다음 전개 방향 3가지 추천받기"):
                if not st.session_state.get("plot_outline"):
                    st.warning("먼저 Plot Generator에서 아웃라인(Plot Outline)을 생성해 주세요.")
                else:
                    with st.spinner(f"제{current_chapter_idx}화 플롯을 분석하여 전개 방향을 고민 중입니다..."):
                        recent_mem_list = []
                        for m in st.session_state.get("memory_chain", [])[-3:]:
                            ch_sum = m.get("chunk_summary", m.get("summary", ""))
                            ch_updates = m.get("entity_changes", m.get("entity_updates", {}))
                            ch_cliff = m.get("cliffhanger_point", "")
                            recent_mem_list.append(
                                f"제{m.get('chapter', '?')}화 요약: {ch_sum} | 인물변화: {ch_updates.get('characters', '')} | 설정변화: {ch_updates.get('settings', '')} | 클리프행어: {ch_cliff}"
                            )
                        recent_mem = "\n".join(recent_mem_list)
                        
                        try:
                            res = requests.post(
                                f"{BACKEND_URL}/generate/next_prompts",
                                json={
                                    "chapter_num": current_chapter_idx,
                                    "chapter_outline": chapter_plot,
                                    "recent_memory": recent_mem
                                },
                                timeout=80
                            )
                            if res.status_code == 200:
                                st.session_state.next_prompt_options = res.json().get("options", {})
                            else:
                                st.error(f"Error: {res.text}")
                        except Exception as e:
                            st.error(f"Connection Error: {e}")
            
            if st.session_state.get("next_prompt_options"):
                st.info("💡 **원하는 전개 방향을 선택하세요:**")
                for key, val in st.session_state.next_prompt_options.items():
                    with st.container():
                        st.markdown(f"**👉 {key}**")
                        st.write(val)
                        if st.button(f"'{key}' 선택하기", key=f"btn_opt_{key}"):
                            st.session_state.last_prompt = val
                            del st.session_state.next_prompt_options
                            auto_save()
                            st.rerun()
                st.divider()

            # ⚙️ 현재 회차 집필 맞춤 설정 (Chapter Style Customization)
            curr_idx_str = str(current_chapter_idx)
            if "chapters_settings" not in st.session_state:
                st.session_state.chapters_settings = {}
            
            chap_meta = st.session_state.chapters_settings.get(curr_idx_str, {})
            
            # Default to global settings if not customized yet
            default_temp = chap_meta.get("temperature", st.session_state.get("setting_temperature", 0.7))
            default_humor = chap_meta.get("humor_level", st.session_state.get("setting_humor", 0))
            
            st.markdown(f"⚙️ **제 {current_chapter_idx}화 개별 집필 설정 (Chapter Style Customization)**")
            col_slide1, col_slide2 = st.columns(2)
            with col_slide1:
                chap_temp = st.slider(
                    "창의성 (Creativity Temperature)",
                    0.1, 1.0,
                    value=float(default_temp),
                    key=f"chap_temp_{curr_idx_str}",
                    on_change=auto_save
                )
            with col_slide2:
                chap_humor = st.slider(
                    "유머 감각 (Humor Level)",
                    0, 10,
                    value=int(default_humor),
                    key=f"chap_humor_{curr_idx_str}",
                    on_change=auto_save
                )
            
            # Save local changes
            st.session_state.chapters_settings[curr_idx_str] = {
                "temperature": chap_temp,
                "humor_level": chap_humor
            }

            user_input = st.text_input("Next Prompt (What happens next?):", key="last_prompt", on_change=auto_save)
            
            c1, c2 = st.columns([1, 1])
            with c1:
                if st.button("Generate / Continue"):
                    if user_input:
                        with st.spinner("Writing..."):
                            new_text = generate_story(
                                prompt=user_input, 
                                temperature=chap_temp, 
                                model=selected_model_writer, 
                                style=selected_style, 
                                persona=st.session_state.custom_persona_input,
                                humor_level=chap_humor,
                                chapter_num=current_chapter_idx,
                                ch_focus=chapter_plot,
                                plot_summary=st.session_state.plot_outline,
                                writer_memo=st.session_state.get("writer_memo", "")
                            )
                            if new_text and not new_text.startswith("[Error"):
                                # --- Multi-Chapter Sync ---
                                # Save current chapter content first
                                if "chapters" not in st.session_state:
                                    st.session_state.chapters = {}
                                
                                # Store newly generated text into the current chapter slot
                                st.session_state.chapters[str(current_chapter_idx)] = new_text
                                st.session_state.current_story = new_text
                                
                                # Now, auto-summarize the completed chapter (Long-Term Memory automation)
                                with st.spinner("이전 화차 완료: 요약을 자동으로 생성하여 장기 기억에 추가 중..."):
                                    try:
                                        res_sum = requests.post(
                                            f"{BACKEND_URL}/summarize",
                                            json={
                                                "text": new_text,
                                                "chapter_num": current_chapter_idx,
                                                "model": selected_model_assistant
                                            },
                                            timeout=60
                                        )
                                        if res_sum.status_code == 200:
                                            if "memory_chain" not in st.session_state:
                                                st.session_state.memory_chain = []
                                            st.session_state.memory_chain = [m for m in st.session_state.memory_chain if m.get("chapter") != current_chapter_idx]
                                            st.session_state.memory_chain.append(res_sum.json())
                                            st.session_state.memory_chain.sort(key=lambda x: int(x.get("chapter", 0)))
                                    except Exception as e:
                                        pass
                                
                                # Advance to the next chapter index if it exists or create one
                                next_idx = current_chapter_idx + 1
                                st.session_state.current_chapter_idx = next_idx
                                
                                # Switch current_story view to the next chapter's existing content (if any) or empty
                                st.session_state.current_story = st.session_state.chapters.get(str(next_idx), "")
                                
                                # Clear prompt state via flag (avoids StreamlitAPIException)
                                st.session_state.clear_last_prompt_flag = True
                                if "next_prompt_options" in st.session_state:
                                    del st.session_state.next_prompt_options
                                
                                auto_save()
                                st.rerun()
                            else:
                                if new_text:
                                    st.error(new_text)
                                else:
                                    st.error("오류: AI가 소설을 생성하지 못했습니다. 응답이 비어 있습니다.")
                    else:
                        st.warning("⚠️ 다음 전개 방향(Next Prompt) 입력란에 소설의 다음 흐름 지시사항을 입력하거나, 상단의 추천 제안에서 하나를 선택해 주세요.")
            with c2:
                if st.button("Clear Story"):
                    st.session_state.current_story = ""
                    auto_save()
                    st.rerun()

        # ----- Right column – AI tools -----
        with col2:
            st.subheader("AI Editor Tools")

            # --- [Polish Mode] 문단별 정밀 교정 ---
            # --- [Polish Mode] RAG 기반 스마트 문단 윤색 ---
            with st.expander("💎 RAG 기반 스마트 문단 윤색 (Gemini Polish)", expanded=True):
                st.caption("소설 본문의 각 문단을 DB 로맨스 스타일과 실시간 매칭하여 윤색합니다. 본문 내 ✨강조 문장✨이 있을 경우 해당 부분만 정밀 부분 수술 교정(Surgical Polish)을 수행합니다.")
                
                story_content = st.session_state.current_story
                if not story_content.strip():
                    st.info("먼저 본문을 생성해 주세요.")
                else:
                    # 문단별로 쪼개기
                    paragraphs = [p.strip() for p in story_content.split("\n\n") if p.strip()]
                    
                    for idx, para in enumerate(paragraphs):
                        # [V7 Normalize Markers] Convert ✨ to tags internally if user used them
                        if "✨" in para:
                            # If they have 2+ sparkles, wrap the middle part
                            parts = para.split("✨")
                            if len(parts) >= 3:
                                # First ✨ becomes <STYLE>, second becomes </STYLE>
                                para = f"{parts[0]}<STYLE>{parts[1]}</STYLE>{''.join(parts[2:])}"
                        
                        # <STYLE> 태그가 포함된 경우 하이라이트
                        is_highlighted = "<STYLE>" in para or "<style>" in para
                        
                        st.markdown(f"**문단 {idx + 1}**")
                        clean_para = para.replace("<STYLE>", "✨").replace("</STYLE>", "✨")
                        
                        if is_highlighted:
                            st.warning("💡 **스타일 교정 추천 구간:**\n\n" + clean_para)
                        else:
                            st.info(clean_para)
                        
                        # 각 문단별 교정 버튼
                        col_btn1, col_btn2 = st.columns([1, 1])
                        with col_btn1:
                            if st.button(f"✨ 교정안 생성", key=f"polish_btn_{idx}"):
                                with st.spinner("RAG 스타일을 분석하며 문체를 다듬는 중..."):
                                    # [Surgical Polish Check] 
                                    target_text_para = para
                                    surgical_data = None
                                    
                                    if "<STYLE>" in para and "</STYLE>" in para:
                                        try:
                                            match = re.search(r'(.*?)<STYLE>(.*?)</STYLE>(.*)', para, re.DOTALL)
                                            if match:
                                                prefix, marked, suffix = match.groups()
                                                target_text_para = marked.strip()
                                                surgical_data = {"prefix": prefix, "suffix": suffix}
                                                st.session_state[f"surgical_info_{idx}"] = surgical_data
                                        except:
                                            pass
                                    
                                    # Gather RAG parameters
                                    rag_enabled, rag_category_id, rag_series_id, rag_keyword = get_clean_rag_params()
                                    payload = {
                                        "paragraph": target_text_para,
                                        "text": target_text_para,
                                        "model": selected_model_assistant,
                                        "rag_enabled": rag_enabled,
                                        "rag_category_id": rag_category_id,
                                        "rag_series_id": rag_series_id,
                                        "rag_keyword": rag_keyword
                                    }
                                    # Strip None values to prevent 422 errors
                                    payload = {k: v for k, v in payload.items() if v is not None}
                                    
                                    try:
                                        res = requests.post(
                                            f"{BACKEND_URL}/generate/polish",
                                            json=payload,
                                            timeout=120
                                        )
                                        if res.status_code == 200:
                                            st.session_state[f"polish_options_{idx}"] = res.json().get("options", {})
                                        else:
                                            st.error(f"서버 오류: {res.text}")
                                    except Exception as e:
                                        st.error(f"연결 오류: {e}")
                        
                        # 교정안이 있을 경우 표시
                        opt_key = f"polish_options_{idx}"
                        if opt_key in st.session_state:
                            st.markdown("---")
                            opts = st.session_state[opt_key]
                            for label, text in opts.items():
                                with st.container():
                                    st.markdown(f"**{label}**")
                                    st.write(text)
                                    if st.button("이 버전으로 교체하기", key=f"apply_{idx}_{label}"):
                                        # 본문 교체 로직 (Surgical or Full Paragraph)
                                        s_info = st.session_state.get(f"surgical_info_{idx}")
                                        if s_info:
                                            # Replace only the part inside the markers
                                            new_para = f"{s_info['prefix']}<STYLE>{text}</STYLE>{s_info['suffix']}"
                                            paragraphs[idx] = new_para
                                            del st.session_state[f"surgical_info_{idx}"]
                                        else:
                                            paragraphs[idx] = text
                                            
                                        st.session_state.current_story = "\n\n".join(paragraphs)
                                        del st.session_state[opt_key] # 사용 완료 후 삭제
                                        auto_save()
                                        st.success("교체 완료!")
                                        st.rerun()
                            if st.button("닫기", key=f"close_opt_{idx}"):
                                del st.session_state[opt_key]
                                st.rerun()
                        st.divider()

            # Critique & Auto-Fix
            st.markdown("### 🕵️‍♂️ Auto-Editor")
            
            current_num = st.session_state.get("current_chapter_idx", 1)
            st.markdown(f"📍 **분석 대상**: 제 {current_num}화 (현재 집필 중인 본문)")
            
            # Target text is strictly the current story chapter
            target_text = st.session_state.get("current_story", "")
            if not target_text.strip() and "chapters" in st.session_state:
                target_text = st.session_state.chapters.get(str(current_num), "")

            # ✍️ Spell Checker
            st.markdown("### ✍️ Spell Checker (맞춤법 검사)")
            if st.button("Run Spell Check", key="run_spell_check_story_engine"):
                if not target_text.strip():
                    st.warning("검사할 본문 내용이 비어 있습니다.")
                else:
                    with st.spinner("맞춤법 및 문장 검사 중..."):
                        try:
                            res = requests.post(
                                f"{BACKEND_URL}/publisher/check-spell",
                                json={"text": target_text, "model": selected_model_assistant},
                                timeout=120,
                            )
                            if res.status_code == 200:
                                st.session_state.story_engine_spell_report = res.json().get("report", "")
                                auto_save()
                                st.rerun()
                            else:
                                st.error(res.text)
                        except Exception as e:
                            st.error(f"통신 에러: {e}")

            if st.session_state.get("story_engine_spell_report"):
                with st.expander("맞춤법 및 문장 교정 결과", expanded=True):
                    st.markdown(st.session_state.story_engine_spell_report)
                    if st.button("결과 닫기", key="close_spell_report"):
                        del st.session_state.story_engine_spell_report
                        st.rerun()
            st.markdown("---")

            # Determine Sliding Window Context (Preceding summaries and entity updates)
            # Fetch preceding N-1 and N-2 chapter summaries
            prev_summaries = [m for m in st.session_state.get("memory_chain", []) if int(m.get("chapter", 0)) < current_num][-2:]
            sliding_context_list = []
            for m in prev_summaries:
                ch_sum = m.get('chunk_summary', m.get('summary', ''))
                ch_updates = m.get('entity_changes', m.get('entity_updates', {}))
                ch_cliff = m.get('cliffhanger_point', '')
                sliding_context_list.append(
                    f"[제{m.get('chapter')}화 초정밀 요약]: {ch_sum}\n"
                    f"[인물 변동]: {ch_updates.get('characters', '')}\n"
                    f"[설정/아이템 변동]: {ch_updates.get('settings', ch_updates.get('world', ''))}\n"
                    f"[클리프행어]: {ch_cliff}"
                )
            sliding_context = "\n\n".join(sliding_context_list)

            if st.button("Run Deep Analysis", key="run_deep_analysis_auto_editor"):
                if not target_text.strip():
                    st.warning("분석할 본문 내용이 비어 있습니다.")
                else:
                    st.session_state.analysis_target_text = target_text
                    
                    with st.spinner(f"제{current_num}화 분석 중 ({len(target_text)}자)..."):
                        try:
                            analysis_prompt = target_text
                            if sliding_context:
                                analysis_prompt = f"--- [이전 화들 정보 (컨텍스트)] ---\n{sliding_context}\n\n--- [분석 대상 본문] ---\n{target_text}"
                            
                            res = requests.post(
                                f"{BACKEND_URL}/analyze/review",
                                json={"text": analysis_prompt, "model": selected_model_assistant}, timeout=120,
                            )
                            if res.status_code == 200:
                                st.session_state.critique_json = res.json()
                                scores = st.session_state.critique_json.get("scores", {})
                                feedback = st.session_state.critique_json.get("feedback", {})
                                display_text = f"**Scores**: Consistency {scores.get('consistency')}, Creativity {scores.get('creativity')}\n\n"
                                display_text += f"**Feedback**: {feedback}\n\n"
                                display_text += f"**Overall**: {st.session_state.critique_json.get('overall_critique')}"
                                st.session_state.critique = display_text
                                auto_save()
                            else:
                                st.error(res.text)
                        except Exception as e:
                            st.error(f"Analysis Error: {e}")

            if st.session_state.get("critique"):
                with st.expander("View Analysis Report", expanded=True):
                    st.write(st.session_state.critique)
                    
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
                                        rag_enabled, rag_category_id, rag_series_id, rag_keyword = get_clean_rag_params()
                                        res = requests.post(
                                            f"{BACKEND_URL}/generate/rewrite",
                                            json={
                                                "text": target_text, 
                                                "critique": st.session_state.critique_json,
                                                "model": selected_model_assistant,
                                                "chars": st.session_state.get("char_sheet", "기본 인물"),
                                                "world": st.session_state.get("world_setting", "기본 세계관"),
                                                "style_guide": st.session_state.get("ig_style_guide", ""),
                                                "rag_enabled": rag_enabled,
                                                "rag_category_id": rag_category_id,
                                                "rag_series_id": rag_series_id,
                                                "rag_keyword": rag_keyword
                                            }, timeout=3600
                                        )
                                        if res.status_code == 200:
                                            new_text = res.json().get("rewritten_text")
                                            if new_text and len(new_text) > 100:
                                                clean_new = new_text.strip()
                                                terminal_punctuations = ('.', '!', '?', '”', '"', '…', '~', '*', '>', '}')
                                                is_truncated = False
                                                if clean_new and not clean_new.endswith(terminal_punctuations):
                                                    is_truncated = True
                                                
                                                # Check if too much text was cut off compared to original
                                                if len(target_text) > 500 and len(clean_new) < len(target_text) * 0.4:
                                                    is_truncated = True
                                                    
                                                if is_truncated:
                                                    st.error("⚠️ AI가 생성한 문장이 중간에 잘린 것(으르렁거리며... 등)으로 감지되었습니다. 원본 원고 손실을 막기 위해 교정을 반영하지 않았습니다. 다시 한 번 버튼을 눌러 시도해 주세요.")
                                                else:
                                                    # Save to proposed state for previewing & user final acceptance
                                                    st.session_state.auto_editor_proposed_fix = new_text
                                                    st.success("✨ 교정안 생성 완료! 아래 검토 탭에서 확인해 주세요.")
                                                    st.rerun()
                                            else:
                                                st.error("Rewrite returned empty text.")
                                        else:
                                            st.error(res.text)
                                    except Exception as e:
                                        st.error(f"Rewrite Error: {e}")

            # Preview Proposed Auto-Fix and require manual approval before final sync
            if st.session_state.get("auto_editor_proposed_fix"):
                st.markdown("---")
                st.markdown("### 🔄 교정안 비교 및 최종 검토")
                st.info("수정본을 확인 및 편집하신 뒤 [교정안 반영] 버튼을 눌러 적용해 주세요.")
                
                with st.expander("원래 작성한 본문 보기", expanded=False):
                    st.text_area("원본", value=st.session_state.get("analysis_target_text", ""), height=200, disabled=True, key="auto_editor_orig_preview")
                
                proposed_text = st.text_area("AI 수정 제안 (본문 덮어쓰기 전 편집 가능)", value=st.session_state.auto_editor_proposed_fix, height=350, key="auto_editor_fix_preview")
                
                col_fix_1, col_fix_2 = st.columns(2)
                with col_fix_1:
                    if st.button("✅ 교정안 반영", key="auto_editor_accept"):
                        st.session_state.chapters[str(current_num)] = proposed_text
                        st.session_state.current_story = proposed_text
                        
                        # Background call to extract new precision metadata & updates for the fixed chapter
                        with st.spinner("교정된 본문의 초정밀 요약을 자동 갱신 중..."):
                            try:
                                sum_res = requests.post(
                                    f"{BACKEND_URL}/summarize",
                                    json={
                                        "text": proposed_text,
                                        "chapter_num": current_num,
                                        "model": selected_model_assistant
                                    }, timeout=60
                                )
                                if sum_res.status_code == 200:
                                    if "memory_chain" not in st.session_state:
                                        st.session_state.memory_chain = []
                                    st.session_state.memory_chain = [m for m in st.session_state.memory_chain if m.get("chapter") != current_num]
                                    st.session_state.memory_chain.append(sum_res.json())
                                    st.session_state.memory_chain.sort(key=lambda x: int(x.get("chapter", 0)))
                            except Exception as e:
                                st.warning(f"장기 기억 요약 갱신 실패: {e}")
                                
                        # Cleanup proposed draft states and refresh screen
                        del st.session_state.auto_editor_proposed_fix
                        if "critique" in st.session_state:
                            del st.session_state.critique
                        auto_save()
                        st.success("교정이 본문에 성공적으로 반영되었습니다! 💾")
                        st.rerun()
                with col_fix_2:
                    if st.button("❌ 취소", key="auto_editor_cancel"):
                        del st.session_state.auto_editor_proposed_fix
                        st.rerun()
            # Consistency
            if st.button("🕵️ Consistency Check"):
                if st.session_state.current_story:
                    with st.spinner("Checking..."):
                        try:
                            # Enrich character sheet and world setting with preceding memory chain updates
                            enriched_chars = st.session_state.char_sheet
                            enriched_world = st.session_state.world_setting
                            
                            current_num = st.session_state.get("current_chapter_idx", 1)
                            prev_memories = [m for m in st.session_state.get("memory_chain", []) if int(m.get("chapter", 0)) < current_num]
                            
                            if prev_memories:
                                enriched_chars += "\n\n[이전 화차들 인물 변동/감정선 누적 상태]"
                                enriched_world += "\n\n[이전 화차들 설정/배경 변동 상태]"
                                for m in prev_memories:
                                    ch_num = m.get("chapter", 0)
                                    ch_sum = m.get("chunk_summary", "")
                                    ch_updates = m.get("entity_changes", {})
                                    ch_cliff = m.get("cliffhanger_point", "")
                                    
                                    enriched_chars += f"\n- 제{ch_num}화: {ch_updates.get('characters', '')} (요약: {ch_sum})"
                                    enriched_world += f"\n- 제{ch_num}화: {ch_updates.get('settings', '')} (클리프행어: {ch_cliff})"

                            res = requests.post(
                                f"{BACKEND_URL}/analyze/consistency",
                                json={
                                    "text": st.session_state.current_story,
                                    "char_sheet": enriched_chars,
                                    "world_setting": enriched_world,
                                    "model": selected_model_assistant,
                                }, timeout=120,
                            )
                            if res.status_code == 200:
                                st.session_state.consistency_report = res.json().get("report", {})
                                st.session_state.pop("proposed_settings_resolution", None)
                                st.session_state.pop("proposed_story_resolution", None)
                                st.rerun()
                            else:
                                st.error(res.text)
                        except Exception as e:
                            st.error(f"Conn Error: {e}")

            if st.session_state.get("consistency_report"):
                report = st.session_state.consistency_report
                if report.get("name_errors"):
                    st.error(f"⚠️ 인물명/호칭 오류: {report['name_errors']}")
                else:
                    st.success("✅ 인물명 및 호칭 일관성 확인 완료")
                    
                if report.get("plot_errors"):
                    st.warning(f"⚠️ 설정/스토리 모순 감지: {report['plot_errors']}")
                    
                    st.markdown("### 🛠️ 모순 자동 조치")
                    col_act1, col_act2 = st.columns(2)
                    with col_act1:
                        if st.button("⚙️ Option A: 설정 자동 업데이트", use_container_width=True):
                            with st.spinner("설정 보완 제안 생성 중..."):
                                try:
                                    res_set = requests.post(
                                        f"{BACKEND_URL}/analyze/consistency/resolve-setting",
                                        json={
                                            "char_sheet": st.session_state.char_sheet,
                                            "world_setting": st.session_state.world_setting,
                                            "plot_errors": report.get("plot_errors", []),
                                            "model": selected_model_assistant
                                        }, timeout=120
                                    )
                                    if res_set.status_code == 200:
                                        st.session_state.proposed_settings_resolution = res_set.json()
                                        st.session_state.pop("proposed_story_resolution", None)
                                        st.rerun()
                                    else:
                                        st.error("설정 제안 생성 실패")
                                except Exception as e:
                                    st.error(f"통신 에러: {e}")
                                    
                    with col_act2:
                        if st.button("✍️ Option B: 본문 자동 교정", use_container_width=True):
                            with st.spinner("본문 교정안 생성 중..."):
                                try:
                                    rag_enabled, rag_category_id, rag_series_id, rag_keyword = get_clean_rag_params()
                                    style_guide = st.session_state.get("ig_style_guide", "")
                                    res_story = requests.post(
                                        f"{BACKEND_URL}/analyze/consistency/resolve-story",
                                        json={
                                            "text": st.session_state.current_story,
                                            "char_sheet": st.session_state.char_sheet,
                                            "world_setting": st.session_state.world_setting,
                                            "plot_errors": report.get("plot_errors", []),
                                            "style_guide": style_guide,
                                            "rag_context": rag_keyword,
                                            "model": selected_model_writer
                                        }, timeout=150
                                    )
                                    if res_story.status_code == 200:
                                        st.session_state.proposed_story_resolution = res_story.json().get("revised_text", "")
                                        st.session_state.pop("proposed_settings_resolution", None)
                                        st.rerun()
                                    else:
                                        st.error("본문 교정안 생성 실패")
                                except Exception as e:
                                    st.error(f"통신 에러: {e}")

                    if st.session_state.get("proposed_settings_resolution"):
                        prop = st.session_state.proposed_settings_resolution
                        st.info("💡 **인물/세계관 설정 보완 제안** (모순이 보완되어 합쳐진 전체 설정안)")
                        c_merged = prop.get("char_sheet_merged", "").strip()
                        w_merged = prop.get("world_setting_merged", "").strip()
                        
                        if c_merged:
                            st.text_area("보완 통합된 캐릭터 시트", value=c_merged, height=200, disabled=True)
                        if w_merged:
                            st.text_area("보완 통합된 세계관 설정", value=w_merged, height=200, disabled=True)
                        
                        col_set_apply1, col_set_apply2 = st.columns(2)
                        with col_set_apply1:
                            if st.button("💾 설정을 시트에 자동 반영", type="primary"):
                                if c_merged:
                                    st.session_state.char_sheet = c_merged
                                if w_merged:
                                    st.session_state.world_setting = w_merged
                                auto_save()
                                st.success("설정이 완전히 교체 및 저장되었습니다! 다시 검사해 보세요. 💾")
                                st.session_state.pop("proposed_settings_resolution", None)
                                st.session_state.pop("consistency_report", None)
                                st.rerun()
                        with col_set_apply2:
                            if st.button("❌ 제안 취소", key="cancel_set_res"):
                                st.session_state.pop("proposed_settings_resolution", None)
                                st.rerun()

                    if st.session_state.get("proposed_story_resolution"):
                        revised = st.session_state.proposed_story_resolution
                        st.info("💡 **본문 모순 해결 교정안**")
                        st.text_area("수정된 본문 프리뷰", value=revised, height=300)
                        
                        col_story_apply1, col_story_apply2 = st.columns(2)
                        with col_story_apply1:
                            if st.button("💾 교정안을 본문에 자동 반영", type="primary"):
                                st.session_state.current_story = revised
                                auto_save()
                                st.success("본문이 교정 및 저장되었습니다! 💾")
                                st.session_state.pop("proposed_story_resolution", None)
                                st.session_state.pop("consistency_report", None)
                                st.rerun()
                        with col_story_apply2:
                            if st.button("❌ 제안 취소", key="cancel_story_res"):
                                st.session_state.pop("proposed_story_resolution", None)
                                st.rerun()
                else:
                    st.success("🎉 소설 본문과 설정 간에 모순이 없습니다!")
                            
            # Interactive Polish Mode (문단별 정밀 교정)
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

                    # Check cover image existence
                    cover_file_path = os.path.join(BASE_DATA_DIR, username, st.session_state.current_project, "cover.png")
                    cover_exists = os.path.exists(cover_file_path)
                    if not cover_exists:
                        st.warning("⚠️ 등록된 책 표지 이미지(cover.png)가 없습니다. EPUB를 빌드하면 기본 텍스트 표지로 대체됩니다. 표지를 만들거나 저장하려면 '🎨 Art Studio' 탭을 이용하십시오.")
                    else:
                        st.success("🟢 등록된 표지 이미지(cover.png)가 확인되었습니다. EPUB 전자책 생성 시 표지로 자동 탑재됩니다.")

                    st.markdown("---")

                    # 0. Full TXT (Clean & Simple)
                    if st.button("📄 Download Full TXT"):
                        st.session_state.pop("export_download_data", None)
                        settings_payload = {
                             "title": export_title,
                             "author": export_author,
                             "publisher": export_publisher,
                             "content": st.session_state.current_story,
                             "export_type": "txt"
                        }
                        try:
                            res = requests.post(f"{BACKEND_URL}/export/download", json=settings_payload, timeout=300)
                            if res.status_code == 200:
                                 st.session_state.export_download_data = {
                                     "data": res.content,
                                     "file_name": f"{export_title}.txt",
                                     "mime": "text/plain",
                                     "label": "⬇️ Click to Save TXT"
                                 }
                                 st.rerun()
                            else:
                                st.error(f"Export Failed: {res.text}")
                        except Exception as e:
                            st.error(f"Conn Error: {e}")

                    # 1. Full EPUB
                    if st.button("📘 Download Full EPUB"):
                        st.session_state.pop("export_download_data", None)
                        settings_payload = {
                             "title": export_title,
                             "author": export_author,
                             "publisher": export_publisher,
                             "content": st.session_state.current_story,
                             "export_type": "epub",
                             "cover_image_path": cover_file_path if cover_exists else None
                        }
                        try:
                            res = requests.post(f"{BACKEND_URL}/export/download", json=settings_payload, timeout=300)
                            if res.status_code == 200:
                                 st.session_state.export_download_data = {
                                     "data": res.content,
                                     "file_name": f"{export_title}.epub",
                                     "mime": "application/epub+zip",
                                     "label": "⬇️ Click to Save EPUB"
                                 }
                                 st.rerun()
                            else:
                                st.error(f"Export Failed: {res.text}")
                        except Exception as e:
                            st.error(f"Conn Error: {e}")

                    # 2. Serial TXT (Split)
                    if st.button("✂️ Download Serial TXT (ZIP)"):
                        st.session_state.pop("export_download_data", None)
                        settings_payload = {
                             "title": export_title,
                             "author": export_author,
                             "publisher": export_publisher,
                             "content": st.session_state.current_story,
                             "export_type": "txt_zip"
                        }
                        try:
                            res = requests.post(f"{BACKEND_URL}/export/download", json=settings_payload, timeout=300)
                            if res.status_code == 200:
                                 st.session_state.export_download_data = {
                                     "data": res.content,
                                     "file_name": f"{st.session_state.current_project}_serial_txt.zip",
                                     "mime": "application/zip",
                                     "label": "⬇️ Click to Save ZIP (TXT)"
                                 }
                                 st.rerun()
                            else:
                                st.error(f"Export Failed: {res.text}")
                        except Exception as e:
                            st.error(f"Conn Error: {e}")

                    # 3. Serial EPUB (Split)
                    if st.button("📚 Download Serial EPUB (ZIP)"):
                        st.session_state.pop("export_download_data", None)
                        settings_payload = {
                             "title": export_title,
                             "author": export_author,
                             "publisher": export_publisher,
                             "content": st.session_state.current_story,
                             "export_type": "epub_zip",
                             "cover_image_path": cover_file_path if cover_exists else None
                        }
                        try:
                            res = requests.post(f"{BACKEND_URL}/export/download", json=settings_payload, timeout=300)
                            if res.status_code == 200:
                                 st.session_state.export_download_data = {
                                     "data": res.content,
                                     "file_name": f"{export_title}_serial_epub.zip",
                                     "mime": "application/zip",
                                     "label": "⬇️ Click to Save ZIP (EPUB)"
                                 }
                                 st.rerun()
                            else:
                                st.error(f"Export Failed: {res.text}")
                        except Exception as e:
                            st.error(f"Conn Error: {e}")

                    # Render the persistent download button if data is ready in session state
                    if "export_download_data" in st.session_state:
                        st.markdown("---")
                        down = st.session_state.export_download_data
                        st.download_button(
                            label=down["label"],
                            data=down["data"],
                            file_name=down["file_name"],
                            mime=down["mime"]
                        )
                        if st.button("Clear Download Cache (다운로드 캐시 비우기)"):
                            del st.session_state.export_download_data
                            st.rerun()

    # ==========================================
    # TAB 2: NOVEL FACTORY (Batch)
    # ==========================================
    elif st.session_state.current_page == "🧐 Editor's Desk":
        st.header("🧐 Comprehensive Review & Auto-Fix")
        
        # Select target focus for review
        scope_option = st.radio(
            "Analysis Target",
            ["Entire Story (Map-Reduce Summaries)", "Current Chapter Only"],
            index=0,
            horizontal=True,
            help="Entire Story uses saved hyper-precision chapter summaries. Current Chapter reads target chapter raw text."
        )

        chapter_list = sorted(map(int, st.session_state.chapters.keys())) if st.session_state.get("chapters") else [1]
        
        target_analyze_ch_num = 1
        if scope_option == "Current Chapter Only":
            target_analyze_ch_num = st.selectbox("Select Chapter to Analyze", chapter_list, index=len(chapter_list)-1)

        # 1. Review Section
        if st.button("Run Deep Analysis", key="run_deep_analysis_review"):
             with st.spinner("Analyzing story..."):
                  try:
                      payload = {"model": selected_model_assistant}
                      if scope_option.startswith("Entire"):
                          payload["memory_chain"] = st.session_state.get("memory_chain", [])
                      else:
                          payload["text"] = st.session_state.chapters.get(str(target_analyze_ch_num), "")
                      
                      res = requests.post(
                          f"{BACKEND_URL}/analyze/review_comprehensive",
                          json={
                              "text": payload.get("text"),
                              "memory_chain": payload.get("memory_chain"),
                              "model": payload["model"]
                          }, timeout=120
                      )
                      if res.status_code == 200:
                           st.session_state.review_result = res.json()["review"]
                           auto_save()
                      else:
                           st.error(res.text)
                  except Exception as e:
                      st.error(f"Connection Error: {e}")

        if "review_result" in st.session_state and st.session_state.review_result:
            review = st.session_state.review_result
            if not isinstance(review, dict):
                st.info("비평 원본 데이터:")
                st.write(review)
            else:
                st.subheader(f"Score: {review.get('scores', 'N/A')}")
            
            # Show AI Recommended Chapters to Fix
            rec_chaps = review.get("recommended_chapters", [])
            applied_fixes = review.get("applied_fixes", []) if isinstance(review.get("applied_fixes"), list) else []
            if rec_chaps:
                st.success("🎯 **AI 비평가 선정 추천 교정 대상 화차**")
                for item in rec_chaps:
                    ch_id = int(item.get("chapter", 0))
                    if ch_id in applied_fixes:
                        st.markdown(f"- 🟢 **제 {ch_id}화 (교정 완료)**: {item.get('reason')}")
                    else:
                        st.markdown(f"- 🔴 **제 {ch_id}화 (미반영)**: {item.get('reason')}")
            
            with st.expander("Detailed Critique", expanded=True):
                st.markdown(review.get("feedback"))
                
            with st.expander("Improvement Suggestions"):
                st.markdown(review.get("improvement_suggestions"))

            # 2. Auto-Fix (Rewriting)
            st.markdown("---")
            st.markdown("### 🛠️ Auto-Fix Assistant")
            
            # Select which chapter to rewrite after reviewing
            target_ch_num = st.selectbox("Target Chapter to Auto-Fix", chapter_list, index=len(chapter_list)-1, key="target_ch_num_selection")
            st.caption(f"✨ Pinpoint rewriting targeting **Chapter {target_ch_num}** based on overall critique.")
            
            if st.button("Generate Fix based on Critique"):
                target_text = st.session_state.chapters.get(str(target_ch_num), "")
                with st.spinner(f"Rewriting Chapter {target_ch_num}..."):
                    try:
                        critique_summary = f"Feedback: {review.get('feedback')} \n Suggestions: {review.get('improvement_suggestions')}"
                        rag_enabled, rag_category_id, rag_series_id, rag_keyword = get_clean_rag_params()
                        res = requests.post(
                            f"{BACKEND_URL}/analyze/rewrite",
                            json={
                                "text": target_text,
                                "critique": critique_summary,
                                "char_sheet": st.session_state.char_sheet,
                                "world_setting": st.session_state.world_setting,
                                "model": selected_model_assistant,
                                "style_guide": st.session_state.get("ig_style_guide", ""),
                                "rag_enabled": rag_enabled,
                                "rag_category_id": rag_category_id,
                                "rag_series_id": rag_series_id,
                                "rag_keyword": rag_keyword
                            }, timeout=120
                        )
                        if res.status_code == 200:
                            st.session_state.rewritten_text = res.json().get("rewritten")
                        else:
                            st.error(res.text)
                    except Exception as e:
                        st.error(str(e))

            if "rewritten_text" in st.session_state:
                st.subheader("Proposed Fix Preview")
                proposed = st.session_state.rewritten_text
                st.text_area("Proposed Edit", value=proposed, height=300)
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("💾 Apply Auto-Fix and Overwrite"):
                        st.session_state.chapters[str(target_ch_num)] = proposed
                        # Register as applied fix
                        if "applied_fixes" not in st.session_state.review_result or not isinstance(st.session_state.review_result["applied_fixes"], list):
                            st.session_state.review_result["applied_fixes"] = []
                        if int(target_ch_num) not in st.session_state.review_result["applied_fixes"]:
                            st.session_state.review_result["applied_fixes"].append(int(target_ch_num))
                        
                        # Update current story if we edited the active chapter
                        if st.session_state.get("current_chapter_idx") == target_ch_num:
                            st.session_state.current_story = proposed
                        auto_save()
                        # Extract and update memory chain
                        try:
                            # hyper-precision extraction
                            r_ext = requests.post(
                                f"{BACKEND_URL}/metadata/extract",
                                json={
                                    "text": proposed,
                                    "chapter_num": target_ch_num,
                                    "chars": st.session_state.char_sheet,
                                    "world": st.session_state.world_setting,
                                    "model": selected_model_assistant
                                }, timeout=120
                            )
                            if r_ext.status_code == 200:
                                meta = r_ext.json().get("metadata", {})
                                # update memory chain
                                chain = st.session_state.get("memory_chain", [])
                                # Remove duplicates
                                chain = [m for m in chain if int(m.get("chapter", 0)) != int(target_ch_num)]
                                chain.append({
                                    "chapter": int(target_ch_num),
                                    "chunk_summary": meta.get("summary", ""),
                                    "entity_changes": meta.get("entity_updates", {}),
                                    "cliffhanger_point": meta.get("cliffhanger_point", "")
                                })
                                chain.sort(key=lambda x: int(x.get("chapter", 0)))
                                st.session_state.memory_chain = chain
                                auto_save()
                        except Exception as e:
                            print(f"Failed to update metadata: {e}")
                            
                        st.success("Auto-Fix applied successfully! 💾")
                        del st.session_state.rewritten_text
                        st.rerun()
                with col_btn2:
                    if st.button("❌ Discard Proposed Fix"):
                        del st.session_state.rewritten_text
                        st.rerun()

    # ==========================================
    # TAB 4: ART STUDIO (Production)
    # ==========================================
    elif st.session_state.current_page == "🎨 Art Studio":
        st.header("🎨 표지 제작 디자인 스튜디오")
        st.caption("Imagen 3 엔진을 활용하여 고품질 웹소설 표지를 생성하고 책의 공식 커버로 등록합니다.")
        
        # Define local cover image path
        cover_dir = os.path.join(BASE_DATA_DIR, username, st.session_state.current_project)
        cover_path = os.path.join(cover_dir, "cover.png")
        
        # If cover exists, show it permanently
        if os.path.exists(cover_path):
            st.info("📖 현재 저장된 최종 책 표지")
            st.image(cover_path, width=300, caption="등록된 책 표지 이미지 (EPUB 내보내기 시 자동 탑재)")
            if st.button("🗑️ 표지 이미지 삭제", key="delete_cover_btn"):
                try:
                    os.remove(cover_path)
                    st.success("표지 이미지가 삭제되었습니다.")
                    st.rerun()
                except Exception as e:
                    st.error(f"삭제 오류: {e}")
        else:
            st.warning("⚠️ 등록된 표지 이미지가 없습니다. 아래에서 이미지를 생성하거나 올려주세요.")
        
        st.markdown("---")
        
        # 1. Prompt Generation
        if st.button("📖 소설 본문에서 이미지 프롬프트 자동 추출"):
            with st.spinner("본문에서 연출 장면 분석 및 이미지 프롬프트 추출 중..."):
                try:
                    res = requests.post(f"{BACKEND_URL}/analyze/cover_prompt", json={"text": st.session_state.current_story}, timeout=120)
                    if res.status_code == 200:
                        st.session_state.cover_prompt = res.json().get("cover_prompt")
                        st.success("프롬프트가 성공적으로 추출되었습니다! (아래 에디터에서 수정 가능)")
                    else:
                        st.error(res.text)
                except Exception as e:
                    st.error(str(e))
        
        prompt_input = st.text_area("🎨 표지 이미지 묘사 (프롬프트 입력 - 영어 입력 권장)", value=st.session_state.get("cover_prompt", ""), height=120)
        
        # 2. Image Generation
        if st.button("✨ 표지 이미지 생성하기 (Imagen 3)", use_container_width=True):
            if prompt_input:
                with st.spinner("AI가 고해상도 표지를 그리는 중... (약 10초 소요)"):
                    try:
                        res = requests.post(f"{BACKEND_URL}/generate/imagen3", json={"prompt": prompt_input}, timeout=120)
                        if res.status_code == 200 and "image_base64" in res.json():
                            img_bytes = base64.b64decode(res.json()["image_base64"])
                            
                            # Save to local path immediately to make it persistent
                            os.makedirs(cover_dir, exist_ok=True)
                            with open(cover_path, "wb") as f:
                                f.write(img_bytes)
                                
                            st.success("🎉 표지 이미지가 성공적으로 생성되어 프로젝트에 공식 등록되었습니다!")
                            st.rerun()
                        else:
                            st.error(res.text)
                    except Exception as e:
                         st.error(str(e))
            else:
                st.error("이미지 생성을 위해 프롬프트를 먼저 입력하거나 소설 본문에서 추출해 주십시오.")


    # ==========================================
    # TAB 5: NOVEL FACTORY (Batch Production)
    # ==========================================
    elif st.session_state.current_page == "🏭 Novel Factory (Batch)":
        st.header("🏭 Novel Factory (Batch Generation)")
        
        # 1. Job Control
        c1, c2 = st.columns([1, 1])
        with c1:
            st.subheader("🚀 Start Production")
            batch_writer_model = st.selectbox("Writer Model", writer_model_options, key="batch_writer", index=0)
            batch_planner_model = st.selectbox("Planner Model", assistant_model_options, key="batch_planner", index=0)
            
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
                rag_enabled, rag_category_id, rag_series_id, rag_keyword = get_clean_rag_params()
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
                    "creativity": temperature,
                    "rag_enabled": rag_enabled,
                    "rag_category_id": rag_category_id,
                    "rag_series_id": rag_series_id,
                    "rag_keyword": rag_keyword,
                    "style_guide": st.session_state.get("ig_style_guide", "")
                }
                batch_settings = {k: v for k, v in batch_settings.items() if v is not None}
                
                with st.spinner("Initializing Factory..."):
                    try:
                        batch_payload = {
                            "settings": batch_settings,
                            "target_vols": 50,
                            "model_writer": batch_writer_model,
                            "model_planner": batch_planner_model,
                            "reference_outline": st.session_state.get("plot_outline", "") if st.session_state.get("use_plot_outline") else "",
                            "self_healing": self_healing
                        }
                        batch_payload = {k: v for k, v in batch_payload.items() if v is not None}
                        res = requests.post(
                            f"{BACKEND_URL}/generate/batch_start",
                            json=batch_payload, timeout=120
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


    # ==========================================
    # TAB 5: PUBLISHER HUB
    # ==========================================
    elif st.session_state.current_page == "📦 Publisher Hub":
        st.markdown("### 📦 출판 허브 (Publisher Hub)")
        st.caption("외부 원고를 가져와 분할하거나, 편집·교정 작업을 수행합니다.")

        pub_splitter, pub_editor = st.tabs(["📄 연재 분할기", "✏️ 편집 작업대"])

        # ── Session State Init ──
        if "pub_raw_text" not in st.session_state:
            st.session_state.pub_raw_text = ""
        if "pub_editor_filename" not in st.session_state:
            st.session_state.pub_editor_filename = ""
        if "pub_episodes" not in st.session_state:
            st.session_state.pub_episodes = []
        if "pub_split_metadata" not in st.session_state:
            st.session_state.pub_split_metadata = {}
        if "pub_editor_current_ep" not in st.session_state:
            st.session_state.pub_editor_current_ep = 0
        if "pub_editor_edits" not in st.session_state:
            st.session_state.pub_editor_edits = {}
        if "pub_local_char_sheet" not in st.session_state:
            st.session_state.pub_local_char_sheet = ""
        if "pub_local_world_setting" not in st.session_state:
            st.session_state.pub_local_world_setting = ""

        # ──────────────────────────────────────────
        # SUB-TAB 1: 연재 분할기 (Serial Splitter)
        # ──────────────────────────────────────────
        with pub_splitter:
            st.markdown("#### 📄 연재 분할기")
            st.info("📁 TXT 또는 EPUB 파일을 업로드하면, 원하는 회차 수 또는 글자 수 기준으로 스마트 분할합니다.")

            uploaded_file = st.file_uploader(
                "📤 파일 업로드 (TXT, EPUB)",
                type=["txt", "epub"],
                key="pub_split_uploader",
                help="TXT 또는 EPUB 파일을 선택하세요.",
            )

            if uploaded_file is not None:
                if st.button("📥 파일 읽기", key="pub_read_file"):
                    with st.spinner("파일을 읽는 중..."):
                        try:
                            import requests as req
                            files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type or "application/octet-stream")}
                            res = req.post(f"{BACKEND_URL}/publisher/upload", files=files, timeout=60)
                            if res.status_code == 200:
                                data = res.json()
                                st.session_state.pub_raw_text = data["text"]
                                st.session_state.pub_editor_filename = data["filename"]
                                st.session_state.pub_episodes = []
                                st.session_state.pub_split_metadata = {}
                                
                                # 자동 원고 제목 생성 및 사이드바 목록 등록
                                clean_title = data["filename"].rsplit(".", 1)[0]
                                clean_title = "".join(ch for ch in clean_title if ch.isalnum() or ch in "_- ").strip().replace(" ", "_")
                                st.session_state.pub_current_doc = clean_title
                                auto_save_publisher_doc()
                                st.success(f"✅ '{data['filename']}' 읽기 완료! (총 {data['char_count']:,}자)")
                                st.rerun()
                            else:
                                st.error(f"오류: {res.text}")
                        except Exception as e:
                            st.error(f"통신 에러: {e}")

            if st.session_state.pub_raw_text:
                total_chars = len(st.session_state.pub_raw_text)
                st.markdown(f"**📋 로드된 파일:** `{st.session_state.pub_editor_filename}` | **총 글자 수:** {total_chars:,}자")

                with st.expander("📖 원문 미리보기 (처음 2000자)", expanded=False):
                    st.text_area(
                        "원문",
                        value=st.session_state.pub_raw_text[:2000] + ("..." if total_chars > 2000 else ""),
                        height=300,
                        disabled=True,
                        key="pub_preview_raw",
                    )

                st.markdown("---")
                st.markdown("#### ⚙️ 분할 설정")
                col_mode, col_val = st.columns(2)

                with col_mode:
                    split_mode = st.radio(
                        "분할 모드",
                        ["📚 회차 수 기준", "📝 글자 수 기준"],
                        key="pub_split_mode",
                        horizontal=True,
                    )

                with col_val:
                    if "회차" in split_mode:
                        split_value = st.number_input(
                            "총 회차 수", min_value=2, max_value=500, value=10, step=1, key="pub_split_value_ch"
                        )
                        mode_key = "chapter"
                    else:
                        split_value = st.number_input(
                            "회차당 목표 글자 수", min_value=500, max_value=50000, value=3000, step=500, key="pub_split_value_tok"
                        )
                        mode_key = "token"

                if st.button("✂️ 분할 실행", key="pub_do_split", type="primary"):
                    with st.spinner("스마트 분할 중... (문장 경계를 분석하고 있습니다)"):
                        try:
                            import requests as req
                            res = req.post(
                                f"{BACKEND_URL}/publisher/split",
                                json={
                                    "text": st.session_state.pub_raw_text,
                                    "mode": mode_key,
                                    "value": split_value,
                                },
                                timeout=60,
                            )
                            if res.status_code == 200:
                                data = res.json()
                                st.session_state.pub_episodes = data["episodes"]
                                st.session_state.pub_split_metadata = data["metadata"]
                                auto_save_publisher_doc()
                                st.success(f"✅ 분할 완료! 총 {data['metadata']['total_episodes']}화")
                                st.rerun()
                            else:
                                st.error(f"오류: {res.text}")
                        except Exception as e:
                            st.error(f"통신 에러: {e}")

                if st.session_state.pub_episodes:
                    meta = st.session_state.pub_split_metadata
                    episodes = st.session_state.pub_episodes

                    st.markdown("---")
                    st.markdown("#### 📊 분할 결과")

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("총 회차", f"{meta.get('total_episodes', 0)}화")
                    c2.metric("총 글자 수", f"{meta.get('total_chars', 0):,}자")
                    c3.metric("평균 글자 수", f"{meta.get('avg_chars', 0):,}자")
                    c4.metric("편차", f"{meta.get('min_chars', 0):,} ~ {meta.get('max_chars', 0):,}자")

                    st.markdown("##### 📋 회차별 미리보기")
                    char_counts = meta.get("char_counts", [])

                    for idx, ep in enumerate(episodes):
                        ep_chars = char_counts[idx] if idx < len(char_counts) else len(ep)
                        with st.expander(f"📖 {idx + 1}화 ({ep_chars:,}자)", expanded=False):
                            st.text_area(
                                f"내용 ({idx + 1}화)",
                                value=ep,
                                height=200,
                                disabled=True,
                                key=f"pub_ep_preview_{idx}",
                            )

                    st.markdown("---")
                    st.markdown("#### 💾 내보내기")
                    col_title, col_author = st.columns(2)
                    with col_title:
                        export_title = st.text_input("작품 제목", value=st.session_state.pub_editor_filename.rsplit(".", 1)[0] if st.session_state.pub_editor_filename else "작품", key="pub_export_title")
                    with col_author:
                        export_author = st.text_input("저자", value="작가", key="pub_export_author")

                    export_format = st.radio("내보내기 형식", ["TXT", "EPUB"], horizontal=True, key="pub_export_format")

                    if st.button("📦 ZIP 다운로드", key="pub_download_zip", type="primary"):
                        with st.spinner("ZIP 파일 생성 중..."):
                            try:
                                import requests as req
                                res = req.post(
                                    f"{BACKEND_URL}/publisher/export-split",
                                    json={
                                        "episodes": episodes,
                                        "title": export_title,
                                        "author": export_author,
                                        "format_type": export_format.lower(),
                                    },
                                    timeout=120,
                                )
                                if res.status_code == 200:
                                    st.download_button(
                                        label="⬇️ 다운로드",
                                        data=res.content,
                                        file_name=f"{export_title}_분할.zip",
                                        mime="application/zip",
                                        key="pub_zip_dl_btn",
                                    )
                                else:
                                    st.error(f"오류: {res.text}")
                            except Exception as e:
                                st.error(f"통신 에러: {e}")

                    st.markdown("---")
                    if st.button("✏️ 편집 작업대로 보내기", key="pub_send_to_editor"):
                        st.session_state.pub_episodes = list(episodes)
                        st.session_state.pub_editor_current_ep = 0
                        st.session_state.pub_editor_edits = {}
                        auto_save_publisher_doc()
                        st.success("✅ 편집 작업대로 전송 완료! '✏️ 편집 작업대' 탭으로 이동하세요.")

        # ──────────────────────────────────────────
        # SUB-TAB 2: 편집 작업대 (Editorial Workbench)
        # ──────────────────────────────────────────
        with pub_editor:
            st.markdown("#### ✏️ 편집 작업대")
            st.info("📖 외부 원고를 가져와 회차별로 편집·교정하고, AI 분석 도구를 활용합니다.")

            editor_upload = st.file_uploader(
                "📤 파일 업로드 (TXT, EPUB) — 또는 분할기에서 가져오기",
                type=["txt", "epub"],
                key="pub_editor_uploader",
            )

            if editor_upload is not None:
                if st.button("📥 파일 읽기 (편집용)", key="pub_editor_read"):
                    with st.spinner("파일을 읽는 중..."):
                        try:
                            import requests as req
                            files = {"file": (editor_upload.name, editor_upload.getvalue(), editor_upload.type or "application/octet-stream")}
                            res = req.post(f"{BACKEND_URL}/publisher/upload", files=files, timeout=60)
                            if res.status_code == 200:
                                data = res.json()
                                st.session_state.pub_episodes = [data["text"]]
                                st.session_state.pub_raw_text = data["text"]
                                st.session_state.pub_editor_filename = data["filename"]
                                st.session_state.pub_editor_current_ep = 0
                                st.session_state.pub_editor_edits = {}
                                
                                # 자동 원고 제목 생성 및 사이드바 목록 등록
                                clean_title = data["filename"].rsplit(".", 1)[0]
                                clean_title = "".join(ch for ch in clean_title if ch.isalnum() or ch in "_- ").strip().replace(" ", "_")
                                st.session_state.pub_current_doc = clean_title
                                auto_save_publisher_doc()
                                st.success(f"✅ '{data['filename']}' 로드 완료! ({data['char_count']:,}자)")
                                st.rerun()
                            else:
                                st.error(f"오류: {res.text}")
                        except Exception as e:
                            st.error(f"통신 에러: {e}")

            if st.session_state.pub_episodes:
                episodes = st.session_state.pub_episodes
                total_eps = len(episodes)
                cur_ep = st.session_state.pub_editor_current_ep

                st.markdown(f"**📋 파일:** `{st.session_state.pub_editor_filename}` | **총 {total_eps}화**")

                st.markdown("---")
                nav_col1, nav_col2, nav_col3 = st.columns([1, 3, 1])

                with nav_col1:
                    if st.button("⬅️ 이전 화", key="pub_nav_prev", disabled=(cur_ep <= 0)):
                        st.session_state.pub_editor_current_ep = max(0, cur_ep - 1)
                        st.rerun()

                with nav_col2:
                    selected_ep = st.selectbox(
                        "회차 선택",
                        range(total_eps),
                        index=cur_ep,
                        format_func=lambda x: f"{x + 1}화 ({len(episodes[x]):,}자)",
                        key="pub_ep_selector",
                    )
                    if selected_ep != cur_ep:
                        st.session_state.pub_editor_current_ep = selected_ep
                        st.rerun()

                with nav_col3:
                    if st.button("➡️ 다음 화", key="pub_nav_next", disabled=(cur_ep >= total_eps - 1)):
                        st.session_state.pub_editor_current_ep = min(total_eps - 1, cur_ep + 1)
                        st.rerun()

                cur_ep = st.session_state.pub_editor_current_ep
                current_text = st.session_state.pub_editor_edits.get(cur_ep, episodes[cur_ep])

                # ── 원고 전용 로컬 설정 사전 ──
                if "pub_local_char_sheet" not in st.session_state:
                    st.session_state.pub_local_char_sheet = ""
                if "pub_local_world_setting" not in st.session_state:
                    st.session_state.pub_local_world_setting = ""

                with st.expander("⚙️ 이 원고 전용 설정 사전 (스토리 엔진과 분리)", expanded=False):
                    set_col1, set_col2 = st.columns(2)
                    with set_col1:
                        st.session_state.pub_local_char_sheet = st.text_area(
                            "👤 캐릭터 시트",
                            value=st.session_state.pub_local_char_sheet,
                            placeholder="예: 주인공 김도진 (남자, 28세, 흑발, 까칠한 성격)...",
                            height=150,
                            key="pub_input_local_char_sheet"
                        )
                    with set_col2:
                        st.session_state.pub_local_world_setting = st.text_area(
                            "🌍 세계관 및 배경 설정",
                            value=st.session_state.pub_local_world_setting,
                            placeholder="예: 현대 서울, 마법이 존재하지만 숨겨진 가상 현대 판타지...",
                            height=150,
                            key="pub_input_local_world_setting"
                        )

                st.markdown(f"##### 📝 {cur_ep + 1}화 편집")
                edit_col1, edit_col2 = st.columns(2)

                with edit_col1:
                    st.markdown("**📖 원본 (읽기 전용)**")
                    st.text_area(
                        "원본",
                        value=episodes[cur_ep],
                        height=500,
                        disabled=True,
                        key=f"pub_editor_orig_{cur_ep}",
                        label_visibility="collapsed",
                    )

                with edit_col2:
                    st.markdown("**✏️ 편집본**")
                    edited_text = st.text_area(
                        "편집",
                        value=current_text,
                        height=500,
                        key=f"pub_editor_edit_{cur_ep}",
                        label_visibility="collapsed",
                    )

                if edited_text != episodes[cur_ep]:
                    st.session_state.pub_editor_edits[cur_ep] = edited_text
                    diff_chars = len(edited_text) - len(episodes[cur_ep])
                    st.caption(f"📝 수정됨 (원본 대비 {'+' if diff_chars >= 0 else ''}{diff_chars}자)")
                elif cur_ep in st.session_state.pub_editor_edits:
                    del st.session_state.pub_editor_edits[cur_ep]

                st.markdown("---")
                st.markdown("##### 🤖 AI 도구")

                ai_col1, ai_col2, ai_col3, ai_col4, ai_col5 = st.columns(5)

                with ai_col1:
                    if st.button("📊 분석", key="pub_ai_analyze", help="현재 회차 텍스트 분석"):
                        with st.spinner("AI 분석 중..."):
                            try:
                                import requests as req
                                target_text = st.session_state.pub_editor_edits.get(cur_ep, episodes[cur_ep])
                                res = req.post(
                                    f"{BACKEND_URL}/analyze/review",
                                    json={"text": target_text, "model": "models/gemini-2.5-flash"},
                                    timeout=120,
                                )
                                if res.status_code == 200:
                                    st.session_state[f"pub_ai_result_{cur_ep}"] = {"type": "분석", "data": res.json()}
                                    st.rerun()
                                else:
                                    st.error(f"오류: {res.text}")
                            except Exception as e:
                                st.error(f"통신 에러: {e}")

                with ai_col2:
                    if st.button("🔍 일관성", key="pub_ai_consistency", help="설정과의 일관성 검사"):
                        with st.spinner("일관성 분석 중..."):
                            try:
                                import requests as req
                                target_text = st.session_state.pub_editor_edits.get(cur_ep, episodes[cur_ep])
                                res = req.post(
                                    f"{BACKEND_URL}/analyze/consistency",
                                    json={
                                        "text": target_text,
                                        "char_sheet": st.session_state.get("pub_local_char_sheet", ""),
                                        "world_setting": st.session_state.get("pub_local_world_setting", ""),
                                        "model": "models/gemini-2.5-flash",
                                    },
                                    timeout=120,
                                )
                                if res.status_code == 200:
                                    st.session_state[f"pub_ai_result_{cur_ep}"] = {"type": "일관성", "data": res.json()}
                                    st.rerun()
                                else:
                                    st.error(f"오류: {res.text}")
                            except Exception as e:
                                st.error(f"통신 에러: {e}")

                with ai_col3:
                    if st.button("📝 종합 리뷰", key="pub_ai_review", help="종합적인 리뷰 및 점수"):
                        with st.spinner("종합 리뷰 중..."):
                            try:
                                import requests as req
                                target_text = st.session_state.pub_editor_edits.get(cur_ep, episodes[cur_ep])
                                res = req.post(
                                    f"{BACKEND_URL}/analyze/review_comprehensive",
                                    json={"text": target_text, "model": "models/gemini-2.5-flash"},
                                    timeout=180,
                                )
                                if res.status_code == 200:
                                    st.session_state[f"pub_ai_result_{cur_ep}"] = {"type": "종합리뷰", "data": res.json()}
                                    st.rerun()
                                else:
                                    st.error(f"오류: {res.text}")
                            except Exception as e:
                                st.error(f"통신 에러: {e}")

                with ai_col4:
                    if st.button("✍️ 맞춤법 검사", key="pub_ai_spellcheck", help="한국어 맞춤법 및 소설 교정"):
                        with st.spinner("맞춤법 및 문장 검사 중..."):
                            try:
                                import requests as req
                                target_text = st.session_state.pub_editor_edits.get(cur_ep, episodes[cur_ep])
                                res = req.post(
                                    f"{BACKEND_URL}/publisher/check-spell",
                                    json={"text": target_text, "model": "models/gemini-2.5-flash"},
                                    timeout=120,
                                )
                                if res.status_code == 200:
                                    st.session_state[f"pub_ai_result_{cur_ep}"] = {"type": "맞춤법", "data": res.json()}
                                    st.rerun()
                                else:
                                    st.error(f"오류: {res.text}")
                            except Exception as e:
                                st.error(f"통신 에러: {e}")

                with ai_col5:
                    if st.button("🧠 장기기억 저장", key="pub_ai_memory", help="현재 회차를 장기기억에 추가"):
                        target_text = st.session_state.pub_editor_edits.get(cur_ep, episodes[cur_ep])
                        if "memory_chain" not in st.session_state:
                            st.session_state.memory_chain = []
                        with st.spinner("요약 생성 중..."):
                            try:
                                import requests as req
                                res = req.post(
                                    f"{BACKEND_URL}/summarize",
                                    json={
                                        "text": target_text,
                                        "chapter_num": cur_ep + 1,
                                        "chars": st.session_state.get("pub_local_char_sheet", ""),
                                    },
                                    timeout=60,
                                )
                                if res.status_code == 200:
                                    summary = res.json().get("summary", target_text[:200])
                                    st.session_state.memory_chain.append({
                                        "chapter": cur_ep + 1,
                                        "summary": summary,
                                        "source": f"[편집 작업대] {st.session_state.pub_editor_filename}",
                                    })
                                    auto_save()
                                    st.success(f"✅ {cur_ep + 1}화 요약이 장기기억에 저장되었습니다!")
                                else:
                                    st.error(f"요약 실패: {res.text}")
                            except Exception as e:
                                st.error(f"통신 에러: {e}")

                # ── AI Results Display ──
                result_key = f"pub_ai_result_{cur_ep}"
                if result_key in st.session_state:
                    result = st.session_state[result_key]
                    result_type = result.get("type", "결과")
                    result_data = result.get("data", {})

                    st.markdown("---")
                    st.markdown(f"##### 🤖 AI {result_type} 결과")

                    if result_type == "분석":
                        review = result_data.get("review", result_data)
                        if isinstance(review, dict):
                            scores = review.get("scores", {})
                            if isinstance(scores, dict):
                                score_cols = st.columns(len(scores))
                                for i, (k, v) in enumerate(scores.items()):
                                    score_cols[i].metric(k, f"{v}/100" if isinstance(v, (int, float)) else str(v))
                            feedback = review.get("feedback", review.get("critique", ""))
                            if feedback:
                                st.markdown(feedback)
                        else:
                            st.write(review)

                    elif result_type == "일관성":
                        report = result_data.get("report", result_data)
                        if isinstance(report, dict):
                            errors = report.get("plot_errors", [])
                            if errors:
                                st.warning(f"⚠️ {len(errors)}개의 불일치 발견")
                                for err in errors:
                                    st.markdown(f"- {err}")
                            else:
                                st.success("✅ 일관성 문제 없음!")
                            notes = report.get("notes", "")
                            if notes:
                                st.info(notes)
                        else:
                            st.write(report)

                    elif result_type == "맞춤법":
                        report = result_data.get("report", result_data)
                        if report:
                            st.markdown(report)
                        else:
                            st.info("맞춤법 및 문장 교정 결과가 비어 있습니다.")

                    elif result_type == "종합리뷰":
                        review = result_data.get("review", result_data)
                        if isinstance(review, dict):
                            scores = review.get("scores", {})
                            if isinstance(scores, dict):
                                score_cols = st.columns(min(len(scores), 5))
                                for i, (k, v) in enumerate(scores.items()):
                                    if i < 5:
                                        score_cols[i].metric(k, f"{v}/100" if isinstance(v, (int, float)) else str(v))
                            critique = review.get("critique", review.get("feedback", ""))
                            if critique:
                                with st.expander("📝 상세 비평", expanded=True):
                                    st.markdown(critique)
                            suggestions = review.get("suggestions", [])
                            if suggestions:
                                with st.expander("💡 개선 제안"):
                                    for s in suggestions:
                                        st.markdown(f"- {s}")
                        else:
                            st.write(review)

                st.markdown("---")
                st.markdown("##### 💾 저장 및 내보내기")

                dl_col1, dl_col2, dl_col3 = st.columns(3)

                with dl_col1:
                    current_download_text = st.session_state.pub_editor_edits.get(cur_ep, episodes[cur_ep])
                    safe_fname = st.session_state.pub_editor_filename.rsplit('.', 1)[0] if '.' in st.session_state.pub_editor_filename else st.session_state.pub_editor_filename
                    st.download_button(
                        "⬇️ 현재 회차 다운로드",
                        data=current_download_text.encode("utf-8"),
                        file_name=f"{safe_fname}_{cur_ep + 1}화.txt",
                        mime="text/plain",
                        key="pub_dl_current",
                    )

                with dl_col2:
                    if st.button("📦 전체 수정본 ZIP", key="pub_dl_all_zip"):
                        import zipfile as zf_mod
                        zip_buf = BytesIO()
                        with zf_mod.ZipFile(zip_buf, "w", zf_mod.ZIP_DEFLATED) as zf:
                            for i, ep in enumerate(episodes):
                                edited = st.session_state.pub_editor_edits.get(i, ep)
                                zf.writestr(f"{i + 1:03d}화.txt", edited.encode("utf-8"))
                        zip_buf.seek(0)
                        st.download_button(
                            "⬇️ 다운로드",
                            data=zip_buf.getvalue(),
                            file_name=f"{safe_fname}_편집본.zip",
                            mime="application/zip",
                            key="pub_dl_zip_btn",
                        )

                with dl_col3:
                    if st.button("📄 분할기로 보내기", key="pub_send_to_splitter"):
                        merged = "\n\n".join(
                            st.session_state.pub_editor_edits.get(i, ep)
                            for i, ep in enumerate(episodes)
                        )
                        st.session_state.pub_raw_text = merged
                        safe_fn = st.session_state.pub_editor_filename.rsplit('.', 1)[0] if '.' in st.session_state.pub_editor_filename else st.session_state.pub_editor_filename
                        st.session_state.pub_editor_filename = f"{safe_fn}_편집본.txt"
                        st.session_state.pub_episodes = []
                        st.session_state.pub_split_metadata = {}
                        auto_save_publisher_doc()
                        st.success("✅ 분할기로 전송 완료! '📄 연재 분할기' 탭으로 이동하세요.")

                edited_count = len(st.session_state.pub_editor_edits)
                if edited_count > 0:
                    st.caption(f"📝 수정된 회차: {edited_count}/{total_eps}화")
            else:
                st.info("📁 파일을 업로드하거나, '📄 연재 분할기' 탭에서 '편집 작업대로 보내기'를 사용하세요.")

        # 원고 자동 저장 실행
        auto_save_publisher_doc()


if __name__ == "__main__":
    main()
