"""QFNU library web API and opt-in check-in/check-out scheduler."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading
import time
import uuid
from typing import Any, Callable, TypeVar

import requests

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from qfnu_login import (
    QFNULibraryClient,
    LibraryError,
    LibrarySessionExpired,
    library_login,
)
import qfnu_login as q


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class SliderStartResponse(BaseModel):
    token: str | None = None
    requires_slider: bool
    big_image: str | None = None
    small_image: str | None = None
    username: str | None = None


class SliderVerifyRequest(BaseModel):
    token: str
    move_length: int = Field(ge=1, le=260)
    tracks: list[dict[str, int]] = Field(min_length=2)


class ActionRequest(BaseModel):
    confirm: bool = False
    reservation_id: str | None = None


class ReserveRequest(BaseModel):
    seat_id: str
    segment: str
    confirm: bool = False


class AutomationConfig(BaseModel):
    enabled: bool = False
    repeat_daily: bool = False
    reservation_enabled: bool = False
    reservation_time: str = "19:20"
    reservation_classroom: str = ""
    reservation_seat_id: str = ""
    reservation_segment: str = ""
    check_in_enabled: bool = True
    check_out_enabled: bool = True
    check_in_time: str = "08:50"
    check_out_time: str = "22:05"
    reservation_id: str | None = None

    @field_validator("reservation_time", "check_in_time", "check_out_time")
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
_login_password = ""
_config_path = Path(__file__).with_name("automation_config.json")


def _load_automation_config() -> AutomationConfig:
    try:
        return AutomationConfig.model_validate_json(_config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AutomationConfig()


_config = _load_automation_config()
_status = {"last_action": None, "last_run_at": None, "last_message": None}
_run_keys: dict[str, str] = {}
_state_lock = threading.Lock()
_relogin_lock = threading.Lock()
_scheduler_task: asyncio.Task[None] | None = None
_pending_logins: dict[str, dict[str, Any]] = {}
SHANGHAI_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
T = TypeVar("T")


def _require_client() -> QFNULibraryClient:
    if _client is None:
        raise HTTPException(status_code=401, detail="请先登录统一身份认证")
    return _client


def _relogin(expired_client: QFNULibraryClient | None = None) -> QFNULibraryClient:
    """Refresh the in-memory library session after the server rejects it."""
    global _client
    if not _username or not _login_password:
        raise LibrarySessionExpired("图书馆会话已失效，请重新登录")
    with _relogin_lock:
        # Another request may have refreshed the same expired client already.
        if expired_client is not None and _client is not None and _client is not expired_client:
            return _client
        try:
            refreshed = library_login(_username, _login_password)
        except Exception as exc:
            _client = None
            raise LibrarySessionExpired(f"图书馆会话已失效，自动重新登录失败：{exc}") from exc
        _client = refreshed
        return refreshed


def _with_relogin(operation: Callable[[QFNULibraryClient], T]) -> T:
    """Run one library operation and retry it once after a session refresh."""
    client = _require_client()
    try:
        return operation(client)
    except LibrarySessionExpired:
        refreshed = _relogin(client)
        return operation(refreshed)


def _raise_library_http_error(exc: LibraryError) -> None:
    status_code = 401 if isinstance(exc, LibrarySessionExpired) else 400
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def _segment_label(item: dict[str, Any]) -> str:
    return str(
        item.get("name")
        or item.get("title")
        or item.get("time")
        or item.get("segment_name")
        or f"{item.get('start') or item.get('startTime') or ''}–{item.get('end') or item.get('endTime') or ''}"
    ).strip("–")


def _reserve_for_config(client: QFNULibraryClient, config: AutomationConfig) -> dict[str, Any]:
    classroom = config.reservation_classroom.strip()
    seat_id = config.reservation_seat_id.strip()
    desired_segment = config.reservation_segment.strip()
    if not classroom or not seat_id or not desired_segment:
        raise LibraryError("定时预约需要空间、座位 ID 和时段")

    segments = client.segments(classroom, "tomorrow")
    segment = next(
        (
            item
            for item in segments
            if str(item.get("id")) == desired_segment or _segment_label(item) == desired_segment
        ),
        None,
    )
    if not segment or not segment.get("id"):
        raise LibraryError("明天没有匹配的真实预约时段，请重新选择")

    seats = client.seat_map(classroom, "tomorrow", segment=str(segment["id"]))
    selected = next((item for item in seats if str(item.get("id")) == seat_id), None)
    if not selected:
        raise LibraryError("定时预约座位不属于当前空间或已失效")
    if selected.get("status") != "空闲":
        raise LibraryError(f"座位当前状态为“{selected.get('status', '未知')}”，无法预约")
    return client.reserve(seat_id, str(segment["id"]), confirm=True)


def _run_action(
    action: str,
    reservation_id: str | None = None,
    config: AutomationConfig | None = None,
) -> None:
    config = config or _config.model_copy()
    try:
        if action == "reserve":
            _with_relogin(lambda client: _reserve_for_config(client, config))
            message = "自动预约成功"
        elif action == "check-in":
            _with_relogin(lambda client: client.check_in(confirm=True))
            message = "自动签到成功"
        else:
            _with_relogin(lambda client: client.checkout(reservation_id, confirm=True))
            message = "自动签退成功"
    except (LibraryError, Exception) as exc:
        labels = {"reserve": "预约", "check-in": "签到", "check-out": "签退"}
        message = f"自动{labels.get(action, action)}失败：{exc}"
    with _state_lock:
        _status.update(
            last_action=action,
            last_run_at=datetime.now(SHANGHAI_TZ).isoformat(timespec="seconds"),
            last_message=message,
        )


async def _automation_loop() -> None:
    while True:
        await asyncio.sleep(20)
        with _state_lock:
            config = _config.model_copy()
        if not config.enabled or _client is None:
            continue

        now = datetime.now(SHANGHAI_TZ)
        current_minute = now.strftime("%H:%M")
        day_key = now.date().isoformat()
        schedules = (
            ("reserve", config.reservation_enabled, config.reservation_time),
            ("check-in", config.check_in_enabled, config.check_in_time),
            ("check-out", config.check_out_enabled, config.check_out_time),
        )
        for action, enabled, target_time in schedules:
            if enabled and current_minute == target_time:
                key = f"{day_key}:{action}:{target_time}" if config.repeat_daily else f"once:{action}:{target_time}"
                if _run_keys.get(action) == key:
                    continue
                _run_keys[action] = key
                await asyncio.to_thread(_run_action, action, config.reservation_id, config)


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
    global _client, _username, _login_password
    try:
        client = library_login(request.username, request.password)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _client = client
    _username = request.username
    _login_password = request.password
    return {"username": request.username, "name": client.name or request.username}


def _complete_manual_login(
    state: dict[str, Any],
    move_length: int | None = None,
    tracks: list[dict[str, int]] | None = None,
) -> QFNULibraryClient:
    if move_length is not None and tracks is not None:
        body = {"canvasLength": 280, "moveLength": move_length, "tracks": tracks}
        sign = q.encrypt_password(
            json.dumps(body, ensure_ascii=False, separators=(",", ":")),
            state["secret"],
        )
        verify = state["session"].post(
            q.urljoin(q.LOGIN_URL, q.SLIDER_VERIFY_URL),
            data={"sign": sign},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": state["page_url"],
            },
            timeout=20,
        )
        verify.raise_for_status()
        if verify.json().get("errorCode") != 1:
            raise HTTPException(status_code=422, detail="滑块验证未通过，请重新拖动")

    payload = {
        name: value
        for name, value in state["parsed"].fields.items()
        if name not in {"passwordText", "password"}
    }
    payload.update(
        {
            "username": state["username"],
            "password": q.encrypt_password(state["password"], state["salt"]),
            "_eventId": payload.get("_eventId", "submit"),
            "cllt": payload.get("cllt", "userNameLogin"),
            "dllt": payload.get("dllt", "generalLogin"),
        }
    )
    response = state["session"].post(
        state["action"],
        data=payload,
        headers={"Referer": state["page_url"]},
        timeout=20,
        allow_redirects=False,
    )
    state["session"].qfnu_login_location = response.headers.get("Location", "")
    if response.status_code >= 400:
        raise HTTPException(status_code=401, detail="登录提交失败，请检查账号密码")
    return QFNULibraryClient.from_login_session(state["session"])


@app.post("/api/auth/login/start", response_model=SliderStartResponse)
def login_start(request: LoginRequest) -> dict[str, Any]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    )
    page = session.get(
        q.LOGIN_URL,
        params={"service": q.LIBRARY_CAS_SERVICE},
        timeout=20,
    )
    parsed = q._parse_login_page(page.text)
    salt = parsed.fields.pop("pwdEncryptSalt", "")
    if not parsed.has_password_form or not salt:
        raise HTTPException(status_code=502, detail="登录页结构异常")

    token = uuid.uuid4().hex
    action = q.urljoin(page.url, parsed.form_action or q.LOGIN_URL)
    action = (
        f"{action}{'&' if '?' in action else '?'}"
        f"{q.urlencode({'service': q.LIBRARY_CAS_SERVICE})}"
    )
    state = {
        "session": session,
        "page_url": page.url,
        "parsed": parsed,
        "salt": salt,
        "username": request.username,
        "password": request.password,
        "action": action,
        "created": time.time(),
    }
    if q._captcha_required(session, request.username, 20):
        captcha = session.get(
            q.urljoin(q.LOGIN_URL, q.SLIDER_OPEN_URL),
            timeout=20,
        ).json()
        raw_small = base64.b64decode(captcha["smallImage"])
        state["secret"] = raw_small[-16:].decode("ascii")
        _pending_logins[token] = state
        return {
            "token": token,
            "requires_slider": True,
            "big_image": captcha["bigImage"],
            "small_image": base64.b64encode(raw_small[:-16]).decode("ascii"),
            "username": request.username,
        }

    client = _complete_manual_login(state)
    global _client, _username, _login_password
    _client, _username, _login_password = client, request.username, request.password
    return {"requires_slider": False, "username": request.username}


@app.post("/api/auth/login/slider")
def login_slider(request: SliderVerifyRequest) -> dict[str, str]:
    state = _pending_logins.pop(request.token, None)
    if not state or time.time() - state.get("created", time.time()) > 300:
        raise HTTPException(status_code=410, detail="验证码已过期，请重新开始登录")
    client = _complete_manual_login(state, request.move_length, request.tracks)
    global _client, _username, _login_password
    _client, _username, _login_password = client, state["username"], state["password"]
    return {"username": _username, "name": client.name or _username}


@app.post("/api/auth/logout")
def logout() -> dict[str, bool]:
    global _client, _username, _login_password
    _client = None
    _username = ""
    _login_password = ""
    return {"ok": True}


@app.get("/api/library/classrooms")
def classrooms() -> dict[str, int]:
    return QFNULibraryClient.classrooms()


@app.get("/api/library/segments")
def segments(classroom: str, target_date: str | None = None) -> list[dict]:
    try:
        return _with_relogin(lambda client: client.segments(classroom, target_date))
    except LibraryError as exc:
        _raise_library_http_error(exc)


@app.get("/api/library/seats")
def seats(
    classroom: str,
    target_date: str | None = None,
    start_time: str = "08:00",
    end_time: str = "22:00",
    segment: str | None = None,
) -> list[dict]:
    try:
        return _with_relogin(
            lambda client: client.available_seats(
                classroom, target_date, start_time, end_time, segment
            )
        )
    except LibraryError as exc:
        _raise_library_http_error(exc)


@app.get("/api/library/seat-map")
def seat_map(
    classroom: str,
    target_date: str | None = None,
    start_time: str = "08:00",
    end_time: str = "22:00",
    segment: str | None = None,
) -> list[dict]:
    try:
        return _with_relogin(
            lambda client: client.seat_map(
                classroom, target_date, start_time, end_time, segment
            )
        )
    except LibraryError as exc:
        _raise_library_http_error(exc)


@app.get("/api/library/reservations")
def reservations() -> list[dict]:
    try:
        return _with_relogin(lambda client: client.reservations())
    except LibraryError as exc:
        _raise_library_http_error(exc)


@app.post("/api/library/reserve")
def reserve(request: ReserveRequest) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(status_code=400, detail="预约需要 confirm=true")
    try:
        return _with_relogin(
            lambda client: client.reserve(request.seat_id, request.segment, confirm=True)
        )
    except LibraryError as exc:
        _raise_library_http_error(exc)


@app.post("/api/library/cancel")
def cancel(request: ActionRequest) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(status_code=400, detail="取消预约需要 confirm=true")
    if not request.reservation_id:
        raise HTTPException(status_code=400, detail="取消预约需要 reservation_id")
    try:
        return _with_relogin(
            lambda client: client.cancel(request.reservation_id, confirm=True)
        )
    except LibraryError as exc:
        _raise_library_http_error(exc)


@app.post("/api/library/check-in")
def check_in(request: ActionRequest) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(status_code=400, detail="签到需要 confirm=true")
    try:
        return _with_relogin(lambda client: client.check_in(confirm=True))
    except LibraryError as exc:
        _raise_library_http_error(exc)


@app.post("/api/library/check-out")
def check_out(request: ActionRequest) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(status_code=400, detail="签退需要 confirm=true")
    try:
        return _with_relogin(
            lambda client: client.checkout(request.reservation_id, confirm=True)
        )
    except LibraryError as exc:
        _raise_library_http_error(exc)


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
    if config.enabled and config.reservation_enabled:
        if not config.reservation_classroom.strip() or not config.reservation_seat_id.strip() or not config.reservation_segment.strip():
            raise HTTPException(status_code=400, detail="启用定时预约需要先选择空间、座位和时段")
    with _state_lock:
        _config = config
        _run_keys.clear()
        try:
            _config_path.write_text(
                json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"定时任务保存失败：{exc}") from exc
        return AutomationStatus(
            config=_config.model_copy(),
            running=_config.enabled and _client is not None,
            **_status,
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=False)
