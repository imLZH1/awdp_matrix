import asyncio
import os
import sys

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.database import AsyncSessionLocal, engine, Base
from backend.core.security import get_password_hash
from backend.models import models
from sqlalchemy import select

async def init_test_data():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # Check if user already exists
        result = await db.execute(select(models.User).where(models.User.username == "test"))
        existing_user = result.scalars().first()
        
        # 2.1 Create Admin User
        admin_user = models.User(
            username="admin",
            password=get_password_hash("admin"),
            is_admin=True,
            team_id=None
        )
        db.add_all([admin_user,])

        await db.commit()

if __name__ == "__main__":
    asyncio.run(init_test_data())
