import streamlit as st
import requests
import os
from dotenv import load_dotenv
from io import BytesIO
from docx import Document

# Load environment variables
load_dotenv()

# Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
ALLOWED_IPS = os.getenv("ALLOWED_IPS", "").split(",")  # Comma separated list of IPs

def check_access():
    """Simple IP-based access control simulation."""
    # In a real deployed Streamlit app, getting client IP is tricky due to proxies.
    # This is a placeholder or basic check logic if behind known proxy.
    # For now, we will skip hard enforcement or rely on query param for "admin" bypass during dev.
    pass

def init_session_state():
    if "current_story" not in st.session_state:
        st.session_state.current_story = ""
    if "critique" not in st.session_state:
        st.session_state.critique = None

def get_feedback(text):
    try:
        response = requests.post(f"{BACKEND_URL}/analyze/feedback", json={"text": text})
        if response.status_code == 200:
            return response.json().get("critique")
        else:
            return f"Error: {response.text}"
    except Exception as e:
        return f"Error connecting to backend: {e}"

def generate_story(prompt, temperature):
    current = st.session_state.current_story
    # Send only the prompt usually, or previous context + prompt if model is stateless but we want consistency.
    # Here assuming model takes prompt and continues. 
    # Better prompt engineering: "Continue the following story: [STORY] [PROMPT]"
    
    full_prompt = f"Genre: Romance. Continue the story:\n{current}\n\n{prompt}"
    # Truncate if too long? For now, send as is.
    
    try:
        response = requests.post(f"{BACKEND_URL}/generate/romance", json={
            "prompt": full_prompt,
            "max_length": 500,
            "temperature": temperature
        })
        if response.status_code == 200:
            return response.json().get("generated_text")
        else:
            return f"\n[Error: {response.text}]"
    except Exception as e:
        return f"\n[Error connecting to backend: {e}]"

def create_download_file(text, format="txt"):
    if format == "txt":
        return text.encode("utf-8")
    elif format == "docx":
        doc = Document()
        doc.add_heading('Romance Novel', 0)
        # Add paragraphs
        for para in text.split('\n'):
            if para.strip():
                doc.add_paragraph(para.strip())
        
        bio = BytesIO()
        doc.save(bio)
        bio.seek(0)
        return bio.getvalue()

