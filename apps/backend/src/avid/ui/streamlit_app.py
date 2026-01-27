"""Streamlit UI for AVID - 자동 영상 편집.

Run with:
    streamlit run apps/backend/src/avid/ui/streamlit_app.py
"""

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any

import streamlit as st

from avid.errors import AVIDError
from avid.export.fcpxml import FCPXMLExporter
from avid.models.media import MediaFile, MediaInfo
from avid.models.pipeline import StageResult
from avid.models.project import Project, TranscriptSegment, Transcription
from avid.models.timeline import EditDecision, EditType, EditReason, TimeRange
from avid.pipeline.base import ProgressCallback
from avid.pipeline.context import PipelineContext
from avid.pipeline.stages.silence import SilenceStage
from avid.pipeline.stages.subtitle_analysis import SubtitleAnalysisStage
from avid.pipeline.stages.transcribe import TranscribeStage
from avid.services.audio_analyzer import AudioAnalyzer
from avid.services.transcription import TranscriptionService

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="AVID - 자동 영상 편집",
    page_icon="🎬",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------
_DEFAULT_STATE: dict[str, Any] = {
    "uploaded_video": None,
    "uploaded_audio": None,
    "uploaded_srt": None,
    "temp_dir": None,
    "silence_result": None,
    "subtitle_result": None,
    "transcribe_result": None,
    "project": None,
    "fcpxml_bytes": None,
}

for key, default in _DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = default


def _get_temp_dir() -> Path:
    """Get or create a temporary working directory for this session."""
    if st.session_state["temp_dir"] is None or not Path(st.session_state["temp_dir"]).exists():
        td = tempfile.mkdtemp(prefix="avid_")
        st.session_state["temp_dir"] = td
    return Path(st.session_state["temp_dir"])


# ---------------------------------------------------------------------------
# Sidebar — Configuration
# ---------------------------------------------------------------------------
st.sidebar.title("설정")

st.sidebar.header("무음 감지 옵션")
min_silence_ms = st.sidebar.slider(
    "최소 무음 길이 (ms)", min_value=100, max_value=2000, value=500, step=50,
)
silence_threshold_db = st.sidebar.slider(
    "무음 임계값 (dB)", min_value=-60, max_value=-20, value=-40, step=1,
)
padding_ms = st.sidebar.slider(
    "패딩 (ms)", min_value=0, max_value=500, value=100, step=10,
)
tight_mode = st.sidebar.checkbox("Tight 모드 (교차 검출)", value=True)

st.sidebar.header("AI 분석 옵션")
ai_providers = st.sidebar.multiselect(
    "AI 제공자", options=["claude", "codex"], default=["claude"],
)
decision_maker = st.sidebar.selectbox(
    "결정 전략", options=["majority", "any", "all"], index=0,
)

st.sidebar.header("출력 형식")
export_format = st.sidebar.selectbox("형식", options=["FCPXML"], index=0)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_uploaded_file(uploaded_file: Any, dest_dir: Path) -> Path:
    """Save a Streamlit UploadedFile to disk and return the path."""
    dest = dest_dir / uploaded_file.name
    dest.write_bytes(uploaded_file.getbuffer())
    return dest


def _make_media_file(path: Path) -> MediaFile:
    """Create a MediaFile from a path with basic info.

    In a production setting, MediaService.get_media_info() would be used
    to extract real metadata via ffprobe. Here we create a stub.
    """
    suffix = path.suffix.lower()
    is_video = suffix in {".mp4", ".mov", ".avi", ".mkv"}

    return MediaFile(
        path=path,
        original_name=path.name,
        info=MediaInfo(
            duration_ms=0,  # will be filled by AudioAnalyzer
            width=1920 if is_video else None,
            height=1080 if is_video else None,
            fps=30.0 if is_video else None,
            sample_rate=44100,
        ),
    )


def _build_pipeline_context(temp_dir: Path) -> PipelineContext:
    """Build a PipelineContext from uploaded files."""
    output_dir = temp_dir / "output"
    output_dir.mkdir(exist_ok=True)

    ctx = PipelineContext(working_dir=temp_dir, output_dir=output_dir)

    video_path = st.session_state.get("uploaded_video")
    audio_path = st.session_state.get("uploaded_audio")

    if video_path:
        ctx.video_file = _make_media_file(Path(video_path))
    if audio_path:
        ctx.audio_file = _make_media_file(Path(audio_path))

    return ctx


def _collect_edit_decisions() -> list[EditDecision]:
    """Collect all EditDecision objects from session results."""
    decisions: list[EditDecision] = []

    for result_key in ("silence_result", "subtitle_result"):
        result_data = st.session_state.get(result_key)
        if result_data and isinstance(result_data, dict):
            raw_decisions = result_data.get("edit_decisions", [])
            for d in raw_decisions:
                if isinstance(d, dict):
                    decisions.append(EditDecision.model_validate(d))
                elif isinstance(d, EditDecision):
                    decisions.append(d)

    return decisions


