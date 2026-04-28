import subprocess
import os
import json
import shutil
from pathlib import Path
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import RESTLER_PATH, RESTLER_RESULTS_DIR

class RESTlerWrapper:
    def __init__(self):
        possible_paths = [
            "/opt/restler/restler/Restler.dll",
            "/opt/test/test_code/restler-llm-enhancer/data/restler/Restler.dll",
            RESTLER_PATH if RESTLER_PATH and RESTLER_PATH.endswith('.dll') else None
        ]
        
        self.restler_dll = None
        for path in possible_paths:
            if path and os.path.exists(path):
                self.restler_dll = path
                break
        
        if not self.restler_dll:
            for root, dirs, files in os.walk("/opt"):
                if "Restler.dll" in files:
                    self.restler_dll = os.path.join(root, "Restler.dll")
                    break
        
        print(f"Using RESTler DLL: {self.restler_dll}")
        self.results_dir = RESTLER_RESULTS_DIR
        
        # 添加目标服务器配置
        self.target_ip = "172.31.7.190"
        self.target_port = "8889"
    
    def _run_restler(
        self,
        args,
        log_dir: str | None = None,
        log_prefix: str | None = None,
        cwd: str | None = None,
    ):
        if not self.restler_dll or not os.path.exists(self.restler_dll):
            print(f"ERROR: Restler.dll not found")
            return None
        
        cmd = ["dotnet", self.restler_dll] + args
        print(f"Running: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3000,
                cwd=cwd,
            )
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
                safe_prefix = log_prefix or args[0] if args else "restler"
                stdout_path = os.path.join(log_dir, f"{safe_prefix}.stdout.log")
                stderr_path = os.path.join(log_dir, f"{safe_prefix}.stderr.log")
                try:
                    with open(stdout_path, "w", encoding="utf-8", errors="replace") as f:
                        f.write(result.stdout or "")
                    with open(stderr_path, "w", encoding="utf-8", errors="replace") as f:
                        f.write(result.stderr or "")
                except Exception as e:
                    print(f"WARNING: failed writing logs: {e}")

                print(f"RESTler stdout log: {stdout_path}")
                print(f"RESTler stderr log: {stderr_path}")

            if result.returncode != 0:
                print(f"RESTler return code: {result.returncode}")
            if result.stdout:
                print(f"Stdout (first 500 chars): {result.stdout[:500]}")
            if result.stderr:
                print(f"Stderr (first 500 chars): {result.stderr[:500]}")
            return result
        except Exception as e:
            print(f"Command error: {e}")
            return None
    
    def compile(self, openapi_file: str, output_dir: str, custom_config: dict = None):
        compile_dir = os.path.join(output_dir, "compile")
        os.makedirs(compile_dir, exist_ok=True)

        generate_args = [
            "generate_config",
            "--specs", openapi_file,
            "--output_dir", compile_dir
        ]

        print("Generating compiler config...")
        gen_result = self._run_restler(generate_args, log_dir=compile_dir, log_prefix="generate_config")

        if gen_result is None:
            return {
                "success": False,
                "stdout": "",
                "stderr": "Failed to generate config",
                "compile_dir": compile_dir,
                "grammar_file": None,
                "dictionary_file": None,
                "config_file": None
            }

        config_file = os.path.join(compile_dir, "config.json")
        if not os.path.exists(config_file):
            return {
                "success": False,
                "stdout": gen_result.stdout,
                "stderr": f"Config file not found at {config_file}",
                "compile_dir": compile_dir,
                "grammar_file": None,
                "dictionary_file": None,
                "config_file": None
            }

        with open(config_file, 'r') as f:
            compiler_config = json.load(f)

        compile_examples_requested = bool(custom_config and custom_config.get("examples"))
        compile_examples_path = custom_config.get("examples") if custom_config else None
        compile_examples_config_attempted = False
        compile_examples_config_used = False
        compile_examples_config_fallback = False

        if custom_config:
            if custom_config.get("dict"):
                dict_dest = os.path.join(compile_dir, "dict.json")
                shutil.copy(custom_config["dict"], dict_dest)
                compiler_config["CustomDictionaryFilePath"] = "dict.json"
                print(f"Using custom dictionary: {custom_config['dict']}")

            if custom_config.get("annotations"):
                anno_dest = os.path.join(compile_dir, "annotations.json")
                shutil.copy(custom_config["annotations"], anno_dest)
                compiler_config["AnnotationFilePath"] = "annotations.json"
                print(f"Using custom annotations: {custom_config['annotations']}")

            if custom_config.get("examples"):
                examples_dest = os.path.join(compile_dir, "examples.json")
                shutil.copy(custom_config["examples"], examples_dest)
                compiler_config["ExampleConfigFilePath"] = "examples.json"
                compile_examples_config_attempted = True
                print(f"Using custom examples: {custom_config['examples']}")

        with open(config_file, 'w') as f:
            json.dump(compiler_config, f, indent=2)

        print(f"Config saved to {config_file}")

        config_file_abs = os.path.abspath(config_file)
        cmd_args = ["compile", config_file_abs]
        result = self._run_restler(cmd_args, log_dir=compile_dir, log_prefix="compile", cwd=compile_dir)

        if result is not None:
            compile_output = (result.stdout or "") + (result.stderr or "")
            invalid_examples_field = (
                custom_config
                and custom_config.get("examples")
                and result.returncode != 0
                and (
                    "ExampleConfigFilePath" in compile_output
                    or "ExamplesFilePath" in compile_output
                    or "Could not find member 'ExampleConfigFilePath'" in compile_output
                    or "Could not find member 'ExamplesFilePath'" in compile_output
                )
            )
            if invalid_examples_field:
                print("Compiler does not support examples field in config; retrying compile without examples config field.")
                compile_examples_config_fallback = True
                with open(config_file, 'r') as f:
                    compiler_config_retry = json.load(f)
                compiler_config_retry.pop("ExampleConfigFilePath", None)
                compiler_config_retry.pop("ExamplesFilePath", None)
                with open(config_file, 'w') as f:
                    json.dump(compiler_config_retry, f, indent=2)
                result = self._run_restler(cmd_args, log_dir=compile_dir, log_prefix="compile_retry", cwd=compile_dir)

        if result is None:
            return {
                "success": False,
                "stdout": "",
                "stderr": "Failed to run compile",
                "compile_dir": compile_dir,
                "grammar_file": None,
                "dictionary_file": None,
                "config_file": config_file
            }

        output = result.stdout + result.stderr
        compile_success = "Task Compile succeeded" in output
        if compile_examples_config_attempted and compile_success and not compile_examples_config_fallback:
            compile_examples_config_used = True

        grammar_file = None
        for file in Path(compile_dir).rglob("grammar.py"):
            grammar_file = str(file)
            break

        dictionary_file = None
        for file in Path(compile_dir).rglob("dict.json"):
            dictionary_file = str(file)
            break

        examples_file = None
        for file in Path(compile_dir).rglob("examples.json"):
            examples_file = str(file)
            break

        print("EXAMPLES USAGE [compile]")
        print(f"  requested: {compile_examples_requested}")
        print(f"  path: {compile_examples_path}")
        print(f"  config_attempted: {compile_examples_config_attempted}")
        print(f"  config_used: {compile_examples_config_used}")
        print(f"  config_fallback: {compile_examples_config_fallback}")

        return {
            "success": compile_success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "compile_dir": compile_dir,
            "grammar_file": grammar_file,
            "dictionary_file": dictionary_file,
            "examples_file": examples_file,
            "config_file": config_file,
            "examples_status": {
                "requested": compile_examples_requested,
                "path": compile_examples_path,
                "config_attempted": compile_examples_config_attempted,
                "config_used": compile_examples_config_used,
                "config_fallback": compile_examples_config_fallback
            }
        }
    
    def test(self, grammar_file: str, output_dir: str, dictionary_file: str | None = None, examples_file: str = None):
        test_dir = os.path.join(output_dir, "test")
        os.makedirs(test_dir, exist_ok=True)

        cmd_args = [
            "--workingDirPath", test_dir,
            "test",
            "--grammar_file", grammar_file,
            "--target_ip", self.target_ip,
            "--target_port", self.target_port,
        ]

        if dictionary_file and os.path.exists(dictionary_file):
            cmd_args.extend(["--dictionary_file", dictionary_file])
            print(f"Using dictionary: {dictionary_file}")

        test_examples_requested = bool(examples_file and os.path.exists(examples_file))
        settings_path = self._create_settings_file(test_dir, examples_file=examples_file)
        test_examples_via_settings = False
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r') as f:
                    settings_data = json.load(f)
                test_examples_via_settings = bool(settings_data.get("example_config_file"))
            except Exception:
                test_examples_via_settings = False
        print("EXAMPLES USAGE [test]")
        print(f"  requested: {test_examples_requested}")
        print(f"  path: {examples_file}")
        print(f"  via_settings: {test_examples_via_settings}")
        cmd_args.extend([
            "--settings", settings_path,
        ])

        cmd_args.append("--no_ssl")

        result = self._run_restler(cmd_args, log_dir=test_dir, log_prefix="test")

        if result is None:
            return {
                "success": False,
                "stdout": "",
                "stderr": "Failed to run test",
                "test_dir": test_dir,
                "summary_file": None
            }

        output = result.stdout + result.stderr
        test_success = "Task Test succeeded" in output or result.returncode == 0

        summary_file = None
        for file in Path(test_dir).rglob("testing_summary.json"):
            summary_file = str(file)
            break

        return {
            "success": test_success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "test_dir": test_dir,
            "settings_file": settings_path,
            "summary_file": summary_file,
            "examples_status": {
                "requested": test_examples_requested,
                "path": examples_file,
                "via_settings": test_examples_via_settings
            }
        }
    
    def fuzz(self, grammar_file: str, output_dir: str, dictionary_file: str | None = None):
        fuzz_dir = os.path.join(output_dir, "fuzz")
        os.makedirs(fuzz_dir, exist_ok=True)

        cmd_args = [
            "--workingDirPath", fuzz_dir,
            "fuzz-lean",
            "--grammar_file", grammar_file,
            "--target_ip", self.target_ip,
            "--target_port", self.target_port,
        ]

        if dictionary_file and os.path.exists(dictionary_file):
            cmd_args.extend(["--dictionary_file", dictionary_file])
            print(f"Using dictionary for fuzz: {dictionary_file}")

        cmd_args.extend([
            "--settings", self._create_settings_file(fuzz_dir),
        ])

        cmd_args.append("--no_ssl")

        result = self._run_restler(cmd_args, log_dir=fuzz_dir, log_prefix="fuzz")

        if result is None:
            return {
                "success": False,
                "stdout": "",
                "stderr": "Failed to run fuzz",
                "fuzz_dir": fuzz_dir,
                "summary_file": None,
                "error_buckets_file": None
            }

        output = result.stdout + result.stderr
        fuzz_success = "Task FuzzLean succeeded" in output or result.returncode == 0

        summary_file = None
        error_buckets_file = None
        for file in Path(fuzz_dir).rglob("testing_summary.json"):
            summary_file = str(file)
            break
        for file in Path(fuzz_dir).rglob("errorBuckets.json"):
            error_buckets_file = str(file)
            break

        return {
            "success": fuzz_success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "fuzz_dir": fuzz_dir,
            "summary_file": summary_file,
            "error_buckets_file": error_buckets_file
        }
    
    def _create_settings_file(self, dir_path: str, examples_file: str | None = None) -> str:
        settings = {
            "enable_ipv6": False,
            "renew_once": True
        }
        if examples_file and os.path.exists(examples_file):
            settings["checkers"] = {
                "Examples": {
                    "mode": "exhaustive"
                }
            }
            settings["example_config_file"] = examples_file
            settings["producer_timing_delay"] = 0
        settings_path = os.path.join(dir_path, "settings.json")
        with open(settings_path, 'w') as f:
            json.dump(settings, f, indent=2)
        return settings_path

restler_wrapper = RESTlerWrapper()