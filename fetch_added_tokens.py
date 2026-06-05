from huggingface_hub import hf_hub_download
import json
import os

try:
    hf_token = os.environ.get("HF_TOKEN")
    file_path = hf_hub_download(
        repo_id="TaeHak/korean-harlequin-romance-LoRA",
        filename="added_tokens.json",
        token=hf_token
    )
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print("Added Tokens:", data)
except Exception as e:
    print("Error:", e)
