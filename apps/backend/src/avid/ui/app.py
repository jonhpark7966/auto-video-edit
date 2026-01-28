"""AVID Streamlit UI - 자동 영상 편집 테스트 인터페이스."""

import asyncio
import tempfile
from pathlib import Path

import streamlit as st

from avid.export.fcpxml import FCPXMLExporter
from avid.models.project import Project
from avid.services.evaluation import FCPXMLEvaluator
from avid.services.silence import SilenceDetectionService
from avid.services.subtitle_cut import SubtitleCutService
from avid.services.transcription import TranscriptionService

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="AVID - 자동 영상 편집",
    page_icon="\U0001f3ac",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Custom CSS — editorial / utilitarian aesthetic
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700;900&family=JetBrains+Mono:wght@400;600&display=swap');

:root {
    --ink: #0a0a0a;
    --paper: #f6f4f0;
    --accent: #d94f04;
    --accent-dim: #d94f0418;
    --muted: #8a8780;
    --rule: #d5d2cb;
    --surface: #eceae4;
    --success: #1a7a3a;
    --success-bg: #1a7a3a12;
}

/* Root container */
section[data-testid="stMainBlockContainer"] {
    max-width: 1200px;
    margin: 0 auto;
}

/* Title treatment */
h1 {
    font-family: 'Noto Sans KR', sans-serif !important;
    font-weight: 900 !important;
    letter-spacing: -0.03em !important;
    color: var(--ink) !important;
    border-bottom: 3px solid var(--ink);
    padding-bottom: 0.3em;
}

h2, h3 {
    font-family: 'Noto Sans KR', sans-serif !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
    color: var(--ink) !important;
}

/* Tab styling */
button[data-baseweb="tab"] {
    font-family: 'Noto Sans KR', sans-serif !important;
    font-weight: 500 !important;
    font-size: 1rem !important;
    letter-spacing: -0.01em;
}
button[data-baseweb="tab"][aria-selected="true"] {
    border-bottom-color: var(--accent) !important;
    color: var(--accent) !important;
}

/* Metric cards */
div[data-testid="stMetric"] {
    background: var(--paper);
    border: 1px solid var(--rule);
    border-radius: 6px;
    padding: 1rem 1.25rem;
}
div[data-testid="stMetric"] label {
    font-family: 'Noto Sans KR', sans-serif !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    font-size: 0.72rem !important;
    letter-spacing: 0.08em;
    color: var(--muted) !important;
}
div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-weight: 600 !important;
    color: var(--ink) !important;
}

/* Buttons */
button[data-testid="stBaseButton-primary"],
button[kind="primary"] {
    background-color: var(--accent) !important;
    border: none !important;
    font-family: 'Noto Sans KR', sans-serif !important;
    font-weight: 500 !important;
    letter-spacing: 0.02em;
}
button[data-testid="stBaseButton-primary"]:hover,
button[kind="primary"]:hover {
    background-color: #b84003 !important;
}

/* Download button */
button[data-testid="stDownloadButton"] button {
    border: 2px solid var(--accent) !important;
    color: var(--accent) !important;
    font-family: 'Noto Sans KR', sans-serif !important;
    font-weight: 500 !important;
}

/* Spinner */
div[data-testid="stSpinner"] {
    font-family: 'Noto Sans KR', sans-serif !important;
}

/* Expander */
details summary {
    font-family: 'Noto Sans KR', sans-serif !important;
    font-weight: 500 !important;
}

/* Code / text area */
textarea, code, pre {
    font-family: 'JetBrains Mono', monospace !important;
}

