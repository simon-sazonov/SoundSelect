"""Phase 4: songs from YouTube links or audio files.

Separate the voice, follow the melody, find the beats, then hand notes to the music core.

Its PipelineSpec is registered with ``pipeline.registry.register_pipeline``. Importing this
package must stay cheap and must not need the extras: heavy packages (homr, cv2, music21,
yt_dlp, onnxruntime, rapidocr) are imported inside functions.
"""
