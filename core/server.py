"""
core/server.py

StreamingServer encapsulates the FastAPI application and its routes.
Previously the app was wired at module-level, making it impossible to
instantiate or test without triggering side-effects.

`server = StreamingServer()` creates the instance.
`app = server.app` is kept for uvicorn compatibility.
`run_server()` is a module-level shim for backward compatibility.
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn
import json
import asyncio
from datetime import datetime

from core.state import cache, new_stream_signals
from config import SERVER_HOST, SERVER_PORT


class StreamingServer:
    """
    Wraps the FastAPI application and registers WebSocket + REST routes.
    All route logic is private methods so the class stays testable.
    """

    def __init__(self):
        self.app = FastAPI(title="Ryuk AI Streaming Server")
        self._alert_clients: set[WebSocket] = set()
        self._register_routes()

    # ------------------------------------------------------------------
    # Route registration
    # ------------------------------------------------------------------

    def _register_routes(self):
        app = self.app

        @app.websocket("/ws/stream")
        async def camera_endpoint(websocket: WebSocket):
            await self._handle_camera(websocket)

        @app.websocket("/ws/alerts")
        async def alerts_endpoint(websocket: WebSocket):
            await self._handle_alerts(websocket)

        @app.get("/")
        def root():
            return {"message": "Ryuk AI — connect camera to /ws/stream"}

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_camera(self, websocket: WebSocket):
        await websocket.accept()
        host      = websocket.client.host
        port      = websocket.client.port
        client_id = f"{host}:{port}"

        print(f"Camera {client_id} connected.")
        cache.sadd("registry:active_streams", client_id)
        new_stream_signals.append(client_id)

        # Log connection to MongoDB (async)
        from core.database import cameras_col
        await cameras_col.update_one(
            {"client_id": client_id},
            {"$set": {"host": host, "port": port,
                      "last_connected": datetime.now(), "status": "online"}},
            upsert=True,
        )

        try:
            while True:
                data = await websocket.receive_bytes()
                cache.set(f"stream:{client_id}:frame", data, ex=2)
        except WebSocketDisconnect:
            print(f"Camera {client_id} disconnected.")
        finally:
            cache.srem("registry:active_streams", client_id)
            cache.delete(f"stream:{client_id}:frame")
            from core.database import cameras_col as col
            await col.update_one(
                {"client_id": client_id},
                {"$set": {"status": "offline"}},
            )

    async def _handle_alerts(self, websocket: WebSocket):
        """Bridge Redis pub/sub → WebSocket for alert consumers."""
        await websocket.accept()
        self._alert_clients.add(websocket)
        print("Alert client connected.")

        pubsub = cache.pubsub()
        pubsub.subscribe("security_alerts")

        try:
            while True:
                msg = pubsub.get_message(ignore_subscribe_messages=True)
                if msg:
                    await websocket.send_text(msg["data"].decode("utf-8"))
                await asyncio.sleep(0.1)
        except Exception:
            pass
        finally:
            self._alert_clients.discard(websocket)
            print("Alert client disconnected.")

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    def run(self, host: str = SERVER_HOST, port: int = SERVER_PORT):
        """Start uvicorn synchronously (call from a background thread)."""
        uvicorn.run(self.app, host=host, port=port, log_level="info")


# ---------------------------------------------------------------------------
# Module-level singleton + backward-compat shims
# ---------------------------------------------------------------------------
server = StreamingServer()
app    = server.app           # uvicorn / main.py references this directly

def run_server(host: str, port: int = SERVER_PORT):
    """Backward-compatible entry point used by main.py."""
    server.run(host, port)
