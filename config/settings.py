import os
from dotenv import load_dotenv

load_dotenv()

# LLM 配置
LLM_API_KEY = os.getenv("OPENAI_API_KEY", "")
LLM_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("OPENAI_MODEL", "gpt-4-turbo-preview")

# RESTler 配置
RESTLER_PATH = os.getenv("RESTLER_PATH", "./data/restler/Restler")

# 数据库配置
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/test_results.db")

# 目录配置
DATA_DIR = "./data"
OPENAPI_SPECS_DIR = os.path.join(DATA_DIR, "openapi_specs")
RESTLER_RESULTS_DIR = os.path.join(DATA_DIR, "restler_results")
LLM_GENERATED_DIR = os.path.join(DATA_DIR, "llm_generated")

# 确保目录存在
for dir_path in [DATA_DIR, OPENAPI_SPECS_DIR, RESTLER_RESULTS_DIR, LLM_GENERATED_DIR]:
    os.makedirs(dir_path, exist_ok=True)
