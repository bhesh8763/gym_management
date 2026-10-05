"""Realtime delivery channel for a signed-in user's open browser tab(s).

Connects to ``ws(s)://<host>/ws/messages/?token=<JWT access token>``. The
socket carries server -> client events only (`message.new`, keepalive
pongs) — the send path stays plain HTTPS. Each connection joins the
``ws_user_<id>`` channel-layer group that
:func:`apps.notifications.services.broadcast_to_user` fans out to, so every
open tab of the same user sees new messages live.

Authentication happens once, at handshake time; a missing/expired token is
refused with close code 4401 before the socket is accepted.
"""
import asyncio
import logging
import threading
import weakref
from collections import defaultdict
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

logger = logging.getLogger(__name__)

WS_UNAUTHORIZED = 4401

# ── Live consumer event loops ────────────────────────────────────────────────
# Every WebSocket in the process runs on one event loop (daphne and the dev
# runserver each drive a single loop), tracked here per user. Broadcasts must
# schedule their group_send() ON that loop: a cross-thread asyncio.Queue put
# resolves waiter futures via loop.call_soon(), which does not wake a loop
# blocked in select — delivery would then wait for an unrelated timer/IO
# event (seconds, or until the user interacts). run_coroutine_threadsafe()
# writes to the loop's self-pipe and wakes it immediately.
# WeakSet: a loop cancelled without a clean disconnect disappears on GC.

_user_loops_lock = threading.Lock()
_user_loops: dict = defaultdict(weakref.WeakSet)


def register_user_loop(user_id, loop):
    """Track the event loop serving ``user_id``'s connected tab(s)."""
    with _user_loops_lock:
        _user_loops[user_id].add(loop)


def unregister_user_loop(user_id, loop):
    """Drop ``loop`` when its consumer disconnects."""
    with _user_loops_lock:
        loops = _user_loops.get(user_id)
        if loops is not None:
            loops.discard(loop)
            if not loops:
                _user_loops.pop(user_id, None)


def loops_for_user(user_id):
    """Live (open) loops currently serving ``user_id`` — for broadcasting."""
    with _user_loops_lock:
        return [
            loop for loop in _user_loops.get(user_id, ())
            if not loop.is_closed()
        ]


class MessageConsumer(AsyncJsonWebsocketConsumer):
    """Server-push only: clients may send keepalive pings, nothing else."""

    async def connect(self):
        user = await self._authenticate()
        if user is None:
            await self.close(code=WS_UNAUTHORIZED)
            return
        self.user = user
        self.user_group = f'ws_user_{user.pk}'
        self.user_loop = asyncio.get_running_loop()
        register_user_loop(user.pk, self.user_loop)
        await self.channel_layer.group_add(self.user_group, self.channel_name)
        await self.accept()
        await self.send_json({'type': 'connected', 'user_id': user.pk})

    async def disconnect(self, code):
        if getattr(self, 'user_group', None) is not None:
            await self.channel_layer.group_discard(
                self.user_group, self.channel_name,
            )
        if getattr(self, 'user', None) is not None:
            unregister_user_loop(self.user.pk, asyncio.get_running_loop())

    async def receive_json(self, content):
        # Keepalive pings double as Render free-tier inbound traffic: an open
        # chat sends one every minute, which stops the instance from spinning
        # down and detects stale connections on both sides.
        if isinstance(content, dict) and content.get('type') == 'ping':
            await self.send_json({'type': 'pong'})

    async def message_new(self, event):
        """Channel-layer handler for broadcast_to_user()."""
        await self.send_json(event.get('payload') or {'type': 'message.new'})

    @database_sync_to_async
    def _authenticate(self):
        """Resolve ?token= to an active user, or None when invalid/expired."""
        params = parse_qs(self.scope.get('query_string', b'').decode() or '')
        token = (params.get('token') or [None])[0]
        if not token:
            return None
        try:
            claims = AccessToken(token).payload
            user_id = claims['user_id']
        except (InvalidToken, TokenError, KeyError, TypeError, ValueError):
            return None
        return get_user_model().objects.filter(pk=user_id, is_active=True).first()