# ---------------------------------------------------------------------------
# Main title
# ---------------------------------------------------------------------------
st.title("AVID - 자동 영상 편집")
st.markdown("영상/오디오 파일에서 무음 구간 감지, 음성 인식, AI 자막 분석을 수행합니다.")

# ---------------------------------------------------------------------------
# File upload section
# ---------------------------------------------------------------------------
st.header("파일 업로드")

col_video, col_audio, col_srt = st.columns(3)

with col_video:
    video_file = st.file_uploader(
        "영상 파일", type=["mp4", "mov", "avi"], key="video_uploader",
    )
    if video_file is not None:
        temp_dir = _get_temp_dir()
        saved = _save_uploaded_file(video_file, temp_dir)
        st.session_state["uploaded_video"] = str(saved)
        st.success(f"영상 업로드: {video_file.name}")

with col_audio:
    audio_file = st.file_uploader(
        "오디오 파일", type=["wav", "mp3", "m4a"], key="audio_uploader",
    )
    if audio_file is not None:
        temp_dir = _get_temp_dir()
        saved = _save_uploaded_file(audio_file, temp_dir)
        st.session_state["uploaded_audio"] = str(saved)
        st.success(f"오디오 업로드: {audio_file.name}")

with col_srt:
    srt_file = st.file_uploader(
        "SRT 자막 파일", type=["srt"], key="srt_uploader",
    )
    if srt_file is not None:
        temp_dir = _get_temp_dir()
        saved = _save_uploaded_file(srt_file, temp_dir)
        st.session_state["uploaded_srt"] = str(saved)
        st.success(f"SRT 업로드: {srt_file.name}")

# Check if any media is available
has_media = (
    st.session_state["uploaded_video"] is not None
    or st.session_state["uploaded_audio"] is not None
)

# ---------------------------------------------------------------------------
# Action buttons
# ---------------------------------------------------------------------------
st.header("실행")

col_silence, col_subtitle, col_pipeline = st.columns(3)

# --- Silence detection ---
with col_silence:
    if st.button("무음 감지 실행", disabled=not has_media, use_container_width=True):
        with st.status("무음 감지 진행 중...", expanded=True) as status:
            try:
                temp_dir = _get_temp_dir()
                ctx = _build_pipeline_context(temp_dir)

                stage = SilenceStage()
                options: dict[str, Any] = {
                    "min_silence_ms": min_silence_ms,
                    "silence_threshold_db": float(silence_threshold_db),
                    "padding_ms": padding_ms,
                    "tight_mode": tight_mode,
                }
                srt_path = st.session_state.get("uploaded_srt")
                if srt_path:
                    options["srt_path"] = srt_path

                result = asyncio.run(stage.execute(ctx, options))

                st.session_state["silence_result"] = ctx.get_stage_data("silence")
                status.update(label="무음 감지 완료", state="complete")
                st.success(result.message or "완료")

            except AVIDError as e:
                st.error(f"오류: {e}")
            except Exception as e:
                st.error(f"예상치 못한 오류: {e}")

# --- Subtitle analysis ---
with col_subtitle:
    has_transcription = (
        st.session_state.get("transcribe_result") is not None
        or st.session_state.get("uploaded_srt") is not None
    )
    if st.button(
        "자막 분석 실행",
        disabled=not has_transcription,
        use_container_width=True,
    ):
        with st.status("자막 분석 진행 중...", expanded=True) as status:
            try:
                temp_dir = _get_temp_dir()
                ctx = _build_pipeline_context(temp_dir)

                # Load transcription data into context
                transcribe_data = st.session_state.get("transcribe_result")
                if transcribe_data:
                    ctx.transcription = transcribe_data

                stage = SubtitleAnalysisStage()
                options = {
                    "providers": ai_providers,
                    "decision_maker": decision_maker,
                }

                result = asyncio.run(stage.execute(ctx, options))

                st.session_state["subtitle_result"] = ctx.get_stage_data("subtitle_analysis")
                status.update(label="자막 분석 완료", state="complete")
                st.success(result.message or "완료")

            except AVIDError as e:
                st.error(f"오류: {e}")
            except Exception as e:
                st.error(f"예상치 못한 오류: {e}")

