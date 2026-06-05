import requests
import json

BACKEND_URL = "https://romance-ai-backend-46410417920.asia-southeast1.run.app"

def test_single_generation():
    print("Testing /generate/romance with In-World Prompting...")
    
    # We simulate what the frontend app.py would now construct
    in_world_prompt = """작품명: 미정 (장르: 로맨스 웹소설)
주요 등장인물: 태준: 차가운 재벌 3세. 지수: 당찬 화가.
인물 관계 및 배경 설정: 오해로 점철된 관계 / 현대 서울
전체 전개 요약: 두 사람은 오해를 풀고 서로의 마음을 확인한다.
이번 화 전개 목표: 감정 폭발과 갈등 해소
작가의 특별 메모: 지수의 감정을 애절하게 표현할 것.

=========================
본문

태준은 굳게 닫힌 지수의 화실 문을 차마 두드리지 못하고 서 있었다."""
    
    data = {
        "prompt": "dummy",
        "max_length": 800,
        "temperature": 0.7,
        "model": "DeepSeek-7B (Fine-tuned)",
        "chars": "김만세: 수백억 자산가. 최은미: 생계형 백수.",
        "world": "현대 서울, 노량진",
        "plot_summary": "우연히 만세와 은미가 얽히면서 벌어지는 코믹 로맨스.",
        "ch_focus": "두 사람의 첫 밀착 스킨십과 설렘",
        "writer_memo": "만세의 시점에서 당황스러움과 설렘이 함께 묘사되도록.",
        "context": "서늘하게 가라앉은 눈빛으로 은밀히 수행원들을 호출하려던 수백억 자산가 김만세는, \"백수라 합의금 물어줄 돈도 없으면서 무조건 뛰어요!\"라며 제 손목을 덥석 쥐고 노량진의 비좁은 골목길로 내달리는 최은미에게 속절없이 끌려가고 말았다. 이내 막다른 건물 틈새에 숨어 거친 숨결이 얽힐 만큼 옴짝달싹 못 하고 몸을 밀착하게 된 두 사람 사이로 아찔한 열기가 피어올랐다. \"걱정 마요, 내가 오빠 안 다치게 지켜줄게요.\"라고 속삭이는 그녀의 순진하고도 결연한 눈동자 앞에서, 평생을 강자로 군림해 온 만세의 심장이 생전 처음 겪는 짜릿함에 터질 듯 요동치고 있었다."
    }
    
    try:
        res = requests.post(f"{BACKEND_URL}/generate/romance", json=data)
        print(f"Status: {res.status_code}")
        if res.status_code == 200:
            gen_text = res.json().get("generated_text", "")
            
            # Save to file to avoid console encoding issues
            result = {"status": res.status_code, "generated_text": gen_text}
            with open("d:/myProject/streamlit/test_inworld_result.json", "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print("Test results written to test_inworld_result.json")
        else:
            print(f"Error: {res.text}")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_single_generation()
