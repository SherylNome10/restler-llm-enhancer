import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import json
import os
from datetime import datetime

from database.db_utils import get_all_runs, get_comparison_data, get_run_detail
from runner import TestRunner
from config.settings import OPENAPI_SPECS_DIR

# 页面配置
st.set_page_config(
    page_title="RESTler LLM Enhancer - 智能测试对比平台",
    page_icon="",
    layout="wide"
)

st.title("RESTler LLM 智能增强测试平台")
st.markdown("**对比原生 RESTler 与 LLM 增强版的测试效果**")
st.markdown("---")

# 初始化 session state
if 'comparison_result' not in st.session_state:
    st.session_state['comparison_result'] = None

# ==================== 运行测试区域 ====================
st.header("运行对比测试")

# 选择 API 规范
spec_files = []
if os.path.exists(OPENAPI_SPECS_DIR):
    spec_files = [f for f in os.listdir(OPENAPI_SPECS_DIR) if f.endswith(('.json', '.yaml', '.yml'))]

if not spec_files:
    st.warning("请将 OpenAPI 规范文件放入 `data/openapi_specs/` 目录")
    st.stop()

col1, col2 = st.columns([3, 1])
with col1:
    selected_spec = st.selectbox("选择 OpenAPI 规范", spec_files, label_visibility="collapsed")
with col2:
    run_button = st.button("开始对比测试", type="primary", use_container_width=True)

if run_button:
    with st.spinner("正在运行对比测试，请稍候（可能需要几分钟）..."):
        runner = TestRunner()
        openapi_path = os.path.join(OPENAPI_SPECS_DIR, selected_spec)
        result = runner.run_comparison(openapi_path, selected_spec)
        st.session_state['comparison_result'] = result
        
        if result and result.get('improvement'):
            st.success("对比测试完成！")
        else:
            st.error("测试失败，请检查日志")
        st.rerun()

st.markdown("---")

# ==================== 对比结果展示 ====================
st.header("对比结果")

comparison = get_comparison_data()
baseline = comparison.get("baseline")
enhanced = comparison.get("enhanced")

if baseline and enhanced:
    # 计算提升
    pass_improve = ((enhanced['pass_rate'] - baseline['pass_rate']) / baseline['pass_rate'] * 100) if baseline['pass_rate'] > 0 else 0
    cov_improve = ((enhanced['coverage'] - baseline['coverage']) / baseline['coverage'] * 100) if baseline['coverage'] > 0 else 0
    delta_bugs = enhanced['bugs_found'] - baseline['bugs_found']
    
    # 三个核心指标卡片
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # 通过率说明
        st.caption("**请求通过率**")
        st.caption("*成功执行的请求占总请求的百分比*")
        
        # 显示对比
        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("原生 RESTler", f"{baseline['pass_rate']:.1f}%", delta=None)
        with col_b:
            st.metric("LLM 增强版", f"{enhanced['pass_rate']:.1f}%", 
                     delta=f"{pass_improve:+.1f}%", delta_color="normal")
    
    with col2:
        # 覆盖率说明
        st.caption("**API 覆盖率**")
        st.caption("*成功覆盖的 API 端点占总端点的百分比*")
        
        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("原生 RESTler", f"{baseline['coverage']:.1f}%", delta=None)
        with col_b:
            st.metric("LLM 增强版", f"{enhanced['coverage']:.1f}%", 
                     delta=f"{cov_improve:+.1f}%", delta_color="normal")
    
    with col3:
        # Bug发现数说明
        st.caption("**Bug 发现数**")
        st.caption("*测试过程中发现的潜在缺陷数量*")
        
        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("原生 RESTler", f"{baseline['bugs_found']}", delta=None)
        with col_b:
            st.metric("LLM 增强版", f"{enhanced['bugs_found']}", 
                     delta=f"{delta_bugs:+d}", delta_color="inverse")
    
    # 可视化对比 - 柱状图
    st.subheader("可视化对比")
    
    # 准备数据
    metrics = ['通过率 (%)', '覆盖率 (%)', 'Bug发现数']
    baseline_values = [baseline['pass_rate'], baseline['coverage'], baseline['bugs_found']]
    enhanced_values = [enhanced['pass_rate'], enhanced['coverage'], enhanced['bugs_found']]
    
    # 归一化 Bug 数量（用于显示）
    max_bugs = max(baseline['bugs_found'], enhanced['bugs_found'], 1)
    baseline_bugs_norm = baseline['bugs_found'] / max_bugs * 100
    enhanced_bugs_norm = enhanced['bugs_found'] / max_bugs * 100
    
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        name='原生 RESTler',
        x=metrics,
        y=[baseline['pass_rate'], baseline['coverage'], baseline_bugs_norm],
        text=[f"{baseline['pass_rate']:.1f}%", f"{baseline['coverage']:.1f}%", f"{baseline['bugs_found']}"],
        textposition='auto',
        marker_color='#2E86AB'
    ))
    
    fig.add_trace(go.Bar(
        name='LLM 增强版',
        x=metrics,
        y=[enhanced['pass_rate'], enhanced['coverage'], enhanced_bugs_norm],
        text=[f"{enhanced['pass_rate']:.1f}%", f"{enhanced['coverage']:.1f}%", f"{enhanced['bugs_found']}"],
        textposition='auto',
        marker_color='#A23B72'
    ))
    
    fig.update_layout(
        title="原生 RESTler vs LLM 增强版 性能对比",
        xaxis_title="指标",
        yaxis_title="数值 (%)",
        yaxis=dict(range=[0, 100]),
        legend=dict(x=0.02, y=0.98),
        height=450,
        barmode='group'
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # 详细数据表
    st.subheader("详细数据")
    
    table_data = {
        "指标": ["请求通过率", "API覆盖率", "Bug发现数"],
        "原生 RESTler": [
            f"{baseline['pass_rate']:.1f}%", 
            f"{baseline['coverage']:.1f}%", 
            str(baseline['bugs_found'])
        ],
        "LLM 增强版": [
            f"{enhanced['pass_rate']:.1f}%", 
            f"{enhanced['coverage']:.1f}%", 
            str(enhanced['bugs_found'])
        ],
        "提升": [
            f"{pass_improve:+.1f}%", 
            f"{cov_improve:+.1f}%", 
            f"{delta_bugs:+d}"
        ]
    }
    
    df_comparison = pd.DataFrame(table_data)
    st.dataframe(df_comparison, use_container_width=True, hide_index=True)
    
    # 测试时间信息
    st.caption(f"原生测试时间: {baseline.get('run_time', 'N/A')}")
    st.caption(f"LLM增强测试时间: {enhanced.get('run_time', 'N/A')}")
    
elif baseline and not enhanced:
    st.info("已有原生测试数据，请点击上方按钮运行 LLM 增强对比测试")
elif not baseline and enhanced:
    st.info("已有 LLM 增强测试数据，请点击上方按钮运行原生测试以进行对比")
else:
    st.info("请选择 OpenAPI 规范并点击「开始对比测试」按钮")

# ==================== 说明区域 ====================
st.markdown("---")
st.caption("""
**指标说明：**
- **请求通过率**：成功执行的请求比例，越高表示生成的测试用例质量越好
- **API 覆盖率**：成功触及的 API 端点比例，越高表示测试更全面
- **Bug 发现数**：测试过程中发现的潜在缺陷数量，越多表示问题发现能力越强
""")