from fastapi import APIRouter, WebSocket

router = APIRouter()


# Placeholder — real session/stream routes will be implemented in a future phase.
@router.websocket("/connect")
async def ws_connect(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "connected", "status": "scaffold"})
    await websocket.close()
