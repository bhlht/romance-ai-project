import re

file_path = r"d:\myProject\streamlit\frontend\app.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

pattern = r'(\s*)res\s*=\s*requests\.post\(\s*f"\{BACKEND_URL\}/analyze/review_comprehensive".*?auto_save\(\)'
match = re.search(pattern, content, re.DOTALL)
if match:
    indent = match.group(1)
    print(f"SUCCESS: Found match. Indent len={len(indent)}")
    
    # Construct replacement dynamically using the found indentation
    replacement = (
        f"{indent}# 기존에 이미 사용자가 완료했던 교정 완료 목록(applied_fixes)을 가져와 백엔드로 전송\n"
        f"{indent}old_review = st.session_state.get(\"review_result\")\n"
        f"{indent}old_fixes = []\n"
        f"{indent}if isinstance(old_review, dict):\n"
        f"{indent}    old_fixes = old_review.get(\"applied_fixes\", [])\n"
        f"{indent}    if not isinstance(old_fixes, list):\n"
        f"{indent}        old_fixes = []\n\n"
        f"{indent}res = requests.post(\n"
        f"{indent}    f\"{{BACKEND_URL}}/analyze/review_comprehensive\",\n"
        f"{indent}    json={{\n"
        f"{indent}        \"text\": payload.get(\"text\"),\n"
        f"{indent}        \"memory_chain\": payload.get(\"memory_chain\"),\n"
        f"{indent}        \"applied_fixes\": old_fixes,\n"
        f"{indent}        \"model\": payload[\"model\"]\n"
        f"{indent}    }}, timeout=120\n"
        f"{indent})\n"
        f"{indent}if res.status_code == 200:\n"
        f"{indent}     new_review = res.json().get(\"review\", {{(}}).get(\"review\", {{}})\n"  # Handle nesting if any, or just get
    )
    # Let's inspect the original inner block of if res.status_code == 200:
    # We can just replace the whole matched block with a clean new one:
    clean_replacement = (
        f"{indent}# 기존에 이미 사용자가 완료했던 교정 완료 목록(applied_fixes)을 가져와 백엔드로 전송\n"
        f"{indent}old_review = st.session_state.get(\"review_result\")\n"
        f"{indent}old_fixes = []\n"
        f"{indent}if isinstance(old_review, dict):\n"
        f"{indent}    old_fixes = old_review.get(\"applied_fixes\", [])\n"
        f"{indent}    if not isinstance(old_fixes, list):\n"
        f"{indent}        old_fixes = []\n\n"
        f"{indent}res = requests.post(\n"
        f"{indent}    f\"{{BACKEND_URL}}/analyze/review_comprehensive\",\n"
        f"{indent}    json={{\n"
        f"{indent}        \"text\": payload.get(\"text\"),\n"
        f"{indent}        \"memory_chain\": payload.get(\"memory_chain\"),\n"
        f"{indent}        \"applied_fixes\": old_fixes,\n"
        f"{indent}        \"model\": payload[\"model\"]\n"
        f"{indent}    }}, timeout=120\n"
        f"{indent})\n"
        f"{indent}if res.status_code == 200:\n"
        f"{indent}     new_review = res.json().get(\"review\", {{}})\n"
        f"{indent}     if not isinstance(new_review, dict):\n"
        f"{indent}         new_review = {{}}\n"
        f"{indent}     if \"applied_fixes\" not in new_review or not isinstance(new_review[\"applied_fixes\"], list):\n"
        f"{indent}         new_review[\"applied_fixes\"] = []\n"
        f"{indent}     for fix_ch in old_fixes:\n"
        f"{indent}         if fix_ch not in new_review[\"applied_fixes\"]:\n"
        f"{indent}             new_review[\"applied_fixes\"].append(fix_ch)\n"
        f"{indent}     st.session_state.review_result = new_review\n"
        f"{indent}     auto_save()"
    )
    
    new_content = content[:match.start()] + clean_replacement + content[match.end():]
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("SUCCESS: patch written using regex!")
else:
    print("Regex match failed completely!")
