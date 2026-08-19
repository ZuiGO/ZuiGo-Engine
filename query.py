import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def run():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client.rankengine
    doc = await db.action_items.find_one()
    if doc:
        print("action_items doc:")
        print("content_type:", doc.get("content_type"))
        print("identified_issues:", doc.get("identified_issues"))
    
asyncio.run(run())
