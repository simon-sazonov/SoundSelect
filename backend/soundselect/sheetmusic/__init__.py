"""Phase 3: sheet music from screenshots or a video, stitched in order and re-engraved as one PDF.

Research and test results: /mnt/project-files/research/sheet-video-to-pdf/ in the project files.

Its PipelineSpec is registered with ``pipeline.registry.register_pipeline``. Importing this
package must stay cheap and must not need the extras: heavy packages (homr, cv2, music21,
yt_dlp, onnxruntime, rapidocr) are imported inside functions.
"""
