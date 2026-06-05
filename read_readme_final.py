from huggingface_hub import hf_hub_download
import os

try:
    repo_id = "TaeHak/korean-harlequin-romance-LoRA"
    token = os.environ.get("HF_TOKEN")
    file_path = hf_hub_download(
        repo_id=repo_id,
        filename="final_model/README.md",
        token=token
    )
    with open(file_path, "r", encoding="utf-8") as f:
        print(f.read())
except Exception as e:
    print("Error:", e)
