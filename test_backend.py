import requests
import time

URL = "https://romance-ai-backend-46410417920.asia-southeast1.run.app"

def test_ping():
    print("Pinging backend...")
    try:
        res = requests.get(f"{URL}/ping", timeout=30)
        print(f"Status: {res.status_code}")
        print(f"Response: {res.json()}")
    except Exception as e:
        print(f"Ping failed: {e}")

def test_generate():
    print("\nTesting generation (this may take a minute)...")
    payload = {
        "prompt": "한 남자가 눈 내리는 창밖을 보며 과거를 회상한다.",
        "max_length": 100,
        "temperature": 0.7,
        "model": "DeepSeek-7B (Fine-tuned)"
    }
    try:
        start_time = time.time()
        res = requests.post(f"{URL}/generate/romance", json=payload, timeout=600)
        end_time = time.time()
        print(f"Status: {res.status_code}")
        if res.status_code == 200:
            import json
            gen_text = res.json().get('generated_text', '')
            results = {
                "time_taken": end_time - start_time,
                "gen_text_repr": repr(gen_text),
                "gen_text_head": gen_text[:500]
            }
            with open("test_output.json", "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"Results written to test_output.json. Time: {results['time_taken']:.2f}s")
        else:
            print(f"Error: {res.text}")
    except Exception as e:
        print(f"Generation failed: {e}")

if __name__ == "__main__":
    test_ping()
    test_generate()
