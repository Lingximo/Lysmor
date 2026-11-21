# -*- coding: utf-8 -*-
"""只启动手机中继（8797），不再开眼镜 HUD 的 WebSocket。

2026-11-10 乐奇眼镜退役后，看门狗改用它拉起 8797。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server  # noqa: E402

asyncio.run(server.main_async("0.0.0.0", 8014, enable_hud=False))
