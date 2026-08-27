from __future__ import annotations

import argparse
import base64
from datetime import date as date_type
from datetime import datetime, timedelta
import getpass
import io
import json
import math
import os
import re
import secrets
import time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

import numpy as np
from PIL import Image
import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7


LOGIN_URL = "https://ids.qfnu.edu.cn/authserver/login"
AES_CHARS = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"
SLIDER_OPEN_URL = "/authserver/common/openSliderCaptcha.htl"
SLIDER_VERIFY_URL = "/authserver/common/verifySliderCaptcha.htl"
LIBRARY_BASE_URL = "http://libyy.qfnu.edu.cn"
LIBRARY_CAS_SERVICE = f"{LIBRARY_BASE_URL}/api/cas/cas"

# 接口字段和区域映射参考 qfnu-library-book（CC BY-NC 4.0）。
LIBRARY_CLASSROOMS = {
    "西校区图书馆-二层自习室": 45,
    "西校区图书馆-三层自习室": 38,
    "西校区图书馆-四层自习室": 39,
    "西校区图书馆-五层自习室": 40,
    "西校区东辅楼-二层自习室": 41,
    "西校区东辅楼-三层自习室": 42,
    "东校区图书馆-三层电子阅览室": 21,
    "东校区图书馆-三层自习室01": 22,
    "东校区图书馆-三层自习室02": 23,
    "东校区图书馆-四层中文现刊室": 24,
    "综合楼-801自习室": 16,
    "综合楼-803自习室": 17,
    "综合楼-804自习室": 18,
    "综合楼-805自习室": 19,
    "综合楼-806自习室": 20,
    "行政楼-四层东区自习室": 13,
    "行政楼-四层中区自习室": 14,
    "行政楼-四层西区自习室": 15,
    "电视台楼-二层自习室": 12,
}


class LibraryError(RuntimeError):
    pass


class LibrarySessionExpired(LibraryError):
    """Raised when the library API no longer accepts the current session."""


def _library_date(value: str | None) -> str:
    if not value or value == "tomorrow":
        result = datetime.now().date() + timedelta(days=1)
    elif value == "today":
        result = datetime.now().date()
    else:
        try:
            result = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise LibraryError("日期必须是 today、tomorrow 或 YYYY-MM-DD") from exc
    return result.isoformat()


