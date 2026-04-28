import json
import re
from llm_enhancer import llm_client


def _extract_json_object(text: str) -> str | None:
    if not text:
        return None

    s = text.strip()
    if s.startswith("{") and s.endswith("}"):
        return s

    fence_patterns = [
        r"```json\s*(\{[\s\S]*?\})\s*```",
        r"```\s*(\{[\s\S]*?\})\s*```",
    ]
    for pat in fence_patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1].strip()

    return None


def analyze_and_fix_errors(errors: list, original_spec: dict) -> dict:
    """
    分析错误并生成修正后的请求
    """
    system_prompt = """你是一个 API 测试专家。分析失败的 API 请求和错误信息，生成修正后的请求。

    输出格式为 JSON：
    {
        "fixed_requests": [
            {
                "original_endpoint": "...",
                "fixed_body": {...},
                "fixed_headers": {...},
                "explanation": "..."
            }
        ]
    }
    """

    prompt = f"""分析以下失败的 API 请求和错误信息：

原始 OpenAPI 规范：
```json
{json.dumps(original_spec, indent=2)[:4000]}
```

错误列表：
```json
{json.dumps(errors, indent=2)[:4000]}
```

请：
1. 分析每个错误的原因（如缺少必需字段、类型错误、格式不正确等）
2. 生成修正后的请求体
3. 解释修改了什么
4. 只输出 JSON
"""

    response = llm_client.chat(prompt, system_prompt)
    if not response:
        return {"fixed_requests": []}

    extracted = _extract_json_object(response)
    if not extracted:
        print(f"Failed to find JSON in LLM response: {response[:500]}")
        return {"fixed_requests": []}

    try:
        parsed = json.loads(extracted)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        print(f"Failed to parse LLM response: {extracted[:500]}")

    return {"fixed_requests": []}


def generate_fixed_requests_json(errors: list, openapi_spec: dict, output_path: str):
    """生成修正后的请求 JSON 文件"""
    fixed = analyze_and_fix_errors(errors, openapi_spec)
    with open(output_path, 'w') as f:
        json.dump(fixed, f, indent=2)
    return output_path
