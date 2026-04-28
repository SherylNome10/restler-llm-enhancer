import os
import json

from config.settings import RESTLER_RESULTS_DIR, LLM_GENERATED_DIR
from database.db_utils import (
    create_run_id, save_test_run, save_test_metric, 
    save_error_buckets, save_llm_generation
)
from restler_engine.restler_wrapper import restler_wrapper
from llm_enhancer.dependency_gen import generate_annotations_json
from llm_enhancer.dict_filler import generate_dict_json
from llm_enhancer.example_gen import generate_examples_json
from llm_enhancer.feedback_loop import generate_fixed_requests_json
from compare.metrics_compare import parse_testing_summary, parse_error_buckets, calculate_improvement

class TestRunner:
    def __init__(self):
        self.results = {}

    def _write_examples_verification(self, output_dir: str, run_type: str, compile_result: dict | None, test_result: dict | None):
        verification = {
            "run_type": run_type,
            "compile": {
                "config_used": (compile_result or {}).get("examples_status", {}).get("config_used", False),
                "config_attempted": (compile_result or {}).get("examples_status", {}).get("config_attempted", False),
                "config_fallback": (compile_result or {}).get("examples_status", {}).get("config_fallback", False),
            },
            "test": {
                "via_settings": (test_result or {}).get("examples_status", {}).get("via_settings", False),
            },
            "examples_path": (
                (compile_result or {}).get("examples_status", {}).get("path")
                or (test_result or {}).get("examples_status", {}).get("path")
            )
        }
        verification_path = os.path.join(output_dir, "examples_verification.json")
        with open(verification_path, "w", encoding="utf-8") as f:
            json.dump(verification, f, indent=2, ensure_ascii=False)
        print(f"Examples verification saved to: {verification_path}")
        return verification_path
    
    def run_baseline(self, openapi_file: str, api_spec_name: str) -> dict:
        """运行原生 RESTler（无 LLM 增强）"""
        run_id = create_run_id()
        print(f"\n{'='*50}")
        print(f"Running BASELINE test: {run_id}")
        print(f"{'='*50}")
        
        # 加载 OpenAPI 规范
        with open(openapi_file, 'r') as f:
            openapi_spec = json.load(f)
        
        save_test_run(run_id, False, api_spec_name, json.dumps(openapi_spec))
        
        # 创建输出目录
        output_dir = os.path.join(RESTLER_RESULTS_DIR, run_id)
        os.makedirs(output_dir, exist_ok=True)
        
        # 编译阶段
        compile_result = restler_wrapper.compile(openapi_file, output_dir)
        if not compile_result["success"] or not compile_result["grammar_file"]:
            print("Compile failed.")
            if compile_result.get("compile_dir"):
                print(f"Compile dir: {compile_result['compile_dir']}")
                print(f"Stdout log: {os.path.join(compile_result['compile_dir'], 'compile.stdout.log')}")
                print(f"Stderr log: {os.path.join(compile_result['compile_dir'], 'compile.stderr.log')}")
                print(f"Generate_config stdout log: {os.path.join(compile_result['compile_dir'], 'generate_config.stdout.log')}")
                print(f"Generate_config stderr log: {os.path.join(compile_result['compile_dir'], 'generate_config.stderr.log')}")
            if compile_result.get("stderr"):
                print(f"Error: {compile_result['stderr']}")
            return {"run_id": run_id, "success": False}
        
        # 测试阶段
        test_result = restler_wrapper.test(
            compile_result["grammar_file"],
            output_dir,
            compile_result.get("dictionary_file")
        )

        fuzz_result = restler_wrapper.fuzz(
            compile_result["grammar_file"],
            output_dir,
            dictionary_file=compile_result.get("dictionary_file"),
        )

        test_metrics = parse_testing_summary(test_result.get("summary_file") or test_result.get("test_dir") or "")
        fuzz_metrics = parse_testing_summary(fuzz_result.get("summary_file") or fuzz_result.get("fuzz_dir") or "")
        errors = parse_error_buckets(fuzz_result.get("error_buckets_file") or fuzz_result.get("fuzz_dir") or "")

        verification_file = self._write_examples_verification(
            output_dir,
            "baseline",
            compile_result,
            test_result
        )

        save_test_metric(run_id, fuzz_metrics)
        if errors:
            save_error_buckets(run_id, errors)

        return {
            "run_id": run_id,
            "success": True,
            "test_metrics": test_metrics,
            "fuzz_metrics": fuzz_metrics,
            "errors": errors,
            "output_dir": output_dir,
            "examples_verification_file": verification_file,
            "compile_result": compile_result,
            "test_result": test_result,
            "fuzz_result": fuzz_result
        }
    
    def run_llm_enhanced(self, openapi_file: str, api_spec_name: str, 
                          enable_feedback_loop: bool = True) -> dict:
        """运行 LLM 增强版 RESTler"""
        run_id = create_run_id()
        print(f"\n{'='*50}")
        print(f"Running LLM-ENHANCED test: {run_id}")
        print(f"{'='*50}")
        
        # 加载 OpenAPI 规范
        with open(openapi_file, 'r') as f:
            openapi_spec = json.load(f)
        
        save_test_run(run_id, True, api_spec_name, json.dumps(openapi_spec))
        
        # 创建输出目录
        output_dir = os.path.join(RESTLER_RESULTS_DIR, run_id)
        llm_gen_dir = os.path.join(LLM_GENERATED_DIR, run_id)
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(llm_gen_dir, exist_ok=True)
        
        # 1. 生成 annotations.json
        print("Generating annotations.json with LLM...")
        annotations_file = os.path.join(llm_gen_dir, "annotations.json")
        generate_annotations_json(openapi_spec, annotations_file)
        save_llm_generation(run_id, "dependency", annotations_file)
        
        # 2. 生成 dict.json
        print("Generating dict.json with LLM...")
        dict_file = os.path.join(llm_gen_dir, "dict.json")
        generate_dict_json(openapi_spec, dict_file)
        save_llm_generation(run_id, "dict", dict_file)
        
        # 3. 生成 examples.json
        print("Generating examples.json with LLM...")
        examples_file = os.path.join(llm_gen_dir, "examples.json")
        generate_examples_json(openapi_spec, examples_file)
        save_llm_generation(run_id, "example", examples_file)
        
        # 编译阶段（使用 LLM 生成的文件）
        custom_config = {
            "annotations": annotations_file,
            "dict": dict_file,
            "examples": examples_file
        }
        compile_result = restler_wrapper.compile(openapi_file, output_dir, custom_config)
        if not compile_result["success"] or not compile_result["grammar_file"]:
            print("Compile failed.")
            if compile_result.get("compile_dir"):
                print(f"Compile dir: {compile_result['compile_dir']}")
                print(f"Stdout log: {os.path.join(compile_result['compile_dir'], 'compile.stdout.log')}")
                print(f"Stderr log: {os.path.join(compile_result['compile_dir'], 'compile.stderr.log')}")
                print(f"Generate_config stdout log: {os.path.join(compile_result['compile_dir'], 'generate_config.stdout.log')}")
                print(f"Generate_config stderr log: {os.path.join(compile_result['compile_dir'], 'generate_config.stderr.log')}")
            if compile_result.get("stderr"):
                print(f"Error: {compile_result['stderr']}")
            return {"run_id": run_id, "success": False}
        
        test_result = restler_wrapper.test(
            compile_result["grammar_file"],
            output_dir,
            compile_result.get("dictionary_file"),
            compile_result.get("examples_file") or examples_file
        )

        fuzz_result = restler_wrapper.fuzz(
            compile_result["grammar_file"],
            output_dir,
            dictionary_file=compile_result.get("dictionary_file"),
        )

        test_metrics = parse_testing_summary(test_result.get("summary_file") or test_result.get("test_dir") or "")
        fuzz_metrics = parse_testing_summary(fuzz_result.get("summary_file") or fuzz_result.get("fuzz_dir") or "")
        errors = parse_error_buckets(fuzz_result.get("error_buckets_file") or fuzz_result.get("fuzz_dir") or "")

        print("EXAMPLES VERIFICATION")
        print(f"  compile.config_used: {compile_result.get('examples_status', {}).get('config_used')}")
        print(f"  test.via_settings: {test_result.get('examples_status', {}).get('via_settings')}")
        print(f"  examples.path: {compile_result.get('examples_status', {}).get('path') or test_result.get('examples_status', {}).get('path')}")

        verification_file = self._write_examples_verification(
            output_dir,
            "enhanced",
            compile_result,
            test_result
        )

        if enable_feedback_loop and errors:
            print("Running feedback loop with LLM...")
            fixed_file = os.path.join(llm_gen_dir, "fixed_requests.json")
            generate_fixed_requests_json(errors, openapi_spec, fixed_file)
            save_llm_generation(run_id, "feedback_fixed", fixed_file)

        save_test_metric(run_id, fuzz_metrics)
        if errors:
            save_error_buckets(run_id, errors)

        return {
            "run_id": run_id,
            "success": True,
            "test_metrics": test_metrics,
            "fuzz_metrics": fuzz_metrics,
            "errors": errors,
            "output_dir": output_dir,
            "llm_gen_dir": llm_gen_dir,
            "examples_verification_file": verification_file,
            "compile_result": compile_result,
            "test_result": test_result,
            "fuzz_result": fuzz_result
        }
    
    def run_comparison(self, openapi_file: str, api_spec_name: str):
        """运行对比测试（基线 + 增强）"""
        print("\n" + "="*60)
        print("STARTING COMPARISON TEST")
        print("="*60)
        
        # 运行基线测试
        baseline_result = self.run_baseline(openapi_file, api_spec_name)
        
        # 运行增强测试
        enhanced_result = self.run_llm_enhanced(openapi_file, api_spec_name)
        
        # 计算提升
        if baseline_result.get("success") and enhanced_result.get("success"):
            improvement = calculate_improvement(
                baseline_result,
                enhanced_result
            )
            print("\n" + "="*60)
            print("IMPROVEMENT SUMMARY")
            print("="*60)
            print(f"BASELINE compile/test/fuzz: {baseline_result.get('compile_result', {}).get('success')} / {baseline_result.get('test_result', {}).get('success')} / {baseline_result.get('fuzz_result', {}).get('success')}")
            print(f"ENHANCED compile/test/fuzz: {enhanced_result.get('compile_result', {}).get('success')} / {enhanced_result.get('test_result', {}).get('success')} / {enhanced_result.get('fuzz_result', {}).get('success')}")
            print(f"ENHANCED examples compile.config_used: {enhanced_result.get('compile_result', {}).get('examples_status', {}).get('config_used')}")
            print(f"ENHANCED examples test.via_settings: {enhanced_result.get('test_result', {}).get('examples_status', {}).get('via_settings')}")
            print(f"ENHANCED examples path: {enhanced_result.get('compile_result', {}).get('examples_status', {}).get('path') or enhanced_result.get('test_result', {}).get('examples_status', {}).get('path')}")
            print(f"ENHANCED examples verification file: {enhanced_result.get('examples_verification_file')}")
            print(f"TEST Pass Rate Improvement: {improvement.get('test', {}).get('pass_rate', 0):.2f}%")
            print(f"TEST Coverage Improvement: {improvement.get('test', {}).get('coverage', 0):.2f}%")
            print(f"FUZZ Pass Rate Improvement: {improvement.get('fuzz', {}).get('pass_rate', 0):.2f}%")
            print(f"FUZZ Coverage Improvement: {improvement.get('fuzz', {}).get('coverage', 0):.2f}%")
            print(f"FUZZ Bugs Found Improvement: {improvement.get('fuzz', {}).get('bugs_found', 0):.2f}%")
            print(
                f"Error Buckets: {improvement.get('error_buckets', {}).get('baseline_count', 0)} -> "
                f"{improvement.get('error_buckets', {}).get('enhanced_count', 0)}"
            )
            
            return {
                "baseline": baseline_result,
                "enhanced": enhanced_result,
                "improvement": improvement
            }
        
        return {
            "baseline": baseline_result,
            "enhanced": enhanced_result,
            "improvement": None
        }

def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="RESTler LLM Enhancer")
    parser.add_argument("--openapi", required=True, help="Path to OpenAPI spec file")
    parser.add_argument("--name", default="api", help="API spec name")
    parser.add_argument("--mode", choices=["baseline", "enhanced", "compare"], 
                        default="compare", help="Test mode")
    parser.add_argument("--no-feedback", action="store_true", 
                        help="Disable feedback loop")
    
    args = parser.parse_args()
    
    runner = TestRunner()
    
    if args.mode == "baseline":
        result = runner.run_baseline(args.openapi, args.name)
        print(f"\nResult: {result}")
    elif args.mode == "enhanced":
        result = runner.run_llm_enhanced(args.openapi, args.name, 
                                         enable_feedback_loop=not args.no_feedback)
        print(f"\nResult: {result}")
    else:  # compare
        result = runner.run_comparison(args.openapi, args.name)
        print(f"\nComparison result saved to database")

if __name__ == "__main__":
    main()
