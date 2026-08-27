"""QFNU library web API and opt-in check-in/check-out scheduler."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import threading
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from qfnu_login import QFNULibraryClient, LibraryError, library_login


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class ActionRequest(BaseModel):
    confirm: bool = False
    reservation_id: str | None = None


class ReserveRequest(BaseModel):
    seat_id: str
    segment: str
    confirm: bool = False


class AutomationConfig(BaseModel):
    enabled: bool = False
    check_in_enabled: bool = True
    check_out_enabled: bool = True
    check_in_time: str = "08:50"
    check_out_time: str = "22:05"
    reservation_id: str | None = None

    @field_validator("check_in_time", "check_out_time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise ValueError("时间必须是 HH:MM 格式") from exc
        return value


class AutomationStatus(BaseModel):
    config: AutomationConfig
    running: bool
    last_action: str | None = None
    last_run_at: str | None = None
    last_message: str | None = None


_client: QFNULibraryClient | None = None
_username = ""
_config = AutomationConfig()
_status = {"last_action": None, "last_run_at": None, "last_message": None}
_run_keys: dict[str, str] = {}
_state_lock = threading.Lock()
_scheduler_task: asyncio.Task[None] | None = None


def _require_client() -> QFNULibraryClient:
    if _client is None:
        raise HTTPException(status_code=401, detail="请先登录统一身份认证")
    return _client


def _run_action(action: str, reservation_id: str | None = None) -> None:
    client = _require_client()
    try:
        if action == "check-in":
            client.check_in(confirm=True)
        else:
            client.checkout(reservation_id, confirm=True)
        message = "自动签到成功" if action == "check-in" else "自动签退成功"
    except (LibraryError, Exception) as exc:
        message = f"自动{('签到' if action == 'check-in' else '签退')}失败：{exc}"
    with _state_lock:
        _status.update(
            last_action=action,
            last_run_at=datetime.now().isoformat(timespec="seconds"),
            last_message=message,
        )


async def _automation_loop() -> None:
    while True:
        await asyncio.sleep(20)
        with _state_lock:
            config = _config.model_copy()
        if not config.enabled or _client is None:
            continue

        now = datetime.now()
        current_minute = now.strftime("%H:%M")
        day_key = now.date().isoformat()
        schedules = (
            ("check-in", config.check_in_enabled, config.check_in_time),
            ("check-out", config.check_out_enabled, config.check_out_time),
        )
        for action, enabled, target_time in schedules:
            if enabled and current_minute == target_time:
                key = f"{day_key}:{action}:{target_time}"
                if _run_keys.get(action) == key:
                    continue
                _run_keys[action] = key
                await asyncio.to_thread(_run_action, action, config.reservation_id)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _scheduler_task
    _scheduler_task = asyncio.create_task(_automation_loop())
    yield
    if _scheduler_task:
        _scheduler_task.cancel()
        await asyncio.gather(_scheduler_task, return_exceptions=True)


app = FastAPI(title="QFNU Library API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "logged_in": _client is not None, "username": _username}


@app.post("/api/auth/login")
def login(request: LoginRequest) -> dict[str, str]:
    global _client, _username
    try:
        _client = library_login(request.username, request.password)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _username = request.username
    return {"username": request.username, "name": _client.name or request.username}


@app.post("/api/auth/logout")
def logout() -> dict[str, bool]:
    global _client, _username
    _client = None
    _username = ""
    return {"ok": True}


@app.get("/api/library/classrooms")
def classrooms() -> dict[str, int]:
    return QFNULibraryClient.classrooms()


@app.get("/api/library/segments")
def segments(classroom: str, target_date: str | None = None) -> list[dict]:
    try:
        return _require_client().segments(classroom, target_date)
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/library/seats")
def seats(
    classroom: str,
    target_date: str | None = None,
    start_time: str = "08:00",
    end_time: str = "22:00",
    segment: str | None = None,
) -> list[dict]:
    try:
        return _require_client().available_seats(
            classroom, target_date, start_time, end_time, segment
        )
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/library/seat-map")
def seat_map(
    classroom: str,
    target_date: str | None = None,
    start_time: str = "08:00",
    end_time: str = "22:00",
    segment: str | None = None,
) -> list[dict]:
    try:
        return _require_client().seat_map(
            classroom, target_date, start_time, end_time, segment
        )
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/library/reservations")
def reservations() -> list[dict]:
    try:
        return _require_client().reservations()
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/library/reserve")
def reserve(request: ReserveRequest) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(status_code=400, detail="预约需要 confirm=true")
    try:
        return _require_client().reserve(request.seat_id, request.segment, confirm=True)
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/library/cancel")
def cancel(request: ActionRequest) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(status_code=400, detail="取消预约需要 confirm=true")
    if not request.reservation_id:
        raise HTTPException(status_code=400, detail="取消预约需要 reservation_id")
    try:
        return _require_client().cancel(request.reservation_id, confirm=True)
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/library/check-in")
def check_in(request: ActionRequest) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(status_code=400, detail="签到需要 confirm=true")
    try:
        return _require_client().check_in(confirm=True)
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/library/check-out")
def check_out(request: ActionRequest) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(status_code=400, detail="签退需要 confirm=true")
    try:
        return _require_client().checkout(request.reservation_id, confirm=True)
    except LibraryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/automation", response_model=AutomationStatus)
def get_automation() -> AutomationStatus:
    with _state_lock:
        return AutomationStatus(
            config=_config.model_copy(),
            running=_config.enabled and _client is not None,
            **_status,
        )


@app.put("/api/automation", response_model=AutomationStatus)
def update_automation(config: AutomationConfig) -> AutomationStatus:
    global _config
    if config.enabled and _client is None:
        raise HTTPException(status_code=401, detail="启用自动操作前请先登录")
    with _state_lock:
        _config = config
        _run_keys.clear()
        return AutomationStatus(
            config=_config.model_copy(),
            running=_config.enabled and _client is not None,
            **_status,
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=False)
