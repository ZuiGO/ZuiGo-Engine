import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def run():
    # just testing syntax
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client.rankengine
    
    action = {"job_id": "123", "source_url": "/logo.png", "issue_key": "img_alt"}
    
    # how to do upsert with update_one
    res = await db.action_items.update_one(
        {"job_id": action["job_id"], "source_url": action["source_url"], "issue_key": action["issue_key"]},
        {"$setOnInsert": action},
        upsert=True
    )
    print("Upserted id:", res.upserted_id)

asyncio.run(run())
