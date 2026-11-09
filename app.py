"""스마트 상품 퍼블리셔 — 상단 인덱스로 이동하는 노트형 화면."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from src import service
from ui.screens import NAV_KEY, PAGES, RENDERERS

BRAND_MARK_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 54 54" role="img" aria-label="굿홈앤리빙 심벌"><defs><mask id="weave"><path fill="white" d="M4.32 21.6 27 3.78 49.68 21.6v25.92L42.12 51.84H4.32Z"/><g fill="black"><rect x="15.12" y="24.84" width="6.48" height="17.28" rx=".54"/><rect x="29.16" y="18.9" width="6.48" height="23.22" rx=".54"/><rect x="15.12" y="31.32" width="26.46" height="5.4" rx=".54"/></g></mask></defs><rect width="54" height="54" fill="#656A83" mask="url(#weave)"/></svg>"""

# 고정된 브랜드 자산과 스타일만 HTML로 표시한다.
BRAND_HEADER_HTML = (
    '<div class="gh-brand"><span class="gh-logo">'
    + BRAND_MARK_SVG
    + '</span><div class="gh-brand-name">굿홈앤리빙<small>스마트 상품 퍼블리셔</small></div></div>'
)

NOTEBOOK_CSS = """
<style>
:root { --gh-primary:#656A83; --gh-ink:#45475B; --gh-paper:#FFFEF8; --gh-muted:#626575; --gh-line:#E7E3EA; }
.stApp, .stApp button, .stApp input, .stApp textarea { font-family:"Pretendard","Malgun Gothic","Apple SD Gothic Neo",sans-serif; }
[data-testid="stHeader"] { background:transparent; }
[data-testid="stMainBlockContainer"] { max-width:1440px; padding:44px 34px 40px; }
.stApp .st-key-planner_shell { gap:0; }
.gh-brand { display:flex; align-items:center; gap:12px; margin:0 0 38px 20px; color:var(--gh-ink); }
.gh-logo, .gh-logo svg { display:block; width:43px; height:43px; flex:none; }
.gh-brand-name { font-size:21px; font-weight:700; letter-spacing:-.5px; }
.gh-brand-name small { display:block; margin-top:3px; font-size:14px; font-weight:400; color:var(--gh-muted); letter-spacing:0; }
.st-key-notebook_index { margin-left:20px; width:calc(100% - 20px); }
.st-key-notebook_index [role="radiogroup"] { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:8px; align-items:end; }
.st-key-notebook_index [role="radiogroup"] label { --tab-fill:#F3DEE6; position:relative; min-width:0; min-height:72px; margin:0; padding:28px 12px 13px; border:1px solid #45475B12; border-bottom:0; border-radius:10px 10px 0 0; background:var(--tab-fill); color:var(--gh-ink); }
.st-key-notebook_index [role="radiogroup"] > div:nth-child(2) label { --tab-fill:#F5E6D8; }
.st-key-notebook_index [role="radiogroup"] > div:nth-child(3) label { --tab-fill:#F4EDCD; }
.st-key-notebook_index [role="radiogroup"] > div:nth-child(4) label { --tab-fill:#DEECE1; }
.st-key-notebook_index [role="radiogroup"] > div:nth-child(5) label { --tab-fill:#DEEAF4; }
.st-key-notebook_index [role="radiogroup"] > div:nth-child(6) label { --tab-fill:#E7E0F0; }
.st-key-notebook_index [role="radiogroup"] > div:nth-child(7) label { --tab-fill:#F1E0DC; }
.st-key-notebook_index [role="radiogroup"] label::before { position:absolute; top:9px; left:12px; font-size:11px; color:var(--gh-muted); letter-spacing:1px; }
.st-key-notebook_index [role="radiogroup"] > div:nth-child(1) label::before { content:"01"; }
.st-key-notebook_index [role="radiogroup"] > div:nth-child(2) label::before { content:"02"; }
.st-key-notebook_index [role="radiogroup"] > div:nth-child(3) label::before { content:"03"; }
.st-key-notebook_index [role="radiogroup"] > div:nth-child(4) label::before { content:"04"; }
.st-key-notebook_index [role="radiogroup"] > div:nth-child(5) label::before { content:"05"; }
.st-key-notebook_index [role="radiogroup"] > div:nth-child(6) label::before { content:"06"; }
.st-key-notebook_index [role="radiogroup"] > div:nth-child(7) label::before { content:"07"; }
.st-key-notebook_index [role="radiogroup"] label > div > div:first-child { display:none; }
.st-key-notebook_index [role="radiogroup"] label p { font-size:14px; line-height:1.45; white-space:normal; word-break:keep-all; overflow-wrap:break-word; margin:0; }
.st-key-notebook_index [role="radiogroup"] label:has(input:checked), .st-key-notebook_index [role="radiogroup"] label:has([aria-checked="true"]) { min-height:82px; box-shadow:inset 0 -3px 0 #656A8360; }
.st-key-notebook_index [role="radiogroup"] label:has(input:checked) p { font-weight:700; }
.st-key-notebook_index [role="radiogroup"] label:focus-within { outline:3px solid #9297B5; outline-offset:2px; }
.stApp .st-key-notebook_page { position:relative; margin-left:20px; width:calc(100% - 20px); min-width:0; gap:16px; padding:30px 30px 24px 64px; border:1px solid var(--gh-line); border-radius:4px 4px 11px 11px; background-color:var(--gh-paper); background-image:linear-gradient(#656A830B 1px,transparent 1px),linear-gradient(90deg,#656A830B 1px,transparent 1px); background-size:24px 24px; box-shadow:0 8px 0 #DAD5E5,0 12px 24px #656A8310; }
.st-key-notebook_page::before, .st-key-notebook_page::after { content:""; position:absolute; top:26px; bottom:26px; pointer-events:none; }
.st-key-notebook_page::before { z-index:2; left:-6px; width:30px; background:repeating-linear-gradient(to bottom,transparent 0,transparent 31px,#D6D3DD 31px,#FEFEFF 33px,#B9B6C4 37px,#E9E6EE 40px,transparent 40px,transparent 80px); }
.st-key-notebook_page::after { z-index:1; left:17px; width:8px; background:radial-gradient(ellipse 4px 8px at center 35px,#B4ACBD 90%,transparent 100%) 0 0 / 8px 80px repeat-y; }
.st-key-notebook_page .st-key-notebook_date { position:absolute; top:32px; right:30px; width:auto; max-width:180px; text-align:right; }
.st-key-notebook_page [data-testid="stHeading"]:has(h2) { border-bottom:1px solid #D7D3DF; padding-bottom:14px; }
.st-key-notebook_page h2 { font-size:28px; line-height:1.4; margin:0; padding:0 195px 0 0; }
.st-key-notebook_page h3 { font-size:20px; line-height:1.5; padding:0 0 8px; }
.st-key-notebook_page h4 { font-size:17px; line-height:1.5; padding:0 0 8px; }
.stApp h1, .stApp h2, .stApp h3, .stApp h4 { color:var(--gh-ink); letter-spacing:-.03em; overflow-wrap:anywhere; }
.stApp [data-testid="stCaptionContainer"] { color:var(--gh-muted); }
.st-key-notebook_page [data-testid="stColumn"], .st-key-notebook_page [data-testid="stVerticalBlock"], .st-key-notebook_page [data-testid="stMarkdownContainer"] { min-width:0; }
.st-key-notebook_page [data-testid="stText"], .st-key-notebook_page [data-testid="stMarkdownContainer"] p, .st-key-notebook_page [data-testid="stMarkdownContainer"] li { overflow-wrap:anywhere; line-height:1.65; }
.st-key-notebook_page [data-testid="stButton"] button, .st-key-notebook_page [data-testid="stFormSubmitButton"] button { min-height:42px; height:auto; border-radius:7px; padding:9px 13px; }
.st-key-notebook_page button p, .st-key-notebook_page [data-testid="stWidgetLabel"] p { white-space:normal; line-height:1.45; overflow-wrap:anywhere; }
.st-key-notebook_page [data-testid="stForm"], .st-key-notebook_page [data-testid="stExpander"] { background:#FFFFFF; border-color:var(--gh-line); border-radius:5px; }
.st-key-notebook_page [data-testid="stExpander"] summary p { white-space:normal; overflow-wrap:anywhere; }
.st-key-notebook_page [data-testid="stMetric"] { background:transparent; border:0; box-shadow:none; border-radius:0; padding:0 10px; }
.st-key-notebook_page [data-testid="stMetricLabel"] { color:var(--gh-muted); }
.st-key-notebook_page [data-testid="stMetricValue"] { color:var(--gh-ink); font-size:28px; }
.st-key-dashboard_metrics { padding-bottom:18px; border-bottom:1px solid var(--gh-line); }
.st-key-notebook_footer { margin-top:20px; padding-top:15px; border-top:1px solid #D7D3DF; }
.st-key-notebook_page [class*="st-key-catalog_item_"] { gap:12px; }
.st-key-notebook_page [class*="st-key-catalog_content_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] { border-bottom:1px solid var(--gh-line); padding:12px 0; }
.st-key-notebook_page [data-testid="stLayoutWrapper"]:has(> [class*="st-key-catalog_item_"]),
.st-key-notebook_page [data-testid="stLayoutWrapper"]:has(> [class*="st-key-dashboard_queue_"]) { background:#FFFFFF; border-radius:5px; border-color:var(--gh-line); }
.st-key-notebook_page [data-testid="stLayoutWrapper"]:has(> .st-key-dashboard_reminder) { background:#FFF4BB; border-radius:5px; border-color:#E8D98C; }
.st-key-notebook_page [data-testid="stLayoutWrapper"]:has(> .st-key-criteria_final) { background:#EAF3EC; border-radius:5px; border-color:#D2E1D5; }
@media(max-width:1100px) {
    .st-key-dashboard_metrics > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
    .st-key-dashboard_metrics > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { width:calc(25% - 12px); flex:1 1 calc(25% - 12px); }
}
@media(max-width:960px) {
    [data-testid="stMainBlockContainer"] { padding:44px 20px 32px; }
    .stApp .st-key-notebook_page { padding:28px 22px 22px 52px; }
    .st-key-notebook_index [role="radiogroup"] label { padding-left:9px; padding-right:9px; }
    .st-key-notebook_index [role="radiogroup"] label p { font-size:13px; }
    .st-key-notebook_page [class*="st-key-catalog_row_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
    .st-key-notebook_page [class*="st-key-catalog_row_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child { width:100%; flex:1 1 100%; }
    .st-key-new_sample_controls > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
    .st-key-new_sample_controls > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child { width:100%; flex:1 1 100%; }
    .st-key-new_sample_controls > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:not(:first-child) { width:calc(50% - 12px); flex:1 1 calc(50% - 12px); }
}
@media(max-width:640px) {
    [data-testid="stMainBlockContainer"] { padding:40px 12px 28px; }
    .st-key-notebook_index [role="radiogroup"] { grid-template-columns:repeat(4,minmax(0,1fr)); gap:5px; }
    .st-key-notebook_index [role="radiogroup"] label, .st-key-notebook_index [role="radiogroup"] label:has(input:checked) { min-height:68px; border-radius:7px; }
    .stApp .st-key-notebook_page { padding-left:42px; padding-right:16px; }
    .st-key-notebook_page .st-key-notebook_date { position:static; width:100%; text-align:left; }
    .st-key-notebook_page h2 { padding-right:0; }
}
</style>
"""

st.set_page_config(page_title="스마트 상품 퍼블리셔 · 굿홈앤리빙", page_icon=BRAND_MARK_SVG, layout="wide")
st.markdown(NOTEBOOK_CSS, unsafe_allow_html=True)


def render_navigation() -> str:
    """화면 이름과 세션 키를 유지하는 상단 인덱스."""
    with st.container(key="notebook_index"):
        return st.radio("화면 이동", PAGES, key=NAV_KEY, horizontal=True, label_visibility="collapsed", width="stretch")


with st.container(key="planner_shell"):
    st.markdown(BRAND_HEADER_HTML, unsafe_allow_html=True)
    page = render_navigation()
    with st.container(key="notebook_page"):
        with st.container(key="notebook_date"):
            now = datetime.now(timezone(timedelta(hours=9)))
            st.caption(now.strftime("%Y년 %m월 %d일"))
        RENDERERS[page]()
        with st.container(key="notebook_footer"):
            counts = service.dashboard_counts()
            st.caption(f"승인 대기 {counts.get('pending_review', 0)}건 · 지연 {counts.get('overdue', 0)}건")
            st.caption("데모 카탈로그는 실제 쇼핑몰과 연결되어 있지 않습니다.")