# --- Full pipeline ---
with col_pipeline:
    if st.button("전체 파이프라인 실행", disabled=not has_media, use_container_width=True):
        with st.status("전체 파이프라인 실행 중...", expanded=True) as status:
            try:
                temp_dir = _get_temp_dir()
                ctx = _build_pipeline_context(temp_dir)

                # Stage 1: Transcription
                st.write("1/3 음성 인식...")
                transcribe_stage = TranscribeStage()
                t_result = asyncio.run(transcribe_stage.execute(ctx, {
                    "provider": "whisper-base",
                    "language": None,
                    "export_srt": True,
                }))
                st.session_state["transcribe_result"] = ctx.get_stage_data("transcribe")
                st.write(f"  ✓ {t_result.message}")

                # Stage 2: Silence detection
                st.write("2/3 무음 감지...")
                silence_stage = SilenceStage()
                silence_options: dict[str, Any] = {
                    "min_silence_ms": min_silence_ms,
                    "silence_threshold_db": float(silence_threshold_db),
                    "padding_ms": padding_ms,
                    "tight_mode": tight_mode,
                }
                srt_path = st.session_state.get("uploaded_srt")
                if srt_path:
                    silence_options["srt_path"] = srt_path
                s_result = asyncio.run(silence_stage.execute(ctx, silence_options))
                st.session_state["silence_result"] = ctx.get_stage_data("silence")
                st.write(f"  ✓ {s_result.message}")

                # Stage 3: Subtitle analysis
                st.write("3/3 자막 분석...")
                subtitle_stage = SubtitleAnalysisStage()
                a_result = asyncio.run(subtitle_stage.execute(ctx, {
                    "providers": ai_providers,
                    "decision_maker": decision_maker,
                }))
                st.session_state["subtitle_result"] = ctx.get_stage_data("subtitle_analysis")
                st.write(f"  ✓ {a_result.message}")

                # Export FCPXML
                st.write("FCPXML 내보내기...")
                edit_decisions = _collect_edit_decisions()
                if edit_decisions:
                    project = Project(name="AVID Auto Edit")
                    # Add source media
                    primary = ctx.get_primary_media()
                    if primary:
                        project.add_source_file(primary)
                    project.edit_decisions = edit_decisions

                    exporter = FCPXMLExporter()
                    output_path = ctx.output_dir / "output.fcpxml"
                    asyncio.run(exporter.export(project, output_path))
                    st.session_state["fcpxml_bytes"] = output_path.read_bytes()
                    st.session_state["project"] = project
                    st.write("  ✓ FCPXML 내보내기 완료")

                status.update(label="전체 파이프라인 완료", state="complete")
                st.success("파이프라인 실행 완료!")

            except AVIDError as e:
                st.error(f"오류: {e}")
            except Exception as e:
                st.error(f"예상치 못한 오류: {e}")

# ---------------------------------------------------------------------------
# Results section
# ---------------------------------------------------------------------------
st.header("결과")

tab_silence, tab_subtitle, tab_export = st.tabs(["무음 감지", "자막 분석", "내보내기"])

with tab_silence:
    silence_data = st.session_state.get("silence_result")
    if silence_data:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("무음 구간 수", silence_data.get("silence_count", 0))
        with col2:
            dur_ms = silence_data.get("silence_duration_ms", 0)
            st.metric("총 무음 시간", f"{dur_ms / 1000:.1f}초")
        with col3:
            ratio = silence_data.get("silence_ratio", 0.0)
            st.metric("무음 비율", f"{ratio * 100:.1f}%")

        total_ms = silence_data.get("total_duration_ms", 0)
        if total_ms > 0:
            st.progress(
                min(ratio, 1.0),
                text=f"무음: {dur_ms / 1000:.1f}초 / 전체: {total_ms / 1000:.1f}초",
            )
    else:
        st.info("무음 감지를 실행하세요.")

with tab_subtitle:
    subtitle_data = st.session_state.get("subtitle_result")
    if subtitle_data:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("컷 발견 수", subtitle_data.get("cut_count", 0))
        with col2:
            st.metric("유지 세그먼트", subtitle_data.get("keep_count", 0))

        reason_counts = subtitle_data.get("reason_counts", {})
        if reason_counts:
            st.subheader("컷 사유별 분류")
            for reason, count in reason_counts.items():
                st.write(f"- **{reason}**: {count}개")
    else:
        st.info("자막 분석을 실행하세요.")

with tab_export:
    fcpxml_data = st.session_state.get("fcpxml_bytes")
    if fcpxml_data:
        st.success("FCPXML 파일이 준비되었습니다.")

        # Summary of all edit decisions
        all_decisions = _collect_edit_decisions()
        if all_decisions:
            st.write(f"총 편집 결정: **{len(all_decisions)}개**")

            reason_summary: dict[str, int] = {}
            for d in all_decisions:
                reason_summary[d.reason.value] = reason_summary.get(d.reason.value, 0) + 1
            for reason, count in reason_summary.items():
                st.write(f"- {reason}: {count}개")

        st.download_button(
            label="FCPXML 다운로드",
            data=fcpxml_data,
            file_name="avid_output.fcpxml",
            mime="application/xml",
            use_container_width=True,
        )
    else:
        st.info("파이프라인을 실행하면 FCPXML 파일을 다운로드할 수 있습니다.")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption("AVID - Auto Video Intelligent Director | CC BY-NC-SA 4.0")
