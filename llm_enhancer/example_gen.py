import json
import re
import logging
from llm_enhancer import llm_client

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _clean_python_expressions(text: str) -> str:
    """
    清理 LLM 响应中的 Python 表达式和非法 JSON 内容
    """
    original_text = text
    
    # 1. 替换 .repeat() 表达式
    def replace_repeat(match):
        char = match.group(1)
        count = min(int(match.group(2)), 100)
        return f'"{char * count}"'
    
    text = re.sub(r'["\'](\w)["\']\.repeat\((\d+)\)', replace_repeat, text)
    
    # 2. 替换字符串乘法
    def replace_multiply(match):
        char = match.group(1)
        count = min(int(match.group(2)), 100)
        return f'"{char * count}"'
    
    text = re.sub(r'["\'](\w)["\']\s*\*\s*(\d+)', replace_multiply, text)
    
    # 3. 替换变体
    text = re.sub(r'["\'](\w)["\']\s*\.\s*repeat\s*\(\s*(\d+)\s*\)', replace_repeat, text)
    
    # 4. 移除 Python 注释
    text = re.sub(r'#.*$', '', text, flags=re.MULTILINE)
    
    # 5. 替换长字符串表达式
    text = re.sub(r'["\'][\w\s]*["\']\s*\+\s*["\'][\w\s]*["\']', '"a long string for testing"', text)
    
    if text != original_text:
        logger.info("Cleaned Python expressions from LLM response")
    
    return text


def _fix_json_syntax_errors(text: str) -> str:
    """
    修复常见的 JSON 语法错误
    
    包括：
    - 多余的花括号 } }
    - 对象内多余的花括号
    - 数组元素间缺少逗号
    - 最后一个元素后多余的逗号
    - 缺少逗号的情况
    """
    # 修复多余的花括号：} } 改为 }
    text = re.sub(r'\}\s*\}', '}', text)
    
    # 修复对象内多余的花括号：{ ... }} 改为 { ... }
    text = re.sub(r'(\{[^{}]*\})\}', r'\1', text)
    
    # 修复数组元素间缺少逗号
    text = re.sub(r'\}\s*\{', '},{', text)
    text = re.sub(r'\]\s*\[', '],[', text)
    
    # 修复最后一个元素后多余的逗号
    text = re.sub(r',\s*\]', ']', text)
    text = re.sub(r',\s*\}', '}', text)
    
    # 修复 { 后多余的逗号
    text = re.sub(r'\{\s*,', '{', text)
    
    # 修复 } 后缺少逗号，后面跟着 " 或 {
    text = re.sub(r'\}\s*("|\{)', r'},\1', text)
    
    # 修复 ] 后缺少逗号，后面跟着 [ 或 {
    text = re.sub(r'\]\s*(\[|\{)', r'],\1', text)
    
    # 修复值后缺少逗号（数字后跟 "）
    text = re.sub(r'(\d)\s*"', r'\1, "', text)
    
    # 修复 boolean/null 后缺少逗号
    text = re.sub(r'(true|false|null)\s*"', r'\1, "', text)
    
    return text


def _validate_and_fix_example(example: dict) -> dict:
    """
    验证并修复单个示例，确保所有字段都有正确的值
    """
    required_fields = ["endpoint", "method"]
    for field in required_fields:
        if field not in example:
            logger.warning(f"Example missing '{field}' field, skipping")
            return None
    
    # 确保 headers 存在
    if "headers" not in example or example["headers"] is None:
        example["headers"] = {}
    
    # 确保 headers 中的值是字符串
    if isinstance(example.get("headers"), dict):
        for key, value in example["headers"].items():
            if not isinstance(value, str):
                example["headers"][key] = str(value)
    
    # 确保 body 存在
    if "body" not in example:
        example["body"] = {}
    
    # 检查 Python 表达式残留
    body_str = json.dumps(example["body"])
    if ".repeat" in body_str or " * " in body_str:
        logger.warning(f"Python expression still present in body, replacing with safe value")
        example["body"] = {"value": "test_value"}
    
    return example


