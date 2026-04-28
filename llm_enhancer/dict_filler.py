import json
import re
from llm_enhancer import llm_client

def _repair_common_non_json_patterns(s: str) -> str:
    """
    Repair a few common non-JSON patterns seen in LLM output.
    Currently handles Python-like string repetition: "a" * 100
    (converts to "aaaa...." as a JSON string).
    Also handles JS-like: "a".repeat(100) (and a spaced variant: "a" . repeat(100))
    Also handles simple concatenation: "prefix" + "x".repeat(100)
    """
    if not s:
        return s

    # Replace occurrences like: "prefix" + "x".repeat(1000)
    # Keep this conservative and only support string literal + string literal repeat.
    #
    # IMPORTANT: run this BEFORE bare ".repeat" replacement; otherwise the repeat
    # is replaced first and the remaining "+" expression becomes unmatchable.
    def repl_plus_repeat(m: re.Match) -> str:
        prefix = m.group(1)
        rep_lit = m.group(2)
        try:
            n = int(m.group(3))
        except Exception:
            return m.group(0)
        if n < 0:
            return m.group(0)
        n = min(n, 10000)
        return json.dumps(prefix + (rep_lit * n))

    s = re.sub(
        r'"([^"\\]*(?:\\.[^"\\]*)*)"\s*\+\s*"([^"\\]*(?:\\.[^"\\]*)*)"\s*\.\s*repeat\(\s*(\d+)\s*\)',
        repl_plus_repeat,
        s,
    )

    # Replace occurrences like:
    # - "a".repeat(100)
    # - "a" . repeat(100)
    # Seen in some model outputs attempting pseudo-code inside JSON.
    def repl_dot_repeat(m: re.Match) -> str:
        literal = m.group(1)
        try:
            n = int(m.group(2))
        except Exception:
            return m.group(0)
        if n < 0:
            return m.group(0)
        n = min(n, 10000)
        return json.dumps(literal * n)

    s = re.sub(
        r'"([^"\\]*(?:\\.[^"\\]*)*)"\s*\.\s*repeat\(\s*(\d+)\s*\)',
        repl_dot_repeat,
        s,
    )

    # Replace un-executable JS expression that is not JSON, e.g.:
    # "Body with binary data: " + String.fromCharCode(...Array(256).keys())
    # We can't evaluate this safely here, so coerce to a stable placeholder.
    s = re.sub(
        r'String\.fromCharCode\(\s*\.\.\.\s*Array\(\s*\d+\s*\)\.keys\(\s*\)\s*\)',
        '"<CHARCODES_0_N>"',
        s,
    )

    # Replace occurrences like:  "a" * 100   or  " " * 10
    # Keep this conservative to avoid surprising transformations.
    def repl(m: re.Match) -> str:
        literal = m.group(1)
        try:
            n = int(m.group(2))
        except Exception:
            return m.group(0)
        if n < 0:
            return m.group(0)
        # Cap to keep files reasonable and avoid memory issues.
        n = min(n, 10000)
        return json.dumps(literal * n)

    return re.sub(r'"([^"\\]*(?:\\.[^"\\]*)*)"\s*\*\s*(\d+)', repl, s)

def _extract_json_object(text: str) -> str | None:
    """
    Best-effort extraction of a *complete* JSON object from an LLM response.
    """
    if not text:
        return None

    s = text.strip()
    if s.startswith("{") and s.endswith("}"):
        return s

    # Prefer fenced code blocks first.
    fence_patterns = [
        r"```json\s*(\{[\s\S]*?\})\s*```",
        r"```\s*(\{[\s\S]*?\})\s*```",
    ]
    for pat in fence_patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # Fallback: find the first balanced top-level {...} block.
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
                return text[start : i + 1].strip()

    # 如果到这里还没有找到完整的 JSON，说明可能被截断了
    # 尝试返回从 start 到末尾的内容
    truncated = text[start:].strip()
    if truncated.startswith("{") and truncated.count("{") > truncated.count("}"):
        # 添加缺少的闭合括号
        missing = truncated.count("{") - truncated.count("}")
        truncated += "}" * missing
        return truncated

    return None

def _coerce_restler_dict_shape(d: dict) -> dict:
    """
    Ensure the dictionary is JSON-serializable and in a RESTler-friendly shape:
    - fuzzable_* keys map to list[str]
    - restler_custom_payload maps to dict[str, list[str]]
    """
    if not isinstance(d, dict):
        return {}

    out: dict = {}

    def as_list_of_strings(x):
        if x is None:
            return []
        if isinstance(x, list):
            return [str(v) for v in x if v is not None]
        # Some models return a single string instead of a list.
        if isinstance(x, str):
            return [x]
        return [str(x)]

    out["restler_fuzzable_string"] = as_list_of_strings(d.get("restler_fuzzable_string"))
    out["restler_fuzzable_int"] = as_list_of_strings(d.get("restler_fuzzable_int"))

    custom = d.get("restler_custom_payload")
    custom_out: dict[str, list[str]] = {}
    if isinstance(custom, dict):
        for k, v in custom.items():
            if k is None:
                continue
            custom_out[str(k)] = as_list_of_strings(v)
    out["restler_custom_payload"] = custom_out

    # Cap extreme values to keep files reasonable for RESTler + git logs.
    def cap_list(values: list[str], max_items: int, max_len: int) -> list[str]:
        capped = []
        for s in values[:max_items]:
            if not isinstance(s, str):
                s = str(s)
            if len(s) > max_len:
                s = s[:max_len]
            capped.append(s)
        return capped

    out["restler_fuzzable_string"] = cap_list(out["restler_fuzzable_string"], max_items=200, max_len=20000)
    out["restler_fuzzable_int"] = cap_list(out["restler_fuzzable_int"], max_items=200, max_len=50)
    for k, v in list(out["restler_custom_payload"].items()):
        out["restler_custom_payload"][k] = cap_list(v, max_items=200, max_len=20000)

    return out

