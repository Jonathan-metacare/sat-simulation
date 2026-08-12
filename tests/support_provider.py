"""Deterministic provider used only by integration and local smoke tests."""

from fastapi import FastAPI, File, Form, UploadFile

app = FastAPI()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/detect")
async def detect(
    l1b: UploadFile = File(...),
    thumbnail: UploadFile = File(...),
    options: str = Form("{}"),
    model: str = Form("test-yolo"),
) -> dict:
    assert await l1b.read()
    assert await thumbnail.read()
    return {
        "model_version": model,
        "detections": [
            {
                "label": "vehicle",
                "confidence": 0.91,
                "bbox_pixel": [32, 48, 96, 112],
            }
        ],
        "options_echo": options,
    }