def _extract_json_array(text: str) -> str | None:
    """Extract a JSON array string from an LLM response."""
    if not text:
        return None

    s = text.strip()
    if s.startswith("[") and s.endswith("]"):
        return s

    fence_patterns = [
        r"```json\s*(\[[\s\S]*?\])\s*```",
        r"```\s*(\[[\s\S]*?\])\s*```",
    ]
    for pat in fence_patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()

    start = text.find("[")
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

        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start:i+1].strip()

    return None


def _extract_json_object(text: str) -> str | None:
    """Extract a JSON object string from an LLM response."""
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
                return text[start:i+1].strip()

    return None


def _try_parse_json_with_fixes(text: str) -> list | None:
    """
    尝试多种策略解析 JSON，包括自动修复语法错误
    """
    # 策略1：直接提取并解析 JSON 数组
    json_str = _extract_json_array(text)
    if json_str:
        try:
            result = json.loads(json_str)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass
    
    # 策略2：提取 JSON 对象并尝试提取 examples
    json_str = _extract_json_object(text)
    if json_str:
        try:
            result = json.loads(json_str)
            if isinstance(result, dict):
                examples = result.get("examples") or result.get("x-ms-examples") or []
                if isinstance(examples, list):
                    return examples
        except json.JSONDecodeError:
            pass
    
    # 策略3：修复语法错误后重试
    fixed_text = _fix_json_syntax_errors(text)
    if fixed_text != text:
        # 重新提取 JSON 数组
        json_str = _extract_json_array(fixed_text)
        if json_str:
            try:
                result = json.loads(json_str)
                if isinstance(result, list):
                    logger.info("Successfully parsed after fixing syntax errors")
                    return result
            except json.JSONDecodeError:
                pass
        
        # 重新提取 JSON 对象
        json_str = _extract_json_object(fixed_text)
        if json_str:
            try:
                result = json.loads(json_str)
                if isinstance(result, dict):
                    examples = result.get("examples") or result.get("x-ms-examples") or []
                    if isinstance(examples, list):
                        logger.info("Successfully parsed object after fixing syntax errors")
                        return examples
            except json.JSONDecodeError:
                pass
    
    return None


def generate_examples(openapi_spec: dict) -> list:
    """
    使用 LLM 生成示例请求
    
    Returns:
        list: 示例数组，每个元素包含 endpoint、method、headers、body
    """
    logger.info("Starting generate_examples")
    
    system_prompt = """你是一个 API 测试专家。根据 OpenAPI 规范生成高质量的示例请求体。

重要规则：
1. 输出必须是合法的 JSON 数组
2. 确保 JSON 语法完全正确，不要有多余的花括号
3. 每个对象必须正确开始和结束，例如 {"key": "value"} 而不是 {"key": "value"}}
4. 对象之间必须用逗号分隔
5. 最后一个对象后面不要有逗号
6. 绝对不能包含任何 Python 代码或表达式（如 .repeat(), * 等）
7. 字符串必须使用双引号，不能使用单引号
8. 所有值必须是字面量
9. 不要输出任何其他文字或解释

输出格式示例：
[
    {
        "endpoint": "/api/blog/posts",
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": {"id": 1, "body": "Sample content"}
    }
]"""
    
    prompt = f"""分析以下 OpenAPI 规范，为每个 POST/PUT 端点生成示例请求体：

```json
{json.dumps(openapi_spec, indent=2)[:8000]}

生成要求：
1. 为每个 POST/PUT 方法生成多个示例：
   - 正常场景（1个）
   - 边界场景（2-3个，如最小值、最大值、空值）
   - 异常场景（1-2个，如无效类型）
2. 数据必须严格符合 schema 定义
3. 如果请求体是 JSON，设置 "headers": {{"Content-Type": "application/json"}}
4. **重要**：必须使用实际的字面量值，不能使用任何编程表达式
5. 对于长字符串，请写出实际的文本（最多200个字符）
6. endpoint 路径中的参数占位符（如 {{postId}}）保持原样，不要替换
7. **特别注意**：确保 JSON 语法完全正确，不要有多余的花括号

输出必须是纯 JSON 数组，只输出 JSON，不要有任何其他文本。"""

    logger.info("Calling LLM for examples generation")
    response = llm_client.chat(prompt, system_prompt)
    
    if not response:
        logger.error("LLM returned empty response")
        return []
    
    # 保存原始响应
    import tempfile
    debug_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, prefix='llm_examples_raw_')
    debug_file.write(response)
    debug_file.close()
    logger.info(f"Saved raw LLM response to {debug_file.name}")
    
    # 清理 Python 表达式
    cleaned_response = _clean_python_expressions(response)
    
    # 尝试解析 JSON（自动修复语法错误）
    examples_array = _try_parse_json_with_fixes(cleaned_response)
    
    if examples_array is not None and isinstance(examples_array, list):
        # 验证并修复每个示例
        valid_examples = []
        for example in examples_array:
            fixed = _validate_and_fix_example(example)
            if fixed:
                valid_examples.append(fixed)
        
        logger.info(f"Success! Found {len(valid_examples)} valid examples")
        if valid_examples:
            return valid_examples
        else:
            logger.warning("All examples were invalid")
    else:
        logger.error("Failed to extract valid JSON from LLM response")
        logger.error(f"Response preview: {response[:500]}")
    
    logger.error("All extraction methods failed")
    return []


