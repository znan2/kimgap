"""
Telegram forwarding bot.

Usage:
  1) Set env vars in .env (or process env):
     - FORWARDER_BOT_TOKEN
     - FORWARDER_SOURCE_CHAT_IDS (comma-separated; messages from these chats are relayed)
     - FORWARDER_CONFIG_PATH (optional; default: data/forwarder_config.json)
  2) Run:
     python forwarder_bot.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

_ROOT = Path(__file__).resolve().parent
_LOG = logging.getLogger("forwarder-bot")


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if (
                len(value) >= 2
                and ((value[0] == "'" and value[-1] == "'") or (value[0] == '"' and value[-1] == '"'))
            ):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


def _parse_csv(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


_load_env_file(Path.cwd() / ".env")
_load_env_file(_ROOT / ".env")

FORWARDER_BOT_TOKEN = os.getenv("FORWARDER_BOT_TOKEN", "").strip()
FORWARDER_SOURCE_CHAT_IDS = set(_parse_csv(os.getenv("FORWARDER_SOURCE_CHAT_IDS", "")))
FORWARDER_ADMIN_CHAT_IDS = set(_parse_csv(os.getenv("FORWARDER_ADMIN_CHAT_IDS", "")))
FORWARDER_CONFIG_PATH = Path(
    os.getenv("FORWARDER_CONFIG_PATH", str(_ROOT / "data" / "forwarder_config.json"))
).resolve()

_CFG_LOCK = asyncio.Lock()
_CFG: dict[str, Any] = {"subscriber_chat_ids": [], "source_chat_ids": sorted(FORWARDER_SOURCE_CHAT_IDS)}


async def _load_config() -> None:
    if not FORWARDER_CONFIG_PATH.is_file():
        return
    try:
        raw = json.loads(FORWARDER_CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            subs = raw.get("subscriber_chat_ids", [])
            if isinstance(subs, list):
                _CFG["subscriber_chat_ids"] = sorted({str(x).strip() for x in subs if str(x).strip()})
            srcs = raw.get("source_chat_ids", [])
            if isinstance(srcs, list):
                _CFG["source_chat_ids"] = sorted({str(x).strip() for x in srcs if str(x).strip()})
    except Exception as e:
        _LOG.warning("forwarder config load failed: %s", e)


async def _save_config() -> None:
    FORWARDER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    FORWARDER_CONFIG_PATH.write_text(
        json.dumps(_CFG, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _is_admin(chat_id: str) -> bool:
    if not FORWARDER_ADMIN_CHAT_IDS:
        return True
    return chat_id in FORWARDER_ADMIN_CHAT_IDS


async def _subscribe(chat_id: str) -> tuple[bool, str]:
    async with _CFG_LOCK:
        current = set(_CFG["subscriber_chat_ids"])
        if chat_id in current:
            return False, "이미 구독된 채팅입니다."
        current.add(chat_id)
        _CFG["subscriber_chat_ids"] = sorted(current)
        await _save_config()
    return True, "이 채팅을 알림 구독에 추가했습니다."


async def _unsubscribe(chat_id: str) -> tuple[bool, str]:
    async with _CFG_LOCK:
        current = set(_CFG["subscriber_chat_ids"])
        if chat_id not in current:
            return False, "현재 구독된 채팅이 아닙니다."
        current.discard(chat_id)
        _CFG["subscriber_chat_ids"] = sorted(current)
        await _save_config()
    return True, "이 채팅을 알림 구독에서 제거했습니다."


async def _status_text() -> str:
    async with _CFG_LOCK:
        subs = list(_CFG["subscriber_chat_ids"])
        source = list(_CFG["source_chat_ids"])
    return (
        "포워딩봇 상태\n"
        f"- source_chat_ids: {', '.join(source) if source else '(없음)'}\n"
        f"- subscriber_chat_ids: {', '.join(subs) if subs else '(없음)'}\n"
        f"- config_path: {FORWARDER_CONFIG_PATH}"
    )


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = str(chat.id)
    ok, msg = await _subscribe(chat_id)
    await update.effective_message.reply_text(msg if ok else f"안내: {msg}")


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = str(chat.id)
    ok, msg = await _unsubscribe(chat_id)
    await update.effective_message.reply_text(msg if ok else f"안내: {msg}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = str(chat.id)
    if not _is_admin(chat_id):
        await update.effective_message.reply_text("권한이 없습니다.")
        return
    await update.effective_message.reply_text(await _status_text(), parse_mode=ParseMode.HTML)


async def cmd_source_here(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = str(chat.id)
    if not _is_admin(chat_id):
        await update.effective_message.reply_text("권한이 없습니다.")
        return
    async with _CFG_LOCK:
        srcs = set(_CFG["source_chat_ids"])
        srcs.add(chat_id)
        _CFG["source_chat_ids"] = sorted(srcs)
        await _save_config()
    await update.effective_message.reply_text("이 채팅을 소스 채팅으로 등록했습니다.")


async def cmd_unsource_here(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    chat_id = str(chat.id)
    if not _is_admin(chat_id):
        await update.effective_message.reply_text("권한이 없습니다.")
        return
    async with _CFG_LOCK:
        srcs = set(_CFG["source_chat_ids"])
        if chat_id not in srcs:
            await update.effective_message.reply_text("현재 소스 채팅이 아닙니다.")
            return
        srcs.discard(chat_id)
        _CFG["source_chat_ids"] = sorted(srcs)
        await _save_config()
    await update.effective_message.reply_text("이 채팅의 소스 등록을 해제했습니다.")


async def _prune_dead_subscriber(chat_id: str) -> None:
    async with _CFG_LOCK:
        current = set(_CFG["subscriber_chat_ids"])
        if chat_id in current:
            current.discard(chat_id)
            _CFG["subscriber_chat_ids"] = sorted(current)
            await _save_config()


async def forward_source_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return
    source_chat_id = str(chat.id)
    async with _CFG_LOCK:
        source_chat_ids = set(_CFG["source_chat_ids"])
        targets = list(_CFG["subscriber_chat_ids"])
    if source_chat_id not in source_chat_ids:
        return

    for target in targets:
        if target == source_chat_id:
            continue
        try:
            await context.bot.forward_message(
                chat_id=target,
                from_chat_id=chat.id,
                message_id=message.message_id,
            )
        except Exception as e:
            _LOG.warning("forward failed source=%s -> target=%s: %s", source_chat_id, target, e)
            err = str(e).lower()
            if "chat not found" in err or "bot was blocked" in err or "forbidden" in err:
                await _prune_dead_subscriber(target)


def main() -> None:
    if not FORWARDER_BOT_TOKEN:
        raise SystemExit("FORWARDER_BOT_TOKEN is required")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    app = Application.builder().token(FORWARDER_BOT_TOKEN).build()
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("source_here", cmd_source_here))
    app.add_handler(CommandHandler("unsource_here", cmd_unsource_here))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, forward_source_message))

    loop = asyncio.get_event_loop()
    loop.run_until_complete(_load_config())
    _LOG.info("forwarder started with %d source chats", len(FORWARDER_SOURCE_CHAT_IDS))
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
