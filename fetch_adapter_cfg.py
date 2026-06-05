import urllib.request
import json
import os

url = 'https://huggingface.co/TaeHak/korean-harlequin-romance-LoRA/raw/main/adapter_config.json'
req = urllib.request.Request(url)
hf_token = os.environ.get('HF_TOKEN')
if hf_token:
    req.add_header('Authorization', f'Bearer {hf_token}')

try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode('utf-8'))
        print("Adapter Base Model:", data.get("base_model_name_or_path"))
except Exception as e:
    print("Error:", e)
