import json
import os
import asyncio
import google.generativeai as genai

async def run_debug():
    # Load API key
    # Load env variables from .env
    with open(r"d:\myProject\streamlit\.env", "r") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ[k] = v
                
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    
    filepath = r"d:\myProject\streamlit\story_data\bhlht3\My_romance_20260601.json"
    with open(filepath, "r", encoding="utf-8") as f:
        story_data = json.load(f)
        
    memory_chain = story_data.get("memory_chain", [])
    
    map_prompt = f"""
당신은 대한민국 최고의 웹소설 기획자이자 비평가입니다. 다음 축적된 [매화별 초정밀 요약 및 캐릭터/세계관 설정 변동사항]을 기반으로 작품 전체의 장기적 일관성, 개연성, 상업성 및 전개 템포를 심층 비평하십시오.

[스토리 메타데이터 피드]
{json.dumps(memory_chain, ensure_ascii=False, indent=2)}

[검토 기준]
- 캐릭터 감정선의 누적 및 개연성 (Characters arc consistency)
- 시공간/규칙의 일관성 (World setting consistency)
- 상업적 텐션 및 호흡 (Pacing and commercial potential)

[중요 지시 사항 - 추천 교정 대상 화차 선정 규칙]
1. **스토리 메타데이터 피드 전체를 처음부터 끝까지 매우 정밀하게 교차 검증하십시오.**
2. **조금이라도 인물 성격 붕괴, 사건의 갑작스러운 인과관계 비약(개연성 부족), 공간 설정 충돌, 급격한 템포 저하가 감지되는 모든 화차를 빠짐없이 `recommended_chapters` 배열에 전부 기입하십시오.**
3. **피드백(feedback) 본문(예: consistency, grammar_flow 등)에서 지적하거나 언급한 수정 대상 화차(예: 15화, 16화, 28화 등)는 반드시 하나도 빠짐없이 `recommended_chapters` 배열에 구조화된 형태로 함께 포함되어야 합니다. 본문에서는 지적해놓고 배열을 비워두는 일이 없도록 하십시오.**
4. **절대 JSON 포맷 예시의 2개 항목에 얽매이지 마십시오. 예시는 형식 정의용일 뿐입니다. 결함이 있는 화차라면 1화부터 50화까지 10개든, 20개든 전부 배열에 한꺼번에 담아 반환해야 합니다.**
5. **동일한 상태에서 분석을 다시 누를 때 동일하고 일관된 결과가 나와야 하므로, 정확하고 엄밀하게 전수 조사하십시오.**

반드시 아래 JSON 형식으로만 응답하십시오. (No meta-commentary, 오직 한국어로 작성)
{{
    "scores": {{
        "consistency": 70,
        "grammar_flow": 70,
        "creativity": 70
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
    
    model = genai.GenerativeModel("models/gemini-2.5-flash")
    print("Sending request to Gemini 2.5 Flash...")
    response = await model.generate_content_async(
        map_prompt,
        generation_config={"max_output_tokens": 8192, "temperature": 0.2}
    )
    
    print("\n--- RESPONSE INFO ---")
    print(f"Prompt tokens: {model.count_tokens(map_prompt)}")
    print(f"Candidates:")
    for idx, candidate in enumerate(response.candidates):
        print(f"Candidate {idx} finish reason: {candidate.finish_reason}")
        print(f"Safety ratings: {candidate.safety_ratings}")
        
    print("\n--- TEXT OUTPUT ---")
    if response.text:
        print(response.text)
    else:
        print("No text output returned!")

if __name__ == "__main__":
    asyncio.run(run_debug())
