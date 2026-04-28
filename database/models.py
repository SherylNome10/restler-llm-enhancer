from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import json

from config.settings import DATABASE_PATH

Base = declarative_base()

class TestRun(Base):
    __tablename__ = "test_run"
    
    id = Column(Integer, primary_key=True)
    run_id = Column(String(64), unique=True, nullable=False)
    run_time = Column(DateTime, default=datetime.now)
    is_llm_enhanced = Column(Boolean, default=False)
    api_spec_name = Column(String(256))
    restler_version = Column(String(64))
    openapi_content = Column(Text)  # 存储 JSON 字符串

class TestMetric(Base):
    __tablename__ = "test_metric"
    
    id = Column(Integer, primary_key=True)
    run_id = Column(String(64), nullable=False)
    total_requests = Column(Integer, default=0)
    passed = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    pass_rate = Column(Float, default=0.0)
    coverage = Column(Float, default=0.0)
    bugs_found = Column(Integer, default=0)

class ErrorBucket(Base):
    __tablename__ = "error_bucket"
    
    id = Column(Integer, primary_key=True)
    run_id = Column(String(64), nullable=False)
    api_endpoint = Column(String(512))
    error_type = Column(String(256))
    error_message = Column(Text)
    occurrence_count = Column(Integer, default=1)

class LLMGeneration(Base):
    __tablename__ = "llm_generation"
    
    id = Column(Integer, primary_key=True)
    run_id = Column(String(64), nullable=False)
    gen_type = Column(String(32))  # dependency/dict/example
    content_snapshot = Column(Text)
    is_effective = Column(Boolean, default=False)

# 初始化数据库
def init_db():
    engine = create_engine(f"sqlite:///{DATABASE_PATH}", echo=False)
    Base.metadata.create_all(engine)
    return engine

def get_session():
    engine = create_engine(f"sqlite:///{DATABASE_PATH}", echo=False)
    Session = sessionmaker(bind=engine)
    return Session()
