import uuid
import json
from datetime import datetime
from database.models import get_session, TestRun, TestMetric, ErrorBucket, LLMGeneration

def create_run_id():
    return f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

def save_test_run(run_id, is_llm_enhanced, api_spec_name, openapi_content=None):
    session = get_session()
    try:
        test_run = TestRun(
            run_id=run_id,
            is_llm_enhanced=is_llm_enhanced,
            api_spec_name=api_spec_name,
            restler_version="9.0",
            openapi_content=openapi_content
        )
        session.add(test_run)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"Error saving test run: {e}")
        return False
    finally:
        session.close()

def save_test_metric(run_id, metrics):
    session = get_session()
    try:
        metric = TestMetric(
            run_id=run_id,
            total_requests=metrics.get("total_requests", 0),
            passed=metrics.get("passed", 0),
            failed=metrics.get("failed", 0),
            pass_rate=metrics.get("pass_rate", 0.0),
            coverage=metrics.get("coverage", 0.0),
            bugs_found=metrics.get("bugs_found", 0)
        )
        session.add(metric)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"Error saving metric: {e}")
        return False
    finally:
        session.close()

def save_error_buckets(run_id, errors):
    session = get_session()
    try:
        for error in errors:
            bucket = ErrorBucket(
                run_id=run_id,
                api_endpoint=error.get("endpoint", ""),
                error_type=error.get("type", ""),
                error_message=error.get("message", ""),
                occurrence_count=error.get("count", 1)
            )
            session.add(bucket)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"Error saving error buckets: {e}")
        return False
    finally:
        session.close()

def save_llm_generation(run_id, gen_type, content, is_effective=False):
    session = get_session()
    try:
        generation = LLMGeneration(
            run_id=run_id,
            gen_type=gen_type,
            content_snapshot=content[:1000] if content else "",
            is_effective=is_effective
        )
        session.add(generation)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        print(f"Error saving LLM generation: {e}")
        return False
    finally:
        session.close()

def get_all_runs():
    """获取所有测试记录，按时间倒序"""
    session = get_session()
    try:
        runs = session.query(TestRun).order_by(TestRun.run_time.desc()).all()
        result = []
        for run in runs:
            metric = session.query(TestMetric).filter_by(run_id=run.run_id).first()
            result.append({
                "run_id": run.run_id,
                "run_time": run.run_time,
                "is_llm_enhanced": run.is_llm_enhanced,
                "api_spec_name": run.api_spec_name,
                "pass_rate": metric.pass_rate if metric else 0,
                "coverage": metric.coverage if metric else 0,
                "bugs_found": metric.bugs_found if metric else 0
            })
        return result
    finally:
        session.close()

def get_comparison_data():
    """
    获取用于对比的数据（最近一次原生测试和 LLM 增强测试）
    返回格式:
    {
        "baseline": {"pass_rate": float, "coverage": float, "bugs_found": int, "run_id": str, "run_time": datetime},
        "enhanced": {"pass_rate": float, "coverage": float, "bugs_found": int, "run_id": str, "run_time": datetime}
    }
    """
    session = get_session()
    try:
        # 获取最新的原生测试（按 run_time 降序）
        baseline_run = session.query(TestRun).filter(
            TestRun.is_llm_enhanced == False
        ).order_by(TestRun.run_time.desc()).first()
        
        # 获取最新的 LLM 增强测试
        enhanced_run = session.query(TestRun).filter(
            TestRun.is_llm_enhanced == True
        ).order_by(TestRun.run_time.desc()).first()
        
        result = {
            "baseline": None,
            "enhanced": None
        }
        
        if baseline_run:
            metric = session.query(TestMetric).filter_by(run_id=baseline_run.run_id).first()
            if metric:
                result["baseline"] = {
                    "pass_rate": metric.pass_rate,
                    "coverage": metric.coverage,
                    "bugs_found": metric.bugs_found,
                    "run_id": baseline_run.run_id,
                    "run_time": baseline_run.run_time
                }
        
        if enhanced_run:
            metric = session.query(TestMetric).filter_by(run_id=enhanced_run.run_id).first()
            if metric:
                result["enhanced"] = {
                    "pass_rate": metric.pass_rate,
                    "coverage": metric.coverage,
                    "bugs_found": metric.bugs_found,
                    "run_id": enhanced_run.run_id,
                    "run_time": enhanced_run.run_time
                }
        
        return result
    finally:
        session.close()

def get_run_detail(run_id: str):
    """获取单个测试运行的详细信息"""
    session = get_session()
    try:
        test_run = session.query(TestRun).filter_by(run_id=run_id).first()
        if not test_run:
            return None
        
        metric = session.query(TestMetric).filter_by(run_id=run_id).first()
        errors = session.query(ErrorBucket).filter_by(run_id=run_id).all()
        generations = session.query(LLMGeneration).filter_by(run_id=run_id).all()
        
        return {
            "run": {
                "run_id": test_run.run_id,
                "run_time": test_run.run_time,
                "is_llm_enhanced": test_run.is_llm_enhanced,
                "api_spec_name": test_run.api_spec_name,
                "restler_version": test_run.restler_version
            },
            "metrics": {
                "total_requests": metric.total_requests if metric else 0,
                "passed": metric.passed if metric else 0,
                "failed": metric.failed if metric else 0,
                "pass_rate": metric.pass_rate if metric else 0,
                "coverage": metric.coverage if metric else 0,
                "bugs_found": metric.bugs_found if metric else 0
            } if metric else None,
            "errors": [{"endpoint": e.api_endpoint, "type": e.error_type, "message": e.error_message} for e in errors],
            "generations": [{"type": g.gen_type, "content": g.content_snapshot, "effective": g.is_effective} for g in generations]
        }
    finally:
        session.close()