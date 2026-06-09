import requests
import json

BACKEND_URL = "http://127.0.0.1:8082"

def test_comprehensive_review():
    print("Testing /analyze/review_comprehensive...")
    
    payload = {
        "model": "models/gemini-3-flash-preview",  # Flash model to trigger auto-upgrade to Pro
        "memory_chain": [
            {
                "chapter": 1,
                "summary": "은우는 은밀한 계약을 통해 해준의 저택에 머물게 된다. 해준은 얼어붙은 눈빛으로 그녀를 경계한다."
            },
            {
                "chapter": 14,
                "summary": "해준은 은우에게 깊어지는 소유욕을 느끼며 갈등이 심화된다. 서로간의 감정이 고조되지만 오해로 엇갈린다."
            },
            {
                "chapter": 15,
                "summary": "14화에서 언급된 갈등이 아무런 감정적 서사 없이 15화에서 급작스럽게 풀리며 어색한 키스신이 전개된다."
            }
        ]
    }
    
    try:
        res = requests.post(f"{BACKEND_URL}/analyze/review_comprehensive", json=payload, timeout=120)
        print(f"Status Code: {res.status_code}")
        if res.status_code == 200:
            print("Response successfully received!")
            print(json.dumps(res.json(), ensure_ascii=False, indent=2))
        else:
            print(f"Failed with response: {res.text}")
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_comprehensive_review()