def generate_dict_values(openapi_spec: dict, debug_base_path: str | None = None) -> dict:
    """
    使用 LLM 生成字典值
    """
    system_prompt = """你是一个 API 测试专家。根据 OpenAPI 规范中的参数定义，生成合理的测试数据值。
    重要规则：
    1. 只输出纯 JSON，不要包含任何 Python/JavaScript 表达式
    2. 禁止使用 .repeat()、+、* 等运算符
    3. 所有字符串必须是字面量，如 "test"、"aaaaaaaaaa"
    4. 不要生成超长字符串（超过 50 字符）
    5. 不要包含注释或尾随逗号
    
    输出格式为 JSON：
    {
        "restler_fuzzable_string": ["test1", "test2"],
        "restler_fuzzable_int": ["1", "2"],
        "restler_custom_payload": {
            "param1": ["value1", "value2"]
        }
    }
    """
    
    # 只提取 parameters 和 requestBody 中需要的参数名，大幅减少输入
    param_names = set()
    
    # 从 paths 中提取参数名
    paths = openapi_spec.get("paths", {})
    for path, methods in paths.items():
        for method, details in methods.items():
            if method in ["get", "post", "put", "delete"]:
                # 路径参数
                params = details.get("parameters", [])
                for p in params:
                    param_names.add(p.get("name", ""))
                # 请求体参数
                body = details.get("requestBody", {})
                if body:
                    schema = body.get("content", {}).get("application/json", {}).get("schema", {})
                    props = schema.get("properties", {})
                    for prop_name in props.keys():
                        param_names.add(prop_name)
    
    # 只传入参数名列表，不传完整 schema
    param_list = list(param_names)
    if not param_list:
        param_list = ["page", "per_page", "postId", "id", "body", "checksum", "title"]
    
    prompt = f"""API 需要以下参数：{', '.join(param_list)}

为每个参数生成 3-5 个合理的测试值。

要求：
1. 只输出纯 JSON，不要使用任何表达式
2. 字符串直接用字面量，如 "test"
3. 不要生成超长字符串

输出格式：
{{
    "restler_custom_payload": {{
        "page": ["1", "10", "100"],
        "per_page": ["5", "10", "50"],
        "postId": ["1", "2", "3"],
        "body": ["test content", "hello world"]
    }}
}}"""

    response = llm_client.chat(prompt, system_prompt)
    if response:
        extracted = _extract_json_object(response)
        if extracted:
            try:
                repaired = _repair_common_non_json_patterns(extracted)
                try:
                    parsed = json.loads(repaired)
                except json.JSONDecodeError:
                    # Sometimes the model returns a valid JSON object prefix then truncates.
                    # Try decoding the longest valid prefix.
                    dec = json.JSONDecoder()
                    parsed, end = dec.raw_decode(repaired)
                    if end <= 0:
                        raise

                if isinstance(parsed, dict):
                    coerced = _coerce_restler_dict_shape(parsed)
                    if coerced:
                        return coerced
            except Exception:
                print(f"Failed to parse LLM JSON: {extracted}")
                if debug_base_path:
                    try:
                        with open(debug_base_path + ".llm_response.txt", "w", encoding="utf-8", errors="replace") as f:
                            f.write(response)
                        with open(debug_base_path + ".extracted.jsonish.txt", "w", encoding="utf-8", errors="replace") as f:
                            f.write(extracted)
                        # repaired may not exist if failure happened before assignment
                        try:
                            with open(debug_base_path + ".repaired.json.txt", "w", encoding="utf-8", errors="replace") as f:
                                f.write(repaired)
                        except Exception:
                            pass
                    except Exception as e:
                        print(f"WARNING: failed writing debug artifacts: {e}")
        else:
            print(f"Failed to find JSON in LLM response: {response[:500]}")

    # Safe fallback so the pipeline can proceed.
    return {
        "restler_fuzzable_string": ["test", "", "null", "<script>alert(1)</script>"],
        "restler_fuzzable_int": ["0", "1", "-1", "999999"],
        "restler_custom_payload": {}
    }

def generate_dict_json(openapi_spec: dict, output_path: str):
    """生成 RESTler 的 dict.json 文件"""
    dict_values = generate_dict_values(openapi_spec, debug_base_path=output_path)

    with open(output_path, 'w') as f:
        json.dump(dict_values, f, indent=2)

    return output_path
