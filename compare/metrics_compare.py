import json
import os
from typing import Dict, Any, List


def find_testing_summary(search_dir: str) -> str | None:
    """递归查找 testing_summary.json 文件"""
    if not search_dir or not os.path.exists(search_dir):
        return None
    for root, dirs, files in os.walk(search_dir):
        if "testing_summary.json" in files:
            return os.path.join(root, "testing_summary.json")
    return None


def find_error_buckets(search_dir: str) -> str | None:
    """递归查找 errorBuckets.json 文件"""
    if not search_dir or not os.path.exists(search_dir):
        return None
    for root, dirs, files in os.walk(search_dir):
        if "errorBuckets.json" in files:
            return os.path.join(root, "errorBuckets.json")
    return None


def parse_testing_summary(summary_file: str) -> Dict[str, Any]:
    """解析 testing_summary.json 文件"""
    if os.path.isdir(summary_file):
        summary_file = find_testing_summary(summary_file)

    if not summary_file or not os.path.exists(summary_file):
        print("Warning: testing_summary.json not found")
        return {
            "total_requests": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0.0,
            "coverage": 0.0,
            "bugs_found": 0
        }

    try:
        with open(summary_file, 'r') as f:
            data = json.load(f)

        # 解析覆盖率
        coverage_str = data.get("final_spec_coverage", "0 / 0")
        if isinstance(coverage_str, str) and "/" in coverage_str:
            parts = coverage_str.split("/")
            covered = int(parts[0].strip())
            total_spec = int(parts[1].strip())
            coverage = (covered / total_spec * 100) if total_spec > 0 else 0.0
        else:
            coverage = float(coverage_str) if isinstance(coverage_str, (int, float)) else 0.0

        # 解析通过率
        valid = 0
        total_requests = 0
        valid_str = data.get("rendered_requests_valid_status", "0 / 0")
        
        if isinstance(valid_str, str) and "/" in valid_str:
            parts = valid_str.split("/")
            valid = int(parts[0].strip())
            total_requests = int(parts[1].strip())
            pass_rate = (valid / total_requests * 100) if total_requests > 0 else 0.0
        else:
            pass_rate = float(valid_str) if isinstance(valid_str, (int, float)) else 0.0
            rendered = data.get("rendered_requests", 0)
            if isinstance(rendered, str) and "/" in rendered:
                parts = rendered.split("/")
                total_requests = int(parts[1].strip())
            else:
                total_requests = int(rendered) if isinstance(rendered, (int, float)) else 0
            valid = int(total_requests * pass_rate / 100) if total_requests > 0 else 0

        # 统计 Bug 实例总数（而不是类型数）
        bug_buckets = data.get("bug_buckets", {})
        bugs_found = 0
        if isinstance(bug_buckets, dict):
            for bucket_name, bucket in bug_buckets.items():
                if isinstance(bucket, dict):
                    # 格式: {"type_name": {"count": 2}}
                    bugs_found += bucket.get("count", 1)
                elif isinstance(bucket, (int, float)):
                    # 格式: {"type_name": 2}
                    bugs_found += bucket
                else:
                    # 其他情况，每个类型算 1 个
                    bugs_found += 1
        elif isinstance(bug_buckets, list):
            bugs_found = len(bug_buckets)

        return {
            "total_requests": total_requests,
            "passed": valid,
            "failed": max(total_requests - valid, 0),
            "pass_rate": pass_rate,
            "coverage": coverage,
            "bugs_found": bugs_found
        }
    except Exception as e:
        print(f"Error parsing summary file: {e}")
        return {
            "total_requests": 0,
            "passed": 0,
            "failed": 0,
            "pass_rate": 0.0,
            "coverage": 0.0,
            "bugs_found": 0
        }


def parse_error_buckets(error_file: str) -> List[Dict]:
    """解析 errorBuckets.json 文件"""
    if not error_file or not error_file.strip():
        return []

    if os.path.isdir(error_file):
        error_file = find_error_buckets(error_file)

    if not error_file or not os.path.exists(error_file):
        print(f"Warning: errorBuckets.json not found at {error_file}")
        return []

    try:
        with open(error_file, 'r') as f:
            data = json.load(f)

        raw_buckets = data.get("errorBuckets", [])
        errors = []
        if isinstance(raw_buckets, list):
            for bucket in raw_buckets:
                if not isinstance(bucket, dict):
                    continue
                errors.append({
                    "endpoint": bucket.get("endpoint", ""),
                    "type": bucket.get("type", ""),
                    "message": bucket.get("message", ""),
                    "count": bucket.get("count", 1)
                })
        elif isinstance(raw_buckets, dict):
            for bucket_name, bucket in raw_buckets.items():
                if isinstance(bucket, dict):
                    errors.append({
                        "endpoint": bucket.get("endpoint", ""),
                        "type": bucket.get("type", bucket_name),
                        "message": bucket.get("message", ""),
                        "count": bucket.get("count", 1)
                    })
                else:
                    errors.append({
                        "endpoint": "",
                        "type": str(bucket_name),
                        "message": "",
                        "count": 1
                    })
        return errors
    except Exception as e:
        print(f"Error parsing error buckets: {e}")
        return []


def calculate_improvement(baseline: Dict, enhanced: Dict) -> Dict:
    """计算 LLM 增强带来的提升百分比，分别统计 test/fuzz/error buckets"""

    def pct_change(base_val, new_val):
        """计算百分比变化"""
        # 处理 None
        base_val = base_val or 0
        new_val = new_val or 0
        
        if base_val == 0 and new_val > 0:
            return 100.0
        if base_val > 0:
            return ((new_val - base_val) / base_val) * 100
        return 0.0

    def abs_change(base_val, new_val):
        """计算绝对变化"""
        base_val = base_val or 0
        new_val = new_val or 0
        return new_val - base_val

    baseline_test = baseline.get("test_metrics", {})
    enhanced_test = enhanced.get("test_metrics", {})
    baseline_fuzz = baseline.get("fuzz_metrics", {})
    enhanced_fuzz = enhanced.get("fuzz_metrics", {})

    return {
        "test": {
            "pass_rate": pct_change(baseline_test.get("pass_rate", 0), enhanced_test.get("pass_rate", 0)),
            "coverage": pct_change(baseline_test.get("coverage", 0), enhanced_test.get("coverage", 0)),
            "bugs_found_pct": pct_change(baseline_test.get("bugs_found", 0), enhanced_test.get("bugs_found", 0)),
            "bugs_found_abs": abs_change(baseline_test.get("bugs_found", 0), enhanced_test.get("bugs_found", 0)),
        },
        "fuzz": {
            "pass_rate": pct_change(baseline_fuzz.get("pass_rate", 0), enhanced_fuzz.get("pass_rate", 0)),
            "coverage": pct_change(baseline_fuzz.get("coverage", 0), enhanced_fuzz.get("coverage", 0)),
            "bugs_found_pct": pct_change(baseline_fuzz.get("bugs_found", 0), enhanced_fuzz.get("bugs_found", 0)),
            "bugs_found_abs": abs_change(baseline_fuzz.get("bugs_found", 0), enhanced_fuzz.get("bugs_found", 0)),
        },
        "error_buckets": {
            "baseline_count": len(baseline.get("errors", []) or []),
            "enhanced_count": len(enhanced.get("errors", []) or []),
            "change_abs": len(enhanced.get("errors", []) or []) - len(baseline.get("errors", []) or []),
            "change_pct": pct_change(
                len(baseline.get("errors", []) or []), 
                len(enhanced.get("errors", []) or [])
            ),
        }
    }