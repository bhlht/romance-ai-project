import asyncio
import os
import sys

# Windows CP949 콘솔 인코딩 우회
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# 프로젝트 루트 경로 추가
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.gemini_service import GeminiService

async def test_ledger_fallback():
    print("==================================================")
    print("[TEST] Starting Ledger Fallback System Test")
    print("==================================================")
    
    gemini = GeminiService()
    if not gemini.api_key:
        print("[ERROR] GEMINI_API_KEY가 설정되어 있지 않습니다.")
        return

    # 매우 자극적인 성인용 19금 씬 묘사를 포함한 모의 텍스트
    sensitive_chapter_text = (
        "그녀는 침대 머리에 양손이 결합되어 갇혀 있었다. "
        "만세가 그녀의 옷을 벗기기 시작하자 은미는 거칠게 헐떡였다. "
        "붉게 물든 뺨 위로 뜨거운 숨결이 닿았다. "
        "두 사람은 격렬하게 육체적 관계를 가졌고, 침실 안에는 야릇한 신음과 교성이 가득 울려 퍼졌다. "
        "만세는 그의 페니스를 그녀의 깊은 속살로 삽입했고, 은미는 쾌감의 절정 속에서 남주의 이름을 부르며 애원했다. "
        "합방이 끝난 후 만세는 '다시는 내 허락 없이 떠나지 마라'며 그녀에게 단호한 독점욕을 드러냈다. "
        "은미는 어쩔 수 없이 고개를 끄덕이며 그의 품에 안겼다."
    )
    
    unresolved_text = "[제7화] 만세가 은미를 자택에 머물게 하겠다고 선언함. 은미는 도망칠 계획을 세움."
    ch_summary = "만세가 은미와 격렬한 밤을 보내고 난 후, 은미는 만세의 압도적인 소유욕에 굴복하는 척하며 자택에 머무르기로 합의한다."
    
    print("\n--- 1. 민감 문장 필터링 테스트 (_filter_sensitive_sentences) ---")
    filtered = gemini._filter_sensitive_sentences(sensitive_chapter_text)
    print(f"Original Length: {len(sensitive_chapter_text)} chars")
    print(f"Filtered Length: {len(filtered)} chars")
    print("Filtered Text:")
    print(filtered)
    
    # 키워드가 잘 걸러졌는지 체크
    keywords_checked = ["옷을 벗", "헐떡", "신음", "교성", "페니스", "삽입", "쾌감", "절정"]
    passed_filtering = True
    for kw in keywords_checked:
        if kw in filtered:
            print(f"[FAILED] Filtering Failed: '{kw}' keyword still remains.")
            passed_filtering = False
    if passed_filtering:
        print("[SUCCESS] Filtering Logic Check Passed (All sensitive keywords removed)!")

    print("\n--- 2. 다단계 Fallback 추출 API 테스트 (1단계 또는 2/3단계 복구) ---")
    try:
        ledger = await gemini.extract_continuity_ledger_with_fallback(
            chapter_num=8,
            chapter_text=sensitive_chapter_text,
            unresolved_text_c=unresolved_text,
            ch_summary=ch_summary
        )
        print("\n[SUCCESS] Extracted Continuity Ledger:")
        import json
        print(json.dumps(ledger, ensure_ascii=False, indent=2))
        
        # fallback_applied 확인
        if ledger.get("fallback_applied"):
            print("\n[RESULT] Safety filter triggered, successfully recovered using FALLBACK!")
        else:
            print("\n[RESULT] Successfully extracted directly using basic model request!")
            
        # 결과에 필수 키가 모두 존재하는지 검증
        required_keys = ["chapter", "promises_made", "open_threads", "established_facts", "relationship_states", "chapter_end_state"]
        all_keys_exist = all(k in ledger for k in required_keys)
        if all_keys_exist:
            print("[SUCCESS] JSON Schema Verification Passed!")
        else:
            print("[FAILED] JSON Schema Verification Failed (Missing keys).")
            
    except Exception as e:
        print(f"[FAILED] Test Failed with Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_ledger_fallback())
