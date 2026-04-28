import json
import re
from llm_enhancer import llm_client

def _split_method_and_path(s: str) -> tuple[str, str] | None:
    """
    Convert strings like "POST /posts/{id}" into ("POST", "/posts/{id}").
    Returns None if the format is unexpected.
    """
    if not s or not isinstance(s, str):
        return None
    parts = s.strip().split(None, 1)
    if len(parts) != 2:
        return None
    method, path = parts[0].upper(), parts[1].strip()
    if not method or not path:
        return None
    # RESTler expects just the OpenAPI path, not the method in the path.
    return method, path

def _extract_json_object(text: str) -> str | None:
    """
    Extract a JSON object or array string from an LLM response.
    """
    if not text:
        return None

    # 移除 markdown 代码块标记
    text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text, flags=re.MULTILINE)
    
    # 移除 Python 表达式 "a" * 100 等
    text = re.sub(r'"\s*\*\s*\d+', '"xxx"', text)
    text = re.sub(r'[\w\s]+\s*\*\s*\d+', '"xxx"', text)
    
    text = text.strip()
    
    # 查找 JSON 对象或数组
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        if start_char not in text:
            continue
        
        start = text.find(start_char)
        if start == -1:
            continue
        
        depth = 0
        in_string = False
        escape = False
        
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
                
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    result = text[start:i+1].strip()
                    # 验证是否为有效 JSON
                    try:
                        json.loads(result)
                        return result
                    except:
                        # 如果不是有效 JSON，继续尝试
                        pass
    
    return None

def generate_dependencies(openapi_spec: dict) -> dict:
    """
    使用 LLM 生成 API 依赖关系
    """
    system_prompt = """你是一个 API 测试专家。分析 OpenAPI 规范，找出 API 端点之间的依赖关系。
    例如：POST /users 必须在 GET /users/{id} 之前，PUT /users/{id} 必须在 POST 之后。
        
    规则：
    - POST 创建资源的端点，是其他需要该资源 ID 的端点的生产者
    - 路径中包含 {param} 的端点，依赖对应的创建端点
    
    输出格式为 JSON，结构如下：
    {
        "dependencies": [
            {
                "producer": "POST /users",
                "consumer": "GET /users/{id}",
                "type": "resource_creation"
            }
        ]
    }
    """

    # 只取 paths 部分，大幅减少 token
    paths = openapi_spec.get("paths", {})
    # 简化：只保留路径和方法，不保留详细 schema
    simplified = {}
    for path, methods in paths.items():
        simplified[path] = list(methods.keys())
    
    spec_str = json.dumps(simplified, indent=2)
    print("--------------------------------")
    print(spec_str)

    
    prompt = f"""分析以下 OpenAPI 规范，找出所有 API 端点之间的依赖关系：

```json
{spec_str}
请输出 JSON 格式的依赖关系列表。"""

    response = llm_client.chat(prompt, system_prompt)
    if not response:
        return {"dependencies": []}

    extracted = _extract_json_object(response)
    if not extracted:
        print(f"Failed to find JSON in LLM response: {response}")
        return {"dependencies": []}

    try:
        parsed = json.loads(extracted)
    except json.JSONDecodeError:
        print(f"Failed to parse LLM JSON: {extracted}")
        return {"dependencies": []}

    if isinstance(parsed, dict):
        # Ensure expected shape
        if "dependencies" not in parsed or not isinstance(parsed.get("dependencies"), list):
            return {"dependencies": []}
        return parsed

    return {"dependencies": []}

def generate_annotations_json(openapi_spec: dict, output_path: str):
    """生成 RESTler 的 annotations.json 文件"""
    deps = generate_dependencies(openapi_spec)

    annotations = {"x-restler-global-annotations": []}
    
    # 获取依赖列表，兼容两种格式
    dependencies = deps.get("dependencies", [])
    
    # 如果 dependencies 为空，可能是 LLM 直接返回了数组
    if not dependencies and isinstance(deps, list):
        dependencies = deps
    elif not dependencies and isinstance(deps, dict) and "dependencies" not in deps:
        # 尝试将整个 deps 当作依赖数组
        if isinstance(deps, list):
            dependencies = deps
        elif isinstance(deps, dict):
            # 可能是单个依赖对象
            if "producer" in deps or "consumer" in deps:
                dependencies = [deps]
    
    for dep in dependencies:
        # 尝试多种字段名格式
        producer_str = dep.get("producer") or dep.get("producer_endpoint") or ""
        consumer_str = dep.get("consumer") or dep.get("consumer_endpoint") or ""
        
        # 如果 producer_str 不包含方法，尝试从其他字段获取
        producer_method = dep.get("producer_method") or dep.get("method") or ""
        consumer_method = dep.get("consumer_method") or ""
        
        # 解析 producer
        if producer_str and " " not in producer_str and not producer_method:
            # 路径中没有方法，需要从其他字段获取
            pass
        
        producer = _split_method_and_path(producer_str) if producer_str else None
        consumer = _split_method_and_path(consumer_str) if consumer_str else None
        
        # 如果解析失败但有单独的方法字段，手动构建
        if (not producer or not producer[0]) and producer_method and producer_str:
            producer = (producer_method.upper(), producer_str)
        if (not consumer or not consumer[0]) and consumer_method and consumer_str:
            consumer = (consumer_method.upper(), consumer_str)
        
        if not producer or not consumer:
            continue

        producer_method, producer_endpoint = producer
        consumer_method, consumer_endpoint = consumer

        annotations["x-restler-global-annotations"].append({
            "producer_endpoint": producer_endpoint,
            "producer_method": producer_method.lower(),
            "consumer_endpoint": consumer_endpoint,
            "consumer_method": consumer_method.lower(),
        })

    with open(output_path, 'w') as f:
        json.dump(annotations, f, indent=2)

    print(f"Generated annotations.json with {len(annotations['x-restler-global-annotations'])} dependencies")
    return output_path
    