def _library_encrypt(text: str, target_date: str | None = None) -> str:
    """Encrypt library reservation payloads with the site's daily AES key."""
    day = target_date or datetime.now().strftime("%Y%m%d")
    key = (day + day[::-1]).encode("ascii")
    iv = b"ZZWBKJ_ZHIHUAWEI"
    padder = PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(text.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()


class QFNULibraryClient:
    """Client for the QFNU library seat APIs used by the referenced project."""

    def __init__(self, session: requests.Session, bearer_token: str, name: str = ""):
        self.session = session
        self.name = name
        self.bearer_token = (
            bearer_token if bearer_token.lower().startswith("bearer") else f"bearer{bearer_token}"
        )
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": f"{LIBRARY_BASE_URL}",
                "Referer": f"{LIBRARY_BASE_URL}/h5/index.html",
                "lang": "zh",
            }
        )

    @classmethod
    def from_login_session(cls, session: requests.Session) -> "QFNULibraryClient":
        location = getattr(session, "qfnu_login_location", "")
        if location:
            session.get(
                urljoin(LOGIN_URL, location),
                allow_redirects=False,
                timeout=20,
            )
        cas_response = session.get(LIBRARY_CAS_SERVICE, allow_redirects=False, timeout=20)
        location = cas_response.headers.get("Location", "")
        match = re.search(r"(?:[?&#]|^)(?:ticket|cas)=([A-Za-z0-9_-]+)", location)
        cas_token = match.group(1) if match else location.rstrip("/").split("/")[-1]
        if not cas_token:
            raise LibraryError("未获取到图书馆 CAS 凭证")
        response = session.post(
            f"{LIBRARY_BASE_URL}/api/cas/user",
            json={"cas": cas_token},
            timeout=20,
        )
        response.raise_for_status()
        try:
            payload = response.json()
            member = payload["member"]
            token = member["token"]
            return cls(session, token, member.get("name", ""))
        except (ValueError, KeyError, TypeError) as exc:
            raise LibraryError("图书馆 CAS 凭证交换失败") from exc

    @staticmethod
    def classrooms() -> dict[str, int]:
        return dict(LIBRARY_CLASSROOMS)

    def _classroom_id(self, classroom: str) -> int:
        try:
            return LIBRARY_CLASSROOMS[classroom]
        except KeyError as exc:
            raise LibraryError(f"未知自习室：{classroom}") from exc

    def _request(self, method: str, path: str, **kwargs) -> dict:
        kwargs.setdefault("timeout", 30)
        response = self.session.request(method, f"{LIBRARY_BASE_URL}{path}", **kwargs)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            if response.status_code in {401, 403}:
                raise LibrarySessionExpired("图书馆会话已失效，请重新登录") from exc
            raise
        try:
            payload = response.json()
        except ValueError as exc:
            raise LibraryError(f"图书馆接口返回了非 JSON 响应：{path}") from exc
        if isinstance(payload, dict) and payload.get("msg") == "您尚未登录":
            raise LibrarySessionExpired("图书馆会话已失效，请重新登录")
        if isinstance(payload, dict) and payload.get("code") not in (None, 1):
            message = payload.get("msg") or payload.get("message") or "图书馆接口返回失败"
            raise LibraryError(f"{message}（code={payload.get('code')}）")
        return payload

    def segments(self, classroom: str, target_date: str | None = None) -> list[dict]:
        day = _library_date(target_date)
        payload = self._request(
            "POST", "/api/Seat/date", json={"build_id": self._classroom_id(classroom)}
        )
        for item in payload.get("data", []):
            if item.get("day") == day:
                return item.get("times", [])
        return []

    def available_seats(
        self,
        classroom: str,
        target_date: str | None = None,
        start_time: str = "08:00",
        end_time: str = "22:00",
        segment: str | None = None,
    ) -> list[dict]:
        day = _library_date(target_date)
        segment = segment or ((self.segments(classroom, day) or [{}])[0].get("id"))
        if not segment:
            raise LibraryError(f"{classroom} 在 {day} 没有可用时段")
        return [seat for seat in self.seat_map(classroom, day, start_time, end_time, segment) if seat["status"] == "空闲"]

    def seat_map(
        self,
        classroom: str,
        target_date: str | None = None,
        start_time: str = "08:00",
        end_time: str = "22:00",
        segment: str | None = None,
    ) -> list[dict]:
        """Return every seat and its state, matching the official H5 page."""
        day = _library_date(target_date)
        segment = segment or ((self.segments(classroom, day) or [{}])[0].get("id"))
        if not segment:
            raise LibraryError(f"{classroom} 在 {day} 没有可用时段")
        payload = self._request(
            "POST",
            "/api/Seat/seat",
            json={
                "area": self._classroom_id(classroom),
                "segment": segment,
                "day": day,
                "startTime": start_time,
                "endTime": end_time,
            },
        )
        result = []
        for seat in payload.get("data", []):
            status = seat.get("status_name") or seat.get("statusName") or seat.get("status") or "未知"
            result.append(
                {
                    "id": seat.get("id"),
                    "no": seat.get("no") or seat.get("name"),
                    "name": seat.get("name") or seat.get("no"),
                    "status": status,
                    "status_code": seat.get("status"),
                    "area": seat.get("area") or self._classroom_id(classroom),
                    "area_name": seat.get("area_name") or seat.get("areaName") or classroom,
                    "point_x": seat.get("point_x"),
                    "point_y": seat.get("point_y"),
                }
            )
        return result

    def reservations(self) -> list[dict]:
        payload = self._request(
            "POST",
            "/api/Member/seat",
            json={"page": 1, "limit": 100, "authorization": self.bearer_token},
            headers={"Authorization": self.bearer_token},
        )
        data = payload.get("data", {})
        return data.get("data", []) if isinstance(data, dict) else []

    def reserve(self, seat_id: str, segment: str, *, confirm: bool = False) -> dict:
        if not confirm:
            raise LibraryError("预约会产生真实外部操作，请显式传入 confirm=True")
        body = json.dumps({"seat_id": str(seat_id), "segment": str(segment)}, separators=(",", ":"))
        return self._request(
            "POST",
            "/api/Seat/confirm",
            json={"aesjson": _library_encrypt(body)},
            headers={"Authorization": self.bearer_token},
        )

    def cancel(self, reservation_id: str, *, confirm: bool = False) -> dict:
        if not confirm:
            raise LibraryError("取消预约会产生真实外部操作，请显式传入 confirm=True")
        return self._request(
            "POST",
            "/api/Space/cancel",
            json={"id": str(reservation_id), "authorization": self.bearer_token},
            headers={"Authorization": self.bearer_token},
        )

    def checkout(self, reservation_id: str | None = None, *, confirm: bool = False) -> dict:
        if not confirm:
            raise LibraryError("签退会产生真实外部操作，请显式传入 confirm=True")
        current = self.reservations()
        item = next(
            (x for x in current if x.get("statusName") == "使用中"), None
        )
        reservation_id = reservation_id or (item or {}).get("id")
        if not reservation_id:
            raise LibraryError("没有找到正在使用的座位")
        return self._request(
            "POST",
            "/api/Space/checkout",
            json={"id": str(reservation_id), "authorization": self.bearer_token},
            headers={"Authorization": self.bearer_token},
        )

    def check_in(self, *, confirm: bool = False) -> dict:
        if not confirm:
            raise LibraryError(
                "签到可能违反图书馆现场使用规则；如确认学校允许，请显式传入 confirm=True"
            )
        body = _library_encrypt('{"method":"checkin"}')
        return self._request(
            "POST",
            "/api/Seat/touch_qr_books",
            json={"aesjson": body, "authorization": self.bearer_token},
            headers={"Authorization": self.bearer_token},
        )


class LoginPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_password_form = False
        self.form_action = ""
        self.fields: dict[str, str] = {}
        self.has_password_form = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "pwdFromId":
            self.in_password_form = True
            self.has_password_form = True
            self.form_action = attributes.get("action") or ""
        elif self.in_password_form and tag == "input":
            name = attributes.get("name")
            element_id = attributes.get("id")
            value = attributes.get("value") or ""
            if name:
                self.fields[name] = value
            if element_id == "pwdEncryptSalt":
                self.fields["pwdEncryptSalt"] = value

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self.in_password_form:
            self.in_password_form = False


class LoginErrorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.capture_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.capture_depth:
            self.capture_depth += 1
            return
        attributes = dict(attrs)
        if attributes.get("id") in {"showErrorTip", "showWarnTip"}:
            self.capture_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self.capture_depth:
            self.capture_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.capture_depth and data.strip():
            self.parts.append(data.strip())


class QFNULoginError(RuntimeError):
    pass


def _random_string(length: int) -> str:
    return "".join(secrets.choice(AES_CHARS) for _ in range(length))


def encrypt_password(password: str, salt: str) -> str:
    """Match the site's encryptPassword(): AES-CBC + PKCS7 + Base64."""
    key = salt.strip().encode("utf-8")
    if len(key) not in {16, 24, 32}:
        raise QFNULoginError(f"站点返回了无效的密码盐长度：{len(key)}")

    iv = _random_string(16).encode("ascii")
    plaintext = (_random_string(64) + password).encode("utf-8")
    padder = PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(ciphertext).decode("ascii")


def _parse_login_page(html: str) -> LoginPageParser:
    parser = LoginPageParser()
    parser.feed(html)
    return parser


def _extract_error(html: str) -> str:
    parser = LoginErrorParser()
    parser.feed(html)
    if parser.parts:
        return " ".join(parser.parts)

    match = re.search(r"(?:错误|失败|异常)[^<>]{0,100}", unescape(html))
    return match.group(0).strip() if match else ""