def main():
    st.set_page_config(page_title="Romance AI Creator", page_icon="💖", layout="wide")
    
    init_session_state()
    
    # Sidebar
    st.sidebar.title("Settings")
    temperature = st.sidebar.slider("Creativity (Temperature)", 0.1, 1.0, 0.7)
    
    # Help Menu
    with st.sidebar.expander("📖 사용법 안내 (Help)", expanded=False):
        st.markdown("""
        **1. ✨ 영감 자판기 (Idea Generator)**
        - **기능**: 소설의 소재가 떠오르지 않을 때 사용하세요.
        - **사용법**: 'Generate Random Story Concept' 버튼을 누르면 캐릭터, 분위기, 반전 요소를 추천해줍니다. 마음에 들면 'Start Story'를 눌러 시작하세요.

        **2. ✍️ 소설 쓰기 (Story Workspace)**
        - **기능**: 소설을 실제로 창작하는 메인 공간입니다.
        - **사용법**: 'Enter your prompt'에 뒷내용 전개를 간단히 입력(예: "그녀가 화를 낸다")하고 'Generate'를 누르면 AI가 소설을 이어 씁니다.

        **3. 📝 AI 피드백 (AI Critique)**
        - **기능**: 쓴 글에 대한 전문가 피드백을 받습니다.
        - **사용법**: 'Request AI Critique'를 누르면 개연성, 감정선 등을 분석해줍니다.

        **4. 🎨 커버 아트 (Cover Art)**
        - **기능**: 소설 표지를 만듭니다.
        - **사용법**: 
            1. 'Generate Cover Prompt'로 프롬프트를 먼저 생성합니다.
            2. 생성된 프롬프트를 아래 'Image Prompt' 칸에 붙여넣습니다.
            3. '🚀 Create Cover Art Now'를 누르면 이미지가 생성됩니다.
        """)
    
    st.title("💖 Romance Novel AI Generator")
    
    # Main Interaction
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("Story Workspace")

        # --- New Feature: Story Idea Generator ---
        with st.expander("✨ Need Inspiration? (Magic Idea Generator)", expanded=False):
            if st.button("🎲 Generate Random Story Concept"):
                with st.spinner("Brainstorming creative ideas..."):
                    try:
                        res = requests.post(f"{BACKEND_URL}/generate/idea")
                        if res.status_code == 200:
                            st.session_state.idea_suggestion = res.json().get("idea")
                        else:
                            st.error(f"Error: {res.text}")
                    except Exception as e:
                        st.error(f"Connection Error: {e}")
            
            if "idea_suggestion" in st.session_state and st.session_state.idea_suggestion:
                st.text_area("Suggested Setup (Editable):", value=st.session_state.idea_suggestion, height=200, key="idea_input")
                if st.button("Use this Idea to Start Story"):
                    # Prepend idea to story or set as prompt
                    st.session_state.current_story = f"[Story Setup]\n{st.session_state.idea_input}\n\n[Chapter 1]\n"
                    st.rerun()
        # -----------------------------------------
        
        # Display Story
        st.text_area("Current Story", value=st.session_state.current_story, height=400, key="story_display", disabled=True)
        
        # Inputs
        user_input = st.text_input("Enter your prompt / continuation:", key="user_prompt")
        
        if st.button("Generate / Continue"):
            if user_input:
                with st.spinner("Writing..."):
                    new_text = generate_story(user_input, temperature)
                    if new_text:
                        st.session_state.current_story += "\n" + new_text
                        st.rerun()
        
        if st.button("Clear Story"):
            st.session_state.current_story = ""
            st.session_state.critique = None
            if "idea_suggestion" in st.session_state:
                del st.session_state.idea_suggestion
            st.rerun()

    with col2:
        st.subheader("AI Editor & Tools")
        
        if st.button("Request AI Critique"):
            if st.session_state.current_story:
                with st.spinner("Analyzing..."):
                    critique = get_feedback(st.session_state.current_story)
                    st.session_state.critique = critique
            else:
                st.warning("Write some story first!")

        if st.session_state.critique:
            st.info("AI Critique:")
            st.markdown(st.session_state.critique)
        
        st.markdown("---")
        st.subheader("Expert Options")
        
        # Download
        st.write("Download Story")
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            st.download_button(
                label="Download TXT",
                data=create_download_file(st.session_state.current_story, "txt"),
                file_name="romance_novel.txt",
                mime="text/plain"
            )
        with col_d2:
             st.download_button(
                label="Download DOCX",
                data=create_download_file(st.session_state.current_story, "docx"),
                file_name="romance_novel.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )

        st.markdown("---")
        st.subheader("🎨 Cover Art Generator")
        
        st.markdown("**Step 1: Design (Text Prompt)**")
        if st.button("🔮 1. Design Cover Prompt"):
            if st.session_state.current_story:
                with st.spinner("Designing cover concept..."):
                    try:
                        res = requests.post(f"{BACKEND_URL}/analyze/cover_prompt", json={"text": st.session_state.current_story})
                        if res.status_code == 200:
                            prompt = res.json().get("cover_prompt")
                            st.success("Design Ready! Copy the text below:")
                            st.text_area("Generated Prompt:", value=prompt, height=150)
                        else:
                            st.error(f"Error: {res.text}")
                    except Exception as e:
                        st.error(f"Connection Error: {e}")
            else:
                st.warning("Write some story first!")

        st.markdown("---")
        st.markdown("**Step 2: Render (Generate Image)**")
        st.info("Paste the text from Step 1 below to generate the actual image.")
        st.text_input("Paste Prompt Here:", key="img_prompt_input")
        
        if st.button("🎨 2. Generate Final Image (Nano Banana Pro)"):
            prompt = st.session_state.get("img_prompt_input")
            if prompt:
                with st.spinner("Generating High-Res Cover Art... (This may take 20s)"):
                    try:
                        res = requests.post(f"{BACKEND_URL}/generate/cover_image", json={"prompt": prompt})
                        if res.status_code == 200:
                            data = res.json()
                            if "image_base64" in data:
                                import base64
                                image_bytes = base64.b64decode(data["image_base64"])
                                st.image(image_bytes, caption="Generated by Nano Banana Pro", use_column_width=True)
                                
                                # Download Button for Image
                                st.download_button(
                                    label="Download Image",
                                    data=image_bytes,
                                    file_name="cover_art.png",
                                    mime="image/png"
                                )
                            else:
                                st.error("No image data received.")
                        else:
                            st.error(f"Error: {res.text}")
                    except Exception as e:
                        st.error(f"Error: {e}")
            else:
                st.warning("Please enter or generate a prompt first!")

if __name__ == "__main__":
    main()
