from __future__ import annotations

import argparse
import asyncio
import multiprocessing
import socket
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import uvicorn
import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}


def resource_base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def frontend_dist_dir() -> Path:
    return resource_base_dir() / "frontend" / "Pathfinding-Visualizer-ThreeJS-master" / "dist"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the independent frontend display component.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-auto-port", action="store_true")
    return parser.parse_args()


def is_port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) != 0


def choose_port(host: str, requested_port: int, auto_port: bool) -> int:
    if not auto_port or is_port_free(host, requested_port):
        return requested_port
    for port in range(requested_port + 1, requested_port + 51):
        if is_port_free(host, port):
            return port
    return requested_port


def websocket_url(api_url: str, path: str, query: str) -> str:
    parsed = urlparse(api_url.rstrip("/"))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    base = f"{scheme}://{parsed.netloc}"
    suffix = path
    if query:
        suffix = f"{suffix}?{query}"
    return urljoin(base, suffix)


def build_app(api_url: str) -> FastAPI:
    dist_dir = frontend_dist_dir()
    if not (dist_dir / "index.html").exists():
        raise RuntimeError(f"frontend dist not found: {dist_dir}")

    app = FastAPI(title="Display UI Component")
    app.mount("/Pathfinding-Visualizer-ThreeJS", StaticFiles(directory=dist_dir, html=True), name="frontend")

    @app.get("/")
    async def index_redirect() -> RedirectResponse:
        return RedirectResponse("/pathfinding")

    @app.get("/dashboard")
    async def dashboard_redirect() -> RedirectResponse:
        return RedirectResponse("/pathfinding")

    @app.get("/pathfinding")
    async def pathfinding_index() -> HTMLResponse:
        html = (dist_dir / "index.html").read_text(encoding="utf-8")
        html = html.replace(
            "<head>",
            '<head><script>if ("serviceWorker" in navigator) { navigator.serviceWorker.getRegistrations().then(function(registrations) { registrations.forEach(function(registration) { registration.unregister(); }); }); }</script>',
        )
        return HTMLResponse(html, headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"})

    @app.websocket("/ws")
    async def proxy_websocket(websocket: WebSocket) -> None:
        await websocket.accept()
        target_url = websocket_url(api_url, "/ws", str(websocket.url.query))
        try:
            async with websockets.connect(target_url, max_size=None) as upstream:
                async def client_to_upstream() -> None:
                    while True:
                        message = await websocket.receive()
                        if "text" in message and message["text"] is not None:
                            await upstream.send(message["text"])
                        elif "bytes" in message and message["bytes"] is not None:
                            await upstream.send(message["bytes"])

                async def upstream_to_client() -> None:
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)

                tasks = [
                    asyncio.create_task(client_to_upstream()),
                    asyncio.create_task(upstream_to_client()),
                ]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                for task in done:
                    task.result()
        except WebSocketDisconnect:
            return
        except Exception:
            await websocket.close(code=1011)

    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy_http(full_path: str, request: Request) -> Response:
        query = request.url.query
        target = urljoin(f"{api_url.rstrip('/')}/", full_path)
        if query:
            target = f"{target}?{query}"
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        async with httpx.AsyncClient(follow_redirects=False, timeout=60.0) as client:
            upstream = await client.request(
                request.method,
                target,
                headers=headers,
                content=await request.body(),
            )
        response_headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        return Response(upstream.content, status_code=upstream.status_code, headers=response_headers)

    return app


def main() -> None:
    args = parse_args()
    port = choose_port(args.host, args.port, auto_port=not args.no_auto_port)
    url = f"http://{args.host}:{port}/pathfinding"
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"[display-ui] serving {url}")
    print(f"[display-ui] proxy API {args.api_url.rstrip('/')}")
    uvicorn.run(build_app(args.api_url), host=args.host, port=port, log_level="info")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
