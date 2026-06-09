import json
import os
import re
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Configure GenAI
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("Error: GEMINI_API_KEY not found in .env", flush=True)
    exit(1)
genai.configure(api_key=api_key)

# Load JSON
json_path = 'story_data/bhlht3/My_romance_20260601.json'
with open(json_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# 1. Merge text from batch results to chapters
batch_results = data.get('batch_status', {}).get('results', [])
chapters = data.get('chapters', {})

merged_any = False
for r in batch_results:
    ch_num = str(r['chapter_num'])
    text = r.get('text', '').strip()
    if text:
        if ch_num not in chapters or len(chapters[ch_num].strip()) == 0:
            chapters[ch_num] = text
            print(f"Merged Chapter {ch_num} text from batch results", flush=True)
            merged_any = True

data['chapters'] = chapters

# Save initial merged text
if merged_any:
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("Successfully merged and saved chapter texts from batch status.", flush=True)

# 2. Rebuild/Extract Memory Chain
memory_chain = data.get('memory_chain', [])
if memory_chain is None:
    memory_chain = []

# Get existing chapters in memory chain
existing_chapters_in_memory = {int(m.get('chapter', 0)) for m in memory_chain}
print(f"Existing chapters in memory chain: {sorted(list(existing_chapters_in_memory))}", flush=True)

model = genai.GenerativeModel('gemini-2.5-flash')

for ch_num_str, text in sorted(chapters.items(), key=lambda x: int(x[0])):
    ch_num = int(ch_num_str)
    if not text.strip():
        continue
    if ch_num in existing_chapters_in_memory:
        continue
    
    print(f"Extracting memory for Chapter {ch_num}...", flush=True)
    prompt = f"""
    당신은 베스트셀러 소설 전문 교열가이자 기획자입니다. 다음 소설 장면을 정밀하게 분석하여 장기 기억 스토리지용 설정 변경 메타데이터를 추출하십시오.

    [분석할 본문 (제{ch_num}화)]
    {text}

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
    try:
        response = model.generate_content(prompt)
        cleaned = response.text.replace("```json", "").replace("```", "").strip()
        metadata = json.loads(cleaned)
    except Exception as e:
        print(f"Warning: JSON parse failed for Chapter {ch_num}, trying regex parsing...", flush=True)
        # Regex parsing fallback
        metadata = {}
        cleaned_text = getattr(response, 'text', '') if 'response' in locals() else ''
        summary_match = re.search(r'"chunk_summary"\s*:\s*"(.*?)"\s*(?:,|\})', cleaned_text, re.DOTALL)
        if summary_match:
            metadata["chunk_summary"] = summary_match.group(1).replace('\\"', '"').replace('\\n', '\n')
        
        char_match = re.search(r'"characters"\s*:\s*"(.*?)"\s*(?:,|\})', cleaned_text, re.DOTALL)
        setting_match = re.search(r'"settings"\s*:\s*"(.*?)"\s*(?:,|\})', cleaned_text, re.DOTALL)
        if char_match or setting_match:
            metadata["entity_changes"] = {}
            if char_match:
                metadata["entity_changes"]["characters"] = char_match.group(1).replace('\\"', '"').replace('\\n', '\n')
            if setting_match:
                metadata["entity_changes"]["settings"] = setting_match.group(1).replace('\\"', '"').replace('\\n', '\n')
        
        cliff_match = re.search(r'"cliffhanger_point"\s*:\s*"(.*?)"\s*(?:,|\})', cleaned_text, re.DOTALL)
        if cliff_match:
            metadata["cliffhanger_point"] = cliff_match.group(1).replace('\\"', '"').replace('\\n', '\n')

    # Construct the memory block
    ch_memory = {
        "chapter": ch_num,
        "chunk_summary": metadata.get("chunk_summary", f"{ch_num}화 요약"),
        "entity_changes": metadata.get("entity_changes", {"characters": "변동 없음", "settings": "변동 없음"}),
        "cliffhanger_point": metadata.get("cliffhanger_point", "")
    }
    
    memory_chain.append(ch_memory)
    # Sort memory chain by chapter number
    memory_chain.sort(key=lambda x: int(x.get("chapter", 0)))
    data['memory_chain'] = memory_chain
    
    # Save after each chapter
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"Successfully added and saved Chapter {ch_num} to memory chain.", flush=True)

print("Memory chain update completed successfully!", flush=True)