/* Selectbox / slider labels */
label, .stSlider label, .stSelectbox label {
    font-family: 'Noto Sans KR', sans-serif !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("\U0001f3ac AVID - 자동 영상 편집")
st.caption("영상 파일을 업로드하고 자동 편집 파이프라인을 실행하세요.")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VIDEO_EXTENSIONS = ["mp4", "mov", "avi", "mkv", "webm"]


def _save_uploaded(uploaded_file: st.runtime.uploaded_file_manager.UploadedFile, tmpdir: str) -> Path:
    """Persist a Streamlit UploadedFile to disk and return its Path."""
    dest = Path(tmpdir) / uploaded_file.name
    dest.write_bytes(uploaded_file.getvalue())
    return dest


def _run_async(coro):  # noqa: ANN001, ANN202
    """Run an async coroutine from synchronous Streamlit context."""
    return asyncio.run(coro)


def _format_ms(ms: int) -> str:
    """Format milliseconds as human-readable m:ss.SSS."""
    total_s = ms / 1000
    minutes = int(total_s // 60)
    seconds = total_s % 60
    return f"{minutes}:{seconds:06.3f}"


# ---------------------------------------------------------------------------
# Tab definitions
# ---------------------------------------------------------------------------

tab_transcribe, tab_silence, tab_subtitle_cut, tab_evaluate = st.tabs(
    [
        "\U0001f3a4  음성 인식",
        "\U0001f507  무음 감지",
        "\U0000270d\ufe0f  자막 컷",
        "\U0001f4ca  평가",
    ]
)

# ===== Tab 1: 음성 인식 (Transcribe) =======================================
with tab_transcribe:
    st.header("음성 인식")
    st.markdown("동영상 파일에서 음성을 인식하여 **SRT 자막 파일**을 생성합니다.")

    col_upload, col_params = st.columns([2, 1])

    with col_upload:
        tr_video = st.file_uploader(
            "영상 파일 업로드",
            type=VIDEO_EXTENSIONS,
            key="tr_video",
            help="mp4, mov, avi, mkv, webm 형식 지원",
        )

    with col_params:
        tr_lang = st.selectbox(
            "언어",
            options=["ko", "en", "ja", "zh"],
            format_func={"ko": "한국어", "en": "English", "ja": "日本語", "zh": "中文"}.get,
            key="tr_lang",
        )
        tr_model = st.selectbox(
            "Whisper 모델",
            options=["tiny", "base", "small", "medium", "large"],
            index=1,
            key="tr_model",
        )

    if st.button("실행", key="tr_run", type="primary", disabled=tr_video is None):
        tmpdir = tempfile.mkdtemp(prefix="avid_tr_")
        video_path = _save_uploaded(tr_video, tmpdir)

        svc = TranscriptionService()
        if not svc.is_available():
            st.error("Whisper CLI를 찾을 수 없습니다. `pip install openai-whisper`로 설치해주세요.")
        else:
            try:
                with st.spinner("음성 인식 중... (모델 크기에 따라 수 분 소요될 수 있습니다)"):
                    srt_path = _run_async(
                        svc.transcribe(video_path, language=tr_lang, model=tr_model, output_dir=Path(tmpdir))
                    )

                srt_content = srt_path.read_text(encoding="utf-8")
                st.session_state["tr_srt_content"] = srt_content
                st.session_state["tr_srt_name"] = srt_path.name

                st.success(f"음성 인식 완료 \u2014 {srt_path.name}")
            except Exception as exc:
                st.error(f"음성 인식 실패: {exc}")

    # Show results persisted in session state
    if "tr_srt_content" in st.session_state:
        st.divider()
        st.subheader("생성된 자막")
        st.text_area(
            "SRT 내용",
            value=st.session_state["tr_srt_content"],
            height=320,
            key="tr_srt_display",
        )
        st.download_button(
            label="\u2b07 SRT 다운로드",
            data=st.session_state["tr_srt_content"],
            file_name=st.session_state.get("tr_srt_name", "output.srt"),
            mime="text/plain",
        )

# ===== Tab 2: 무음 감지 (Silence Detection) ================================
with tab_silence:
    st.header("무음 감지")
    st.markdown("영상에서 무음 구간을 감지하여 **FCPXML 편집 파일**을 생성합니다.")

    col_files, col_params2 = st.columns([2, 1])

    with col_files:
        si_video = st.file_uploader(
            "영상 파일 업로드",
            type=VIDEO_EXTENSIONS,
            key="si_video",
        )
        si_srt = st.file_uploader(
            "SRT 파일 업로드 (선택사항)",
            type=["srt"],
            key="si_srt",
            help="자막 파일이 있으면 무음 감지 정확도가 올라갑니다.",
        )

    with col_params2:
        si_mode = st.selectbox(
            "감지 모드",
            options=["or", "and", "ffmpeg_only", "srt_only"],
            format_func={
                "or": "OR (FFmpeg \u222a SRT)",
                "and": "AND (FFmpeg \u2229 SRT)",
                "ffmpeg_only": "FFmpeg만",
                "srt_only": "SRT만",
            }.get,
            key="si_mode",
        )
        si_tight = st.checkbox("타이트 모드", value=True, key="si_tight", help="컷 영역을 최소화합니다.")
        si_min_silence = st.slider(
            "최소 무음 길이 (ms)",
            min_value=100,
            max_value=2000,
            value=500,
            step=50,
            key="si_min_silence",
        )
        si_noise_db = st.slider(
            "노이즈 임계값 (dB)",
            min_value=-60.0,
            max_value=-20.0,
            value=-40.0,
            step=1.0,
            key="si_noise_db",
        )

    if st.button("실행", key="si_run", type="primary", disabled=si_video is None):
        tmpdir = tempfile.mkdtemp(prefix="avid_si_")
        video_path = _save_uploaded(si_video, tmpdir)
        srt_path = _save_uploaded(si_srt, tmpdir) if si_srt else None

        try:
            with st.spinner("무음 구간 분석 중..."):
                svc = SilenceDetectionService()
                project, project_path = _run_async(
                    svc.detect(
                        video_path=video_path,
                        srt_path=srt_path,
                        output_dir=Path(tmpdir),
                        mode=si_mode,
                        tight=si_tight,
                        min_silence_ms=si_min_silence,
                        noise_db=si_noise_db,
                    )
                )

            # Export FCPXML
            with st.spinner("FCPXML 내보내기 중..."):
                exporter = FCPXMLExporter()
                fcpxml_path = Path(tmpdir) / f"{video_path.stem}_silence.fcpxml"
                fcpxml_path = _run_async(exporter.export(project, fcpxml_path))

            fcpxml_content = fcpxml_path.read_text(encoding="utf-8")
            st.session_state["si_edit_count"] = len(project.edit_decisions)
            st.session_state["si_fcpxml_content"] = fcpxml_content
            st.session_state["si_fcpxml_name"] = fcpxml_path.name

            st.success(f"무음 감지 완료 \u2014 {len(project.edit_decisions)}개 편집 결정")
        except Exception as exc:
            st.error(f"무음 감지 실패: {exc}")

    # Persisted results
    if "si_fcpxml_content" in st.session_state:
        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.metric("편집 결정 수", st.session_state["si_edit_count"])
        with c2:
            st.download_button(
                label="\u2b07 FCPXML 다운로드",
                data=st.session_state["si_fcpxml_content"],
                file_name=st.session_state.get("si_fcpxml_name", "silence.fcpxml"),
                mime="application/xml",
            )

# ===== Tab 3: 자막 컷 (Subtitle Cut) ======================================
with tab_subtitle_cut:
    st.header("자막 컷")
    st.markdown("자막과 영상을 기반으로 **Claude AI**가 편집 포인트를 분석합니다.")

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        sc_video = st.file_uploader(
            "영상 파일 업로드",
            type=VIDEO_EXTENSIONS,
            key="sc_video",
        )
    with col_f2:
        sc_srt = st.file_uploader(
            "SRT 파일 업로드 (필수)",
            type=["srt"],
            key="sc_srt",
        )

    if st.button("실행", key="sc_run", type="primary", disabled=(sc_video is None or sc_srt is None)):
        tmpdir = tempfile.mkdtemp(prefix="avid_sc_")
        video_path = _save_uploaded(sc_video, tmpdir)
        srt_path = _save_uploaded(sc_srt, tmpdir)

        try:
            with st.spinner("Claude AI 분석 중... (최대 3분 소요)"):
                svc = SubtitleCutService()
                project, project_path = _run_async(
                    svc.analyze(
                        srt_path=srt_path,
                        video_path=video_path,
                        output_dir=Path(tmpdir),
                    )
                )

            # Export FCPXML
            with st.spinner("FCPXML 내보내기 중..."):
                exporter = FCPXMLExporter()
                fcpxml_path = Path(tmpdir) / f"{video_path.stem}_subtitle_cut.fcpxml"
                fcpxml_path = _run_async(exporter.export(project, fcpxml_path))

            fcpxml_content = fcpxml_path.read_text(encoding="utf-8")
            st.session_state["sc_edit_count"] = len(project.edit_decisions)
            st.session_state["sc_decisions"] = [
                {
                    "start": _format_ms(d.range.start_ms),
                    "end": _format_ms(d.range.end_ms),
                    "duration_s": round(d.range.duration_ms / 1000, 2),
                    "type": d.edit_type.value,
                    "reason": d.reason.value,
                    "confidence": round(d.confidence, 2),
                }
                for d in project.edit_decisions
            ]
            st.session_state["sc_fcpxml_content"] = fcpxml_content
            st.session_state["sc_fcpxml_name"] = fcpxml_path.name

            st.success(f"자막 컷 분석 완료 \u2014 {len(project.edit_decisions)}개 편집 결정")
        except Exception as exc:
            st.error(f"자막 컷 분석 실패: {exc}")

    # Persisted results
    if "sc_fcpxml_content" in st.session_state:
        st.divider()
        st.metric("편집 결정 수", st.session_state["sc_edit_count"])

        with st.expander("컷 목록 보기", expanded=True):
            if st.session_state["sc_decisions"]:
                st.dataframe(
                    st.session_state["sc_decisions"],
                    column_config={
                        "start": st.column_config.TextColumn("시작"),
                        "end": st.column_config.TextColumn("종료"),
                        "duration_s": st.column_config.NumberColumn("길이 (초)", format="%.2f"),
                        "type": st.column_config.TextColumn("유형"),
                        "reason": st.column_config.TextColumn("사유"),
                        "confidence": st.column_config.NumberColumn("신뢰도", format="%.2f"),
                    },
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("편집 결정이 없습니다.")

        st.download_button(
            label="\u2b07 FCPXML 다운로드",
            data=st.session_state["sc_fcpxml_content"],
            file_name=st.session_state.get("sc_fcpxml_name", "subtitle_cut.fcpxml"),
            mime="application/xml",
        )

# ===== Tab 4: 평가 (Evaluate) =============================================
with tab_evaluate:
    st.header("평가")
    st.markdown("자동 생성된 FCPXML과 수동 편집 FCPXML을 비교하여 **편집 정확도**를 측정합니다.")

    col_pred, col_gt = st.columns(2)
    with col_pred:
        ev_pred = st.file_uploader(
            "예측 FCPXML (자동 생성)",
            type=["fcpxml"],
            key="ev_pred",
        )
    with col_gt:
        ev_gt = st.file_uploader(
            "정답 FCPXML (수동 편집)",
            type=["fcpxml"],
            key="ev_gt",
        )

    ev_threshold = st.slider(
        "오버랩 임계값 (ms)",
        min_value=50,
        max_value=1000,
        value=200,
        step=25,
        key="ev_threshold",
        help="예측과 정답 컷이 일치로 판정되려면 이 값 이상 겹쳐야 합니다.",
    )

    if st.button("평가 실행", key="ev_run", type="primary", disabled=(ev_pred is None or ev_gt is None)):
        tmpdir = tempfile.mkdtemp(prefix="avid_ev_")
        pred_path = _save_uploaded(ev_pred, tmpdir)
        gt_path = _save_uploaded(ev_gt, tmpdir)

        try:
            with st.spinner("FCPXML 비교 평가 중..."):
                evaluator = FCPXMLEvaluator()
                result = evaluator.evaluate(
                    predicted_fcpxml=pred_path,
                    ground_truth_fcpxml=gt_path,
                    overlap_threshold_ms=ev_threshold,
                )
                report = evaluator.format_report(result)

            st.session_state["ev_result"] = result
            st.session_state["ev_report"] = report

            st.success("평가 완료")
        except Exception as exc:
            st.error(f"평가 실패: {exc}")

    # Persisted results
    if "ev_result" in st.session_state:
        result = st.session_state["ev_result"]
        st.divider()

        # Primary metrics row
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Precision", f"{result.precision:.1%}")
        with m2:
            st.metric("Recall", f"{result.recall:.1%}")
        with m3:
            st.metric("F1 Score", f"{result.f1:.1%}")

        # Secondary metrics
        m4, m5, m6, m7 = st.columns(4)
        with m4:
            st.metric("타임라인 오버랩", f"{result.timeline_overlap_ratio:.1%}")
        with m5:
            st.metric("일치", f"{result.matched_cuts}")
        with m6:
            st.metric("미감지", f"{result.missed_cuts}")
        with m7:
            st.metric("초과 감지", f"{result.extra_cuts}")

        st.divider()

        # Full report
        st.subheader("상세 리포트")
        st.text(st.session_state["ev_report"])

        # Expandable detail sections
        if result.missed_ranges:
            with st.expander(f"미감지 컷 ({len(result.missed_ranges)}개)", expanded=False):
                for start, end in result.missed_ranges:
                    dur = (end - start) / 1000
                    st.text(f"  {_format_ms(start)}  \u2192  {_format_ms(end)}   ({dur:.2f}s)")

        if result.extra_ranges:
            with st.expander(f"초과 감지 컷 ({len(result.extra_ranges)}개)", expanded=False):
                for start, end in result.extra_ranges:
                    dur = (end - start) / 1000
                    st.text(f"  {_format_ms(start)}  \u2192  {_format_ms(end)}   ({dur:.2f}s)")
