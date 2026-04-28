import json
import os
from openai import OpenAI
from config.settings import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

class LLMClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL
        )
        self.model = LLM_MODEL
    
    def chat(self, prompt, system_prompt=None):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,  # 降低随机性，使输出更稳定
                seed=42,  # 固定种子，使结果可重现
                max_tokens=4096,
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"LLM API error: {e}")
            return None

llm_client = LLMClient()
