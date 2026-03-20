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
        
        if not existing_user:
            # 1. Create a Team
            team = models.Team(name="星火网络安全队", total_score=0.0)
            db.add(team)
            await db.commit()
            await db.refresh(team)

            # 2. Create a User for the team
            user = models.User(
                username="test",
                password=get_password_hash("test"),
                is_admin=False,
                team_id=team.id
            )
            
            # 2.1 Create Admin User
            admin_user = models.User(
                username="admin",
                password=get_password_hash("admin"),
                is_admin=True,
                team_id=None
            )
            db.add_all([user, admin_user])

            # 3. Create a Challenge
            chal1 = models.Challenge(
                name="Web_SQLi_Login",
                description="该系统存在 SQL 注入漏洞，请在攻击阶段获取 /flag，在防御阶段修补 SQL 注入漏洞。",
                attack_image="awdp/sqli_attack:latest",
                check_image="awdp/sqli_check:latest",
                base_score=500.0,
                initial_defense_count=10
            )
            chal2 = models.Challenge(
                name="Pwn_StackOverflow",
                description="经典的栈溢出漏洞，请获取 Shell 拿 Flag，然后通过 Patch 二进制文件修复溢出。",
                attack_image="test_awdp_pwn1:latest",
                check_image="awdp/pwn_check:latest",
                base_score=500.0,
                initial_defense_count=10
            )
            db.add_all([chal1, chal2])
            await db.commit()
            print("Test data initialized successfully. You can login with username: 'test', password: 'test'")
        else:
            print("Test data already exists.")

if __name__ == "__main__":
    asyncio.run(init_test_data())
