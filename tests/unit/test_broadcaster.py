from __future__ import annotations

import asyncio

from scalping.api.broadcast import Broadcaster


async def test_subscriber_receives_published_message():
    b = Broadcaster()
    q = b.subscribe("scanner")
    await b.publish("scanner", {"type": "delta", "seq": 1})
    msg = await asyncio.wait_for(q.get(), timeout=1)
    assert msg == {"type": "delta", "seq": 1}


async def test_multiple_subscribers_all_receive():
    b = Broadcaster()
    q1 = b.subscribe("scanner")
    q2 = b.subscribe("scanner")
    await b.publish("scanner", {"x": 1})
    assert await q1.get() == {"x": 1}
    assert await q2.get() == {"x": 1}


async def test_channels_are_independent():
    b = Broadcaster()
    scanner_q = b.subscribe("scanner")
    system_q = b.subscribe("system")
    await b.publish("scanner", {"x": 1})
    assert scanner_q.qsize() == 1
    assert system_q.qsize() == 0


async def test_unsubscribe_stops_delivery():
    b = Broadcaster()
    q = b.subscribe("scanner")
    b.unsubscribe("scanner", q)
    await b.publish("scanner", {"x": 1})
    assert q.qsize() == 0


async def test_publish_to_channel_with_no_subscribers_is_noop():
    b = Broadcaster()
    await b.publish("nobody-listening", {"x": 1})  # must not raise
