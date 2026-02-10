import os
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
from peft import PeftModel
import asyncio
from dotenv import load_dotenv

load_dotenv()

# Mock mode flag - set to True if no GPU or for local testing
MOCK_MODE = os.getenv("MOCK_MODE", "False").lower() == "true"

class RomanceModel:
    def __init__(self, base_model_path="deepseek-ai/deepseek-llm-7b-base", lora_path="TaeHak/korean-harlequin-romance-LoRA"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.tokenizer = None
        self.model = None
        self.is_loaded = False
        self.base_model_path = base_model_path
        self.lora_path = lora_path

    def load_model(self):
        if self.is_loaded:
            return

        # [GCP Deployment] Force Real Loading
        if MOCK_MODE:
            print("WARNING: Running in MOCK_MODE.")
            self.is_loaded = True
            return

        print(f"🚀 Initializing Model on Device: {self.device}")
        
        # Always use Hugging Face for Cloud Run to ensure consistency
        self.lora_path = "TaeHak/korean-harlequin-romance-LoRA"
        print(f"☁️ Downloading LoRA adapter from Hugging Face: {self.lora_path}")

        # 1. Login to Hugging Face (Required for Private Repo)
        token = os.getenv("HF_TOKEN")
        
        print("📥 Loading Tokenizer...")
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.base_model_path, 
            trust_remote_code=True,
            token=token
        )
        self.tokenizer.pad_token = self.tokenizer.eos_token # Fix padding
        
        print("📥 Loading Base Model (DeepSeek-7B 4-bit)...")
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16
        )

        try:
            self.model = AutoModelForCausalLM.from_pretrained(
                self.base_model_path,
                quantization_config=bnb_config,
                device_map="auto",
                trust_remote_code=True,
                token=token
            )
        except Exception as e:
            print(f"❌ Base Model Load Error: {e}")
            raise e

        print(f"🔗 Merging LoRA Adapter: {self.lora_path}")
        try:
            self.model = PeftModel.from_pretrained(
                self.model, 
                self.lora_path,
                token=token
            )
            print("✅ LoRA Adapter Loaded Successfully!")
        except Exception as e:
            print(f"❌ LoRA Load Error (Check internet/token): {e}")
            raise e

        self.model.eval()
        self.is_loaded = True
        print("🎉 Model Ready for Romance Generation!")

    async def generate_text(self, prompt: str, max_length: int = 512, temperature: float = 0.7):
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded.")

        if MOCK_MODE:
            # Simulate processing time
            await asyncio.sleep(1) 
            return f"[MOCK GENERATION] Following the prompt '{prompt}', the protagonist gazed into the distance. 'Is this love?' she whispered. The mock model continues to generate text to simulate the output length."

        # Real Generation
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_length,
                do_sample=True,
                temperature=temperature,
                top_p=0.95,
                pad_token_id=self.tokenizer.eos_token_id
            )
        
        generated_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        # Remove original prompt from output if needed, but usually users want continuation
        # For this logic, we return the full text or just continuation depending on UI needs.
        # Let's return just the new part for cleaner appending, or full. 
        # Usually models return prompt + new.
        
        # Simple processing to remove prompt if redundant:
        if generated_text.startswith(prompt):
            generated_text = generated_text[len(prompt):]
            
        return generated_text

# Global instance
romance_model = RomanceModel()