def _captcha_required(session: requests.Session, username: str, timeout: float) -> bool:
    response = session.get(
        urljoin(LOGIN_URL, "/authserver/checkNeedCaptcha.htl"),
        params={"username": username},
        headers={"X-Requested-With": "XMLHttpRequest"},
        timeout=timeout,
    )
    response.raise_for_status()
    try:
        value = response.json().get("isNeed")
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes"}
        return bool(value)
    except (ValueError, AttributeError) as exc:
        raise QFNULoginError("无法识别站点的验证码状态响应") from exc


def _find_slider_gap(big_image: bytes, small_image: bytes) -> int:
    """Find the white jigsaw outline in the same scaled coordinate system as the site."""
    try:
        import cv2
    except ImportError as exc:
        raise QFNULoginError("自动滑块验证需要安装 opencv-python") from exc

    small_raw = small_image[:-16]  # The final 16 bytes are the verification key.
    big = Image.open(io.BytesIO(big_image)).convert("RGB")
    small = Image.open(io.BytesIO(small_raw)).convert("RGBA")

    big_pixels = np.asarray(big, dtype=np.uint8)
    small_pixels = np.asarray(small, dtype=np.uint8)
    mask = small_pixels[:, :, 3] > 20
    ys, xs = np.where(mask)
    if len(xs) < 100:
        raise QFNULoginError("验证码拼图图像无有效内容")

    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    piece_mask = mask[y0 : y1 + 1, x0 : x1 + 1].astype(np.uint8)
    # The server's background image contains a bright outline around the gap.
    # Matching the outline, rather than the photograph behind it, avoids false
    # matches from visually similar parts of the image.
    inner = cv2.erode(piece_mask, np.ones((3, 3), np.uint8), iterations=1)
    outline = (piece_mask & ~inner).astype(np.float32)
    luma = (
        0.299 * big_pixels[:, :, 0]
        + 0.587 * big_pixels[:, :, 1]
        + 0.114 * big_pixels[:, :, 2]
    )
    bright = (luma > 180).astype(np.float32)
    bright_scores = cv2.matchTemplate(bright, outline, cv2.TM_CCORR_NORMED)
    edge_image = cv2.Canny(luma.astype(np.uint8), 40, 120).astype(np.float32) / 255
    edge_scores = cv2.matchTemplate(edge_image, outline, cv2.TM_CCORR_NORMED)
    # Ignore the image borders, where page decoration can resemble an edge.
    bright_scores[:, :5] = bright_scores[:, -5:] = -1
    edge_scores[:, :5] = edge_scores[:, -5:] = -1
    _, bright_best, _, bright_location = cv2.minMaxLoc(bright_scores)
    _, edge_best, _, edge_location = cv2.minMaxLoc(edge_scores)
    if bright_best >= 0.35:
        location, best = bright_location, bright_best
    else:
        location, best = edge_location, edge_best
    if best < 0.28:
        raise QFNULoginError("验证码缺口定位置信度过低")
    return round(location[0] * 280 / big.width)


