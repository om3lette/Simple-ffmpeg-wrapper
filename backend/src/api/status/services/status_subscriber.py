import asyncio
import json

from collections import defaultdict

from fastapi import WebSocket
from camel_converter import dict_to_camel
from redis.asyncio import Redis

from backend.src.api.common.io.progress_handler import ProgressHandler
from backend.src.app_config import app_config
from backend.src.utils import get_logger_by_filepath

logger = get_logger_by_filepath(__file__)


class StatusSubscriber:
    subscriptions: dict[str, set[WebSocket]] = defaultdict(set)
    # Subscribe to `status:\w{32}`
    sub_pattern: str = ProgressHandler.get_status_key_by_id("") + "?" * 32

    def __init__(self, redis_client: Redis):
        self.sub = redis_client.pubsub()

    def subscribe(self, websocket: WebSocket, rid: str):
        self.subscriptions[rid].add(websocket)

    def unsubscribe(self, websocket: WebSocket, rid: str):
        if rid not in self.subscriptions.keys():
            return
        self.subscriptions[rid].remove(websocket)

    async def broadcast(self):
        await self.sub.psubscribe(self.sub_pattern)
        logger.info("Subscribed to all status channels")

        async for msg in self.sub.listen():
            if msg["type"] != "pmessage":
                continue

            rid: str = msg["channel"].split(":")[1]
            data = json.loads(msg["data"])

            if "status" in data.keys():
                data["type"] = "status"
            else:
                if (
                    app_config.websockets.no_progress_updates
                    and "status" not in data.keys()
                ):
                    continue
                if "cur_stage" in data.keys():
                    data["type"] = "stage"
                elif "pct" in data.keys():
                    data["type"] = "progress"

            data["rid"] = rid
            data = dict_to_camel(data)

            await asyncio.gather(
                *(ws.send_json(data) for ws in self.subscriptions[rid])
            )

            # Status is being passed only if request has finished processing
            # It is safe to unsubscribe all users as no more events are expected
            if data.get("status") is not None:
                del self.subscriptions[rid]

    async def unsub_and_close(self):
        await self.sub.punsubscribe(self.sub_pattern)
        await self.sub.aclose()
        logger.info("Unsubscribed from all status channels, closed connection")
