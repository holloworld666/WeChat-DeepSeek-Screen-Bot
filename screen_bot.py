from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any
from ctypes import wintypes

import pyperclip
import uiautomation as auto
import win32gui


ROOT = Path(__file__).resolve().parent
LOG_FILE = ROOT / "wechat-screen-bot.log"
WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
MOD_CONTROL = 0x0002
VK_SPACE = 0x20
HOTKEY_ID = 0x5742


def setup_logging() -> None:
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        config = json.load(handle)
    groups = config.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("config.json 至少需要一个群名。")
    nickname = config.get("bot_nickname")
    if not isinstance(nickname, str) or not nickname.strip():
        raise ValueError("config.json 缺少 bot_nickname，请在启动器中重新选择首次配置。")
    api_key = os.environ.get("AI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("没有读取到 DeepSeek API Key。")
    if len(api_key) < 20 or any(character.isspace() for character in api_key):
        raise ValueError(
            "保存的 DeepSeek API Key 格式无效；Key 应完整且不包含空白字符。"
            "请在启动器中选择“首次配置”重新填写真实 Key。"
        )
    return config


def visible_windows() -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []

    def collect(hwnd: int, _extra: object) -> None:
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd).strip()
            if title:
                result.append((hwnd, title))

    win32gui.EnumWindows(collect, None)
    return result


def find_group_window(group: str) -> int:
    exact = [(hwnd, title) for hwnd, title in visible_windows() if title == group]
    if len(exact) == 1:
        return exact[0][0]
    partial = [
        (hwnd, title)
        for hwnd, title in visible_windows()
        if group in title and title != "微信"
    ]
    if len(partial) == 1:
        return partial[0][0]
    if not exact and not partial:
        raise RuntimeError(
            f"没有找到群聊独立窗口：{group}。请先在微信聊天列表中双击该群，"
            "确认弹出标题为群名的独立窗口，再启动机器人。"
        )
    raise RuntimeError(f"找到多个可能的群窗口：{group}，请关闭重复窗口后重试。")


def walk(root, max_depth: int = 10):
    try:
        yield from auto.WalkControl(root, includeTop=True, maxDepth=max_depth)
    except Exception:
        return


def control_text(control) -> str:
    try:
        return (control.Name or "").strip()
    except Exception:
        return ""


def find_message_list(root):
    known_ids = ("chat_message_list", "message_list", "msg_list")
    for automation_id in known_ids:
        try:
            candidate = root.ListControl(AutomationId=automation_id)
            if candidate.Exists(0, 0):
                return candidate
        except Exception:
            pass

    candidates = []
    try:
        root_rect = root.BoundingRectangle
        for control, depth in walk(root, 9):
            if getattr(control, "ControlTypeName", "") != "ListControl":
                continue
            rect = control.BoundingRectangle
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width < 250 or height < 200:
                continue
            if rect.top > root_rect.top + root_rect.height() * 0.65:
                continue
            candidates.append((width * height - depth * 1000, control))
    except Exception:
        pass
    if not candidates:
        raise RuntimeError("已找到群窗口，但没有识别到消息列表控件。")
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def read_visible_messages(message_list) -> list[str]:
    messages: list[str] = []
    seen_controls: set[int] = set()
    for control, _depth in walk(message_list, 5):
        try:
            control_type = control.ControlTypeName
            if control_type not in {"ListItemControl", "TextControl", "ButtonControl"}:
                continue
            text = control_text(control)
            if not text or text in {"查看更多消息", "以下为新消息"}:
                continue
            # Prefer outer message items and avoid repeating their nested text.
            native_key = hash((text, control_type, str(control.BoundingRectangle)))
            if native_key in seen_controls:
                continue
            seen_controls.add(native_key)
            if messages and (text == messages[-1] or text in messages[-1]):
                continue
            messages.append(text)
        except Exception:
            continue
    return messages[-30:]


def new_suffix(previous: list[str], current: list[str]) -> list[str]:
    limit = min(len(previous), len(current))
    for overlap in range(limit, 0, -1):
        if previous[-overlap:] == current[:overlap]:
            return current[overlap:]
    # A completely different tree usually means a temporary UI refresh. Avoid
    # treating the entire visible history as new messages.
    return [] if previous else current


def find_chat_input(root):
    candidates = []
    root_rect = root.BoundingRectangle
    for control, depth in walk(root, 10):
        try:
            if control.ControlTypeName not in {"EditControl", "DocumentControl"}:
                continue
            rect = control.BoundingRectangle
            width = rect.right - rect.left
            if width < 180 or rect.top < root_rect.top + root_rect.height() * 0.5:
                continue
            candidates.append((width - depth * 5, control))
        except Exception:
            continue
    if not candidates:
        raise RuntimeError("没有识别到群聊输入框。")
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


