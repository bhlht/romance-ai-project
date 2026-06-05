from huggingface_hub import list_repo_files
import os

try:
    repo_id = "TaeHak/korean-harlequin-romance-LoRA"
    token = os.environ.get("HF_TOKEN")
    files = list_repo_files(repo_id=repo_id, token=token)
    print("Files in repo:")
    for f in files:
        print(f" - {f}")
except Exception as e:
    print("Error:", e)
