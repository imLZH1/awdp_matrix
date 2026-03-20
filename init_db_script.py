import asyncio
from backend.core.database import engine
from backend.models.models import Base
from backend.core.security import get_password_hash
from backend.core.database import AsyncSessionLocal
from backend.models.models import User, GameConfig

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        
    async with AsyncSessionLocal() as db:
        # Create admin user
        admin = User(
            username="admin",
            password=get_password_hash("admin"),
            is_admin=True
        )
        db.add(admin)
        
        # Create initial game config
        config = GameConfig(
            name="AWDP Matrix",
            status="pending",
            game_mode="awdp"
        )
        db.add(config)
        await db.commit()
        print("Database initialized successfully!")

if __name__ == "__main__":
    asyncio.run(init_db())
