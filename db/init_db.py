import asyncio
from db.database import async_engine
from db import models

async def init_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)

if __name__ == "__main__":
    asyncio.run(init_db())
