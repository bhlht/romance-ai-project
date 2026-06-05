import os
from huggingface_hub import HfApi
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("HF_TOKEN")
api = HfApi(token=token)

try:
    user = api.whoami()
    print(f"Token is valid. User: {user['name']}")
    
    repo_id = "TaeHak/korean-harlequin-romance-LoRA"
    info = api.model_info(repo_id)
    print(f"Repo found: {repo_id}")
except Exception as e:
    print(f"Token or Repo Error: {e}")