def _slider_tracks(move_length: int) -> list[dict[str, int]]:
    """Create a browser-like, time-stamped drag path for the verifier."""
    tracks = [{"a": 0, "b": 0, "c": 0}]
    steps = max(28, min(70, move_length // 2))
    previous = 0
    for index in range(1, steps + 1):
        progress = index / steps
        eased = 1 - (1 - progress) ** 2
        position = round(move_length * eased)
        if index == steps:
            position = move_length
        if position <= previous:
            continue
        wobble = round(2.0 * math.sin(progress * math.pi * 3.0))
        elapsed = 24 + (index % 4) * 7
        tracks.append({"a": position, "b": wobble, "c": elapsed})
        previous = position
    tracks.append({"a": move_length, "b": 0, "c": 45})
    return tracks


def _solve_slider_captcha(
    session: requests.Session,
    *,
    timeout: float,
    max_attempts: int = 3,
) -> None:
    for attempt in range(1, max_attempts + 1):
        response = session.get(urljoin(LOGIN_URL, SLIDER_OPEN_URL), timeout=timeout)
        response.raise_for_status()
        try:
            payload = response.json()
            big_image = base64.b64decode(payload["bigImage"])
            small_image = base64.b64decode(payload["smallImage"])
            secret = small_image[-16:].decode("ascii")
        except (KeyError, ValueError, UnicodeDecodeError) as exc:
            raise QFNULoginError("站点返回的滑块验证码格式无效") from exc

        estimated_move = _find_slider_gap(big_image, small_image)
        # JPEG scaling and the browser's 278px canvas introduce a one-pixel
        # rounding difference. Try a small neighborhood on this same puzzle,
        # rather than refreshing it for every candidate.
        offsets = [0]
        for delta in range(1, 9):
            offsets.extend((-delta, delta))
        for offset in offsets:
            move_length = max(1, estimated_move + offset)
            body = {
                "canvasLength": 280,
                "moveLength": move_length,
                "tracks": _slider_tracks(move_length),
            }
            sign = encrypt_password(
                json.dumps(body, ensure_ascii=False, separators=(",", ":")),
                secret,
            )
            verify = session.post(
                urljoin(LOGIN_URL, SLIDER_VERIFY_URL),
                data={"sign": sign},
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": LOGIN_URL,
                },
                timeout=timeout,
            )
            verify.raise_for_status()
            try:
                if verify.json().get("errorCode") == 1:
                    return
            except ValueError:
                pass
        if attempt < max_attempts:
            time.sleep(0.4)
    raise QFNULoginError("滑块验证码自动验证失败，已停止本次登录，请稍后重试")


def login(
    username: str,
    password: str,
    *,
    service: str | None = None,
    timeout: float = 20,
    follow_redirects: bool = True,
) -> requests.Session:
    """Log in and return the authenticated requests.Session."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    )

    params = {"service": service} if service else None
    page = session.get(LOGIN_URL, params=params, timeout=timeout)
    if page.status_code >= 400:
        detail = _extract_error(page.text) or page.reason or "登录页请求被拒绝"
        raise QFNULoginError(f"登录页请求失败（HTTP {page.status_code}）：{detail}")
    parsed = _parse_login_page(page.text)
    salt = parsed.fields.pop("pwdEncryptSalt", "")
    if not parsed.has_password_form or not salt:
        raise QFNULoginError("登录页结构已变化，未找到账号密码表单或加密盐")

    if _captcha_required(session, username, timeout):
        _solve_slider_captcha(session, timeout=timeout)

    payload = {
        name: value
        for name, value in parsed.fields.items()
        if name not in {"passwordText", "password"}
    }
    payload.update(
        {
            "username": username,
            "password": encrypt_password(password, salt),
            "_eventId": payload.get("_eventId", "submit"),
            "cllt": payload.get("cllt", "userNameLogin"),
            "dllt": payload.get("dllt", "generalLogin"),
        }
    )

    action = urljoin(page.url, parsed.form_action or LOGIN_URL)
    if service:
        action = f"{action}{'&' if '?' in action else '?'}{urlencode({'service': service})}"
    response = session.post(
        action,
        data=payload,
        headers={"Referer": page.url},
        timeout=timeout,
        allow_redirects=follow_redirects,
    )
    session.qfnu_login_location = response.headers.get("Location", "")
    if response.status_code >= 400:
        detail = _extract_error(response.text) or response.reason or "服务器未返回具体原因"
        raise QFNULoginError(
            f"登录提交失败（HTTP {response.status_code}）：{detail}。"
            "请确认账号密码、滑块验证和账号状态。"
        )

    result_page = _parse_login_page(response.text)
    path = urlparse(response.url).path.rstrip("/")
    still_on_login = result_page.has_password_form and path.endswith("/authserver/login")
    if still_on_login:
        detail = _extract_error(response.text) or "账号、密码或登录状态未通过校验"
        raise QFNULoginError(f"登录失败：{detail}")

    return session


def library_login(
    username: str,
    password: str,
    *,
    timeout: float = 20,
) -> QFNULibraryClient:
    """Log in through IDS and exchange the CAS ticket for a library token."""
    session = login(
        username,
        password,
        service=LIBRARY_CAS_SERVICE,
        timeout=timeout,
        follow_redirects=False,
    )
    return QFNULibraryClient.from_login_session(session)


def save_cookies(session: requests.Session, path: Path) -> None:
    cookies = [
        {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
            "secure": cookie.secure,
            "expires": cookie.expires,
        }
        for cookie in session.cookies
    ]
    path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="曲阜师范大学统一身份认证与图书馆座位工具"
    )
    parser.add_argument(
        "--action",
        choices=(
            "login",
            "classrooms",
            "segments",
            "seats",
            "reservations",
            "reserve",
            "cancel",
            "check-in",
            "check-out",
        ),
        default="login",
        help="默认 login；图书馆操作需要先完成 IDS/CAS 登录",
    )
    parser.add_argument("--username", default=os.getenv("QFNU_USERNAME"))
    parser.add_argument("--service", default=os.getenv("QFNU_SERVICE"))
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--save-cookies", type=Path)
    parser.add_argument("--classroom", help="自习室名称")
    parser.add_argument("--date", help="today、tomorrow 或 YYYY-MM-DD，默认 tomorrow")
    parser.add_argument("--start-time", default="08:00")
    parser.add_argument("--end-time", default="22:00")
    parser.add_argument("--segment", help="预约时段 ID")
    parser.add_argument("--seat-id", help="预约使用的座位 ID")
    parser.add_argument("--reservation-id", help="取消/签退使用的预约记录 ID")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="确认执行预约、取消、签到或签退等真实写操作",
    )
    args = parser.parse_args()

    username = args.username or input("统一身份认证账号：").strip()
    if not username:
        print("[失败] 账号不能为空")
        return 1
    password = os.getenv("QFNU_PASSWORD") or getpass.getpass("统一身份认证密码：")
    try:
        if args.action == "login":
            session = login(
                username,
                password,
                service=args.service,
                timeout=args.timeout,
            )
            print(f"[成功] 已登录账号 {username}，当前 Cookie 数：{len(session.cookies)}")
            if args.save_cookies:
                save_cookies(session, args.save_cookies)
                print(f"Cookie 已保存到：{args.save_cookies.resolve()}")
            try:
                input("登录会话保留在内存中，按 Enter 退出... ")
            except (EOFError, KeyboardInterrupt):
                pass
            return 0

        write_actions = {"reserve", "cancel", "check-in", "check-out"}
        if args.action in write_actions and not args.confirm:
            raise LibraryError(
                f"{args.action} 会改变图书馆状态，请重新运行并添加 --confirm"
            )
        client = library_login(username, password, timeout=args.timeout)

        if args.action == "classrooms":
            result = client.classrooms()
        elif args.action == "segments":
            if not args.classroom:
                raise LibraryError("segments 需要 --classroom")
            result = client.segments(args.classroom, args.date)
        elif args.action == "seats":
            if not args.classroom:
                raise LibraryError("seats 需要 --classroom")
            result = client.available_seats(
                args.classroom,
                args.date,
                args.start_time,
                args.end_time,
                args.segment,
            )
        elif args.action == "reservations":
            result = client.reservations()
        elif args.action == "reserve":
            if not args.seat_id or not args.classroom:
                raise LibraryError("reserve 需要 --classroom 和 --seat-id")
            segment = args.segment
            if not segment:
                times = client.segments(args.classroom, args.date)
                segment = (times[0] if times else {}).get("id")
            if not segment:
                raise LibraryError("reserve 未找到可用时段，请指定 --segment")
            result = client.reserve(args.seat_id, segment, confirm=True)
        elif args.action == "cancel":
            if not args.reservation_id:
                raise LibraryError("cancel 需要 --reservation-id")
            result = client.cancel(args.reservation_id, confirm=True)
        elif args.action == "check-in":
            result = client.check_in(confirm=True)
        else:
            result = client.checkout(args.reservation_id, confirm=True)

        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except (requests.RequestException, QFNULoginError, LibraryError) as exc:
        print(f"[失败] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
