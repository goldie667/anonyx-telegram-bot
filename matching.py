import time
from sqlalchemy import select
from bot.db import Session, User, blocked_pair

QUEUE = "match:queue"
ACTIVE = "chat:active"
LOCK = "match:lock"

async def leave_queue(store, user_id: int):
    await store.zrem(QUEUE, str(user_id))

async def disconnect(store, user_id: int):
    partner = await store.hget(ACTIVE, str(user_id))
    if partner:
        partner_id = partner.decode() if isinstance(partner, bytes) else str(partner)
        await store.hdel(ACTIVE, str(user_id), partner_id)
        return int(partner_id)
    await leave_queue(store, user_id)
    return None

def compatible(me: User, other: User) -> bool:
    if other.id == me.id or other.is_banned:
        return False
    if me.looking_gender != "any" and other.gender != me.looking_gender:
        return False
    if other.looking_gender != "any" and me.gender != other.looking_gender:
        return False
    if not (me.min_age <= (other.age or 0) <= me.max_age):
        return False
    if not (other.min_age <= (me.age or 0) <= other.max_age):
        return False
    if me.looking_country != "any" and (other.country or "").lower() != me.looking_country.lower():
        return False
    if other.looking_country != "any" and (me.country or "").lower() != other.looking_country.lower():
        return False
    if me.match_interests or other.match_interests:
        a = {x.strip().lower() for x in me.interests.split(",") if x.strip()}
        b = {x.strip().lower() for x in other.interests.split(",") if x.strip()}
        if not a.intersection(b):
            return False
    return True

async def find_partner(store, user_id: int):
    async with store.lock(LOCK, timeout=10, blocking_timeout=5):
        async with Session() as session:
            me = await session.get(User, user_id)
            if not me or me.is_banned:
                return None
            active = await store.hget(ACTIVE, str(user_id))
            if active:
                return int(active)
            candidates = await store.zrange(QUEUE, 0, 99)
            for raw in candidates:
                candidate_id = int(raw)
                if candidate_id == user_id:
                    continue
                other = await session.get(User, candidate_id)
                if not other or not compatible(me, other):
                    continue
                if await blocked_pair(session, user_id, candidate_id):
                    continue
                if await store.hget(ACTIVE, str(candidate_id)):
                    await store.zrem(QUEUE, str(candidate_id))
                    continue
                await store.zrem(QUEUE, str(candidate_id))
                await store.hset(ACTIVE, mapping={str(user_id): str(candidate_id), str(candidate_id): str(user_id)})
                return candidate_id
            await store.zadd(QUEUE, {str(user_id): time.time()})
            return None
