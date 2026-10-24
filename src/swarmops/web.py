"""Loopback FastAPI application; static console and server-sent snapshots."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from .console import ConsoleEngine, ROOT, validate_console_scenario


def create_app(storage=None, *, threaded=True, test_host=False):
    @asynccontextmanager
    async def lifespan(app):
        app.state.engine = ConsoleEngine(storage or ROOT / "runs" / "console", threaded=threaded)
        try:
            yield
        finally:
            app.state.engine.close()

    app = FastAPI(title="SwarmOps local console", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        hosts = {"127.0.0.1", "localhost", "testserver"} if test_host else {"127.0.0.1", "localhost"}
        if request.url.hostname not in hosts:
            return JSONResponse({"detail": "Localhost requests only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
            return JSONResponse({"detail": "Cross-origin requests are not allowed"}, status_code=403)
        if request.method == "POST":
            try:
                length = int(request.headers.get("content-length", "-1"))
            except ValueError:
                length = -1
            if not 0 <= length <= 2_000_000:
                return JSONResponse({"detail": "Body must declare a size up to 2 MB"}, status_code=413)
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse({"detail": "JSON required"}, status_code=415)
            body = await request.body()
            if len(body) != length:
                return JSONResponse({"detail": "Body length mismatch"}, status_code=400)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    async def payload(request):
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError("Request must be an object")
            return data
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/state")
    def state(request: Request):
        return request.app.state.engine.snapshot()

    @app.get("/api/stream")
    async def stream(request: Request):
        async def events():
            while not await request.is_disconnected():
                snapshot = await asyncio.to_thread(request.app.state.engine.snapshot)
                yield "data: " + json.dumps(snapshot) + "\n\n"
                await asyncio.sleep(.12)
        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.post("/api/command")
    async def command(request: Request):
        data = await payload(request)
        try:
            return await asyncio.to_thread(request.app.state.engine.command, data)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/validate")
    async def validate(request: Request):
        data = await payload(request)
        try:
            scenario = await asyncio.to_thread(validate_console_scenario, data.get("scenario"))
            return {"valid": True, "cells": len(scenario.free), "jobs": len(scenario.orders)}
        except (ValueError, KeyError, TypeError) as exc:
            return {"valid": False, "error": str(exc)}

    @app.get("/api/export/{kind}")
    def export(kind: str, request: Request):
        try:
            data = request.app.state.engine.export(kind)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="swarmops-{kind}.json"'})

    @app.post("/api/experiment")
    async def experiment(request: Request):
        data = await payload(request)
        try:
            engine = request.app.state.engine
            if data.get("action") == "cancel":
                return engine.cancel_experiment()
            if data.get("action") == "start":
                return engine.start_experiment()
            raise ValueError("Use start or cancel")
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/experiment/export")
    def export_experiment(request: Request):
        return JSONResponse(request.app.state.engine.snapshot()["task"],
                            headers={"Content-Disposition": 'attachment; filename="swarmops-experiment.json"'})

    dist = ROOT / "frontend" / "dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    def home():
        if not (dist / "index.html").exists():
            raise HTTPException(503, "Frontend build missing; run ./launch.sh")
        return FileResponse(dist / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "simulation_only": True}

    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--storage", type=Path, default=ROOT / "runs/console")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    print(f"SwarmOps console: http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run(create_app(args.storage), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
