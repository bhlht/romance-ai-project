import os
import requests
from dotenv import load_dotenv

load_dotenv()

headers = {
    "Content-Type": "application/json"
}

data = {
    "prompt": "수연은 차가운 눈으로 진우를 올려다보았다. \"당신이 나한테 어떻게 이럴 수 있어?\"\n\n진우는",
    "model": "DeepSeek-7B (Fine-tuned)",
    "temperature": 0.7,
    "max_length": 150
}

url = "https://romance-ai-backend-46410417920.asia-southeast1.run.app/generate/romance"
print(f"Sending request to {url}...")
try:
    response = requests.post(url, headers=headers, json=data, timeout=300)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        print("Response Text:")
        print(response.json())
    else:
        print(f"Error: {response.text}")
except Exception as e:
    print(f"Request failed: {e}")
