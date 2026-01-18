"""Gradio UI for AVID."""

import gradio as gr

from avid import __version__


def create_gradio_app() -> gr.Blocks:
    """Create the Gradio interface for AVID."""
    with gr.Blocks(title="AVID - Auto Video Edit") as app:
        gr.Markdown(
            f"""
            # AVID - Auto Video Edit
            자동 영상 편집 파이프라인 (v{__version__})
            """
        )

        with gr.Tabs():
            # Tab 1: File Upload
            with gr.Tab("1. 파일 업로드"):
                with gr.Row():
                    with gr.Column():
                        video_input = gr.File(
                            label="영상 파일",
                            file_types=["video"],
                            type="filepath",
                        )
                        audio_input = gr.File(
                            label="오디오 파일 (선택사항 - 별도 녹음 오디오)",
                            file_types=["audio"],
                            type="filepath",
                        )
                    with gr.Column():
                        file_info = gr.JSON(
                            label="파일 정보",
                            value={},
                        )

                upload_btn = gr.Button("파일 분석", variant="primary")

            # Tab 2: Pipeline Settings
            with gr.Tab("2. 파이프라인 설정"):
                gr.Markdown("### 실행할 단계 선택")

                with gr.Row():
                    with gr.Column():
                        stage_sync = gr.Checkbox(
                            label="싱크 맞추기",
                            value=False,
                            info="영상과 오디오 파일의 싱크를 맞춥니다",
                        )
                        stage_transcribe = gr.Checkbox(
                            label="음성 인식 (Whisper)",
                            value=True,
                            info="음성을 텍스트로 변환합니다",
                        )
                        stage_silence = gr.Checkbox(
                            label="무음 구간 제거",
                            value=True,
                            info="무음 구간을 감지하고 제거합니다",
                        )
                        stage_duplicate = gr.Checkbox(
                            label="중복 제거",
                            value=False,
                            info="반복되는 말을 감지하고 제거합니다",
                        )

                    with gr.Column():
                        gr.Markdown("### 단계별 옵션")

                        with gr.Accordion("무음 감지 옵션", open=False):
                            silence_threshold = gr.Slider(
                                label="무음 임계값 (dB)",
                                minimum=-60,
                                maximum=-20,
                                value=-40,
                                step=1,
                            )
                            silence_min_duration = gr.Slider(
                                label="최소 무음 길이 (ms)",
                                minimum=100,
                                maximum=2000,
                                value=500,
                                step=100,
                            )

                        with gr.Accordion("중복 감지 옵션", open=False):
                            duplicate_threshold = gr.Slider(
                                label="유사도 임계값",
                                minimum=0.5,
                                maximum=1.0,
                                value=0.8,
                                step=0.05,
                            )

            # Tab 3: Processing
            with gr.Tab("3. 처리"):
                with gr.Row():
                    process_btn = gr.Button("파이프라인 실행", variant="primary")
                    cancel_btn = gr.Button("취소", variant="stop")

                progress_bar = gr.Progress()
                status_text = gr.Textbox(
                    label="상태",
                    value="대기 중...",
                    interactive=False,
                )

                with gr.Accordion("처리 로그", open=False):
                    log_output = gr.Textbox(
                        label="로그",
                        lines=10,
                        interactive=False,
                    )

            # Tab 4: Review & Export
            with gr.Tab("4. 검토 및 내보내기"):
                gr.Markdown("### 편집 결과 검토")

                with gr.Row():
                    with gr.Column():
                        timeline_display = gr.JSON(
                            label="타임라인",
                            value={},
                        )

                    with gr.Column():
                        edit_list = gr.Dataframe(
                            label="편집 목록",
                            headers=["시작", "끝", "유형", "이유", "신뢰도"],
                            datatype=["str", "str", "str", "str", "number"],
                            interactive=True,
                        )

                gr.Markdown("### 내보내기")

                with gr.Row():
                    export_format = gr.Radio(
                        label="내보내기 형식",
                        choices=["Final Cut Pro (.fcpxml)", "Premiere Pro (.xml)"],
                        value="Final Cut Pro (.fcpxml)",
                    )
                    export_btn = gr.Button("내보내기", variant="primary")

                export_output = gr.File(label="다운로드")

        # Event handlers (placeholder implementations)
        def analyze_files(video_path: str | None, audio_path: str | None) -> dict:
            """Analyze uploaded files and return info."""
            info = {"status": "분석 완료"}
            if video_path:
                info["video"] = {"path": video_path, "type": "video"}
            if audio_path:
                info["audio"] = {"path": audio_path, "type": "audio"}
            if not video_path and not audio_path:
                info = {"status": "파일을 업로드해주세요"}
            return info

        def run_pipeline(
            video_path: str | None,
            audio_path: str | None,
            sync: bool,
            transcribe: bool,
            silence: bool,
            duplicate: bool,
            silence_db: float,
            silence_ms: int,
            dup_threshold: float,
            progress: gr.Progress = gr.Progress(),
        ) -> tuple[str, str]:
            """Run the pipeline with selected stages."""
            stages = []
            if sync:
                stages.append("sync")
            if transcribe:
                stages.append("transcribe")
            if silence:
                stages.append("silence")
            if duplicate:
                stages.append("duplicate")

            if not stages:
                return "단계를 선택해주세요", ""

            # Placeholder - actual implementation will use PipelineExecutor
            log_lines = []
            for i, stage in enumerate(stages):
                progress((i + 1) / len(stages), desc=f"처리 중: {stage}")
                log_lines.append(f"[INFO] Stage '{stage}' - 준비됨 (구현 예정)")

            return "파이프라인 실행 준비 완료 (실제 처리는 Stage 구현 후)", "\n".join(log_lines)

        # Connect events
        upload_btn.click(
            fn=analyze_files,
            inputs=[video_input, audio_input],
            outputs=[file_info],
        )

        process_btn.click(
            fn=run_pipeline,
            inputs=[
                video_input,
                audio_input,
                stage_sync,
                stage_transcribe,
                stage_silence,
                stage_duplicate,
                silence_threshold,
                silence_min_duration,
                duplicate_threshold,
            ],
            outputs=[status_text, log_output],
        )

    return app


if __name__ == "__main__":
    # For standalone testing
    app = create_gradio_app()
    app.launch()
