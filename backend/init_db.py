import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from backend.models.models import Base, User
from backend.core.security import get_password_hash

DATABASE_URL = "sqlite+aiosqlite:///awdp.db"
engine = create_async_engine(DATABASE_URL, echo=True)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    async with async_session() as session:
        # Check if admin exists
        from sqlalchemy import select
        result = await session.execute(select(User).where(User.username == "admin"))
        admin = result.scalars().first()
        if not admin:
            admin_user = User(
                username="admin",
                password=get_password_hash("admin123"),
                is_admin=True,
                team_id=None
            )
            session.add(admin_user)
            await session.commit()
            print("Admin user created successfully. (admin/admin123)")
        else:
            print("Admin user already exists.")

if __name__ == "__main__":
    asyncio.run(init_db())