def generate_examples_json(openapi_spec: dict, output_path: str):
    """
    生成 RESTler 的 examples.json 文件
    
    格式符合 RESTler 文档要求:
    {
        "paths": {
            "/api/blog/posts": {
                "post": {
                    "1": {
                        "parameters": {
                            "__body__": {...},
                            "headers": {...}
                        }
                    }
                }
            }
        }
    }
    """
    logger.info(f"Generating examples.json at {output_path}")
    
    examples_array = generate_examples(openapi_spec)
    
    # 转换为 RESTler 期望的格式
    restler_examples = {"paths": {}}
    
    for idx, example in enumerate(examples_array):
        endpoint = example.get("endpoint", "")
        method = example.get("method", "").lower()
        headers = example.get("headers", {})
        body = example.get("body", {})
        
        if not endpoint or not method:
            logger.warning(f"Skipping example {idx}: missing endpoint or method")
            continue
        
        # 确保路径存在
        if endpoint not in restler_examples["paths"]:
            restler_examples["paths"][endpoint] = {}
        
        # 确保方法存在
        if method not in restler_examples["paths"][endpoint]:
            restler_examples["paths"][endpoint][method] = {}
        
        # 构建 parameters
        parameters = {}
        
        # 添加 headers 作为参数
        if headers:
            parameters["headers"] = headers
        
        # 添加 body（使用 __body__ 特殊关键字）
        if body:
            parameters["__body__"] = body
        
        # 添加示例（使用索引作为示例 ID）
        example_id = str(idx + 1)
        restler_examples["paths"][endpoint][method][example_id] = {
            "parameters": parameters
        }
    
    # 如果没有有效示例，创建最小示例
    if not restler_examples["paths"]:
        logger.warning("No valid examples generated, creating minimal example")
        restler_examples = {
            "paths": {
                "/api/blog/posts": {
                    "get": {
                        "1": {
                            "parameters": {}
                        }
                    }
                }
            }
        }
    
    with open(output_path, 'w') as f:
        json.dump(restler_examples, f, indent=2)
    
    logger.info(f"Successfully generated {output_path} with {len(examples_array)} examples")
    return output_path


def generate_examples_array(openapi_spec: dict) -> list:
    """
    向后兼容：返回数组格式
    """
    logger.warning("Using deprecated generate_examples_array")
    return generate_examples(openapi_spec)