class DeepSeekClient:
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.url = settings["base_url"].rstrip("/") + "/v1/chat/completions"

    def chat(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.settings.get("model", "deepseek-v4-flash"),
            "messages": [
                {
                    "role": "system",
                    "content": self.settings.get(
                        "system_prompt", "你是微信群里的智能助手，回复自然、准确、简洁。"
                    ),
                },
                *messages,
            ],
            "temperature": float(self.settings.get("temperature", 0.7)),
            "max_tokens": int(self.settings.get("max_tokens", 500)),
            "thinking": {
                "type": "enabled"
                if self.settings.get("enable_thinking", False)
                else "disabled"
            },
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {os.environ['AI_API_KEY']}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=float(self.settings.get("timeout", 60))
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek HTTP {exc.code}: {body}") from exc
        return data["choices"][0]["message"]["content"].strip()


class GroupSession:
    def __init__(
        self,
        group: str,
        hwnd: int,
        nickname: str,
        wake_words: list[str],
        context_size: int,
    ):
        self.group = group
        self.hwnd = hwnd
        self.nickname = nickname
        self.wake_words = [word.strip() for word in wake_words if word.strip()]
        self.root = auto.ControlFromHandle(hwnd)
        self.message_list = find_message_list(self.root)
        self.previous = read_visible_messages(self.message_list)
        self.context: deque[dict[str, str]] = deque(maxlen=context_size)
        self.sent_recently: deque[str] = deque(maxlen=20)
        self.last_message = self.previous[-1] if self.previous else ""
        self.last_message_at = time.time() if self.last_message else 0.0
        logging.info("已绑定群窗口：%s，当前可见消息作为基线：%s 条", group, len(self.previous))

    def poll(self) -> list[str]:
        current = read_visible_messages(self.message_list)
        added = new_suffix(self.previous, current)
        self.previous = current
        for message in added:
            if message not in self.sent_recently:
                self.last_message = message
                self.last_message_at = time.time()
        return added

    def should_reply(self, text: str) -> bool:
        if text in self.sent_recently:
            return False
        return f"@{self.nickname}" in text or any(
            word in text for word in self.wake_words
        )

    def clean_question(self, text: str) -> str:
        cleaned = text.replace(f"@{self.nickname}\u2005", "").replace(
            f"@{self.nickname}", ""
        ).strip()
        for word in self.wake_words:
            cleaned = cleaned.replace(word, " ")
        return " ".join(cleaned.split())

    def send(self, text: str) -> None:
        edit = find_chat_input(self.root)
        pyperclip.copy(text)
        edit.Click(simulateMove=False)
        edit.SendKeys("{Ctrl}v", waitTime=0.1)
        edit.SendKeys("{Enter}", waitTime=0.1)
        self.sent_recently.append(text)


def start_ctrl_space_hotkey(
    triggered: threading.Event, stop_event: threading.Event
) -> threading.Thread:
    """Register Ctrl+Space globally and signal the main bot loop when pressed."""
    ready = threading.Event()
    status: dict[str, Any] = {}

    def listen() -> None:
        user32 = ctypes.windll.user32
        registered = bool(
            user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL, VK_SPACE)
        )
        status["registered"] = registered
        ready.set()
        if not registered:
            return
        message = wintypes.MSG()
        try:
            while not stop_event.wait(0.03):
                while user32.PeekMessageW(
                    ctypes.byref(message), None, 0, 0, PM_REMOVE
                ):
                    if message.message == WM_HOTKEY and message.wParam == HOTKEY_ID:
                        triggered.set()
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)

    thread = threading.Thread(target=listen, name="ctrl-space-hotkey", daemon=True)
    thread.start()
    ready.wait(2)
    if not status.get("registered"):
        raise RuntimeError(
            "无法注册 Ctrl+空格快捷键，可能已被输入法或其他程序占用。"
        )
    return thread


def reply_to_message(
    session: GroupSession, message: str, client: DeepSeekClient
) -> None:
    question = session.clean_question(message)
    if not question:
        return
    session.context.append({"role": "user", "content": question})
    reply = client.chat(list(session.context))
    session.send(reply)
    session.context.append({"role": "assistant", "content": reply})
    logging.info("已回复群：%s", session.group)


def run(config_path: Path, check_only: bool) -> None:
    config = load_config(config_path)
    sessions = []
    for group in config["groups"]:
        hwnd = find_group_window(group)
        sessions.append(
            GroupSession(
                group,
                hwnd,
                config["bot_nickname"].strip(),
                config.get("wake_words", []),
                int(config.get("context_size", 8)),
            )
        )
    if check_only:
        logging.info("配置、依赖和群聊独立窗口检查通过。")
        return

    client = DeepSeekClient(config["ai"])
    stop_event = threading.Event()
    hotkey_triggered = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    start_ctrl_space_hotkey(hotkey_triggered, stop_event)
    wake_words = config.get("wake_words", [])
    trigger_description = f"@{config['bot_nickname']}"
    if wake_words:
        trigger_description += " 或关键词：" + "、".join(wake_words)
    logging.info("无 wx4py 机器人已启动；触发方式：%s。", trigger_description)
    logging.info("全局快捷键已启用：Ctrl+空格，按下后回复最近一条群消息。")
    while not stop_event.wait(0.2):
        if hotkey_triggered.is_set():
            hotkey_triggered.clear()
            latest = max(sessions, key=lambda item: item.last_message_at)
            if latest.last_message:
                try:
                    logging.info("Ctrl+空格触发，准备回复群：%s", latest.group)
                    reply_to_message(latest, latest.last_message, client)
                except Exception:
                    logging.exception("快捷键回复失败：%s", latest.group)
            else:
                logging.warning("Ctrl+空格已触发，但启动后还没有监听到新消息。")
        for session in sessions:
            try:
                for message in session.poll():
                    if not session.should_reply(message):
                        continue
                    reply_to_message(session, message, client)
            except Exception:
                logging.exception("处理群窗口失败：%s", session.group)


def main() -> int:
    parser = argparse.ArgumentParser(description="微信群屏幕/UIA AI 自动回复机器人")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    setup_logging()
    try:
        run(args.config.resolve(), args.check)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logging.exception("启动失败：%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
