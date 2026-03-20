import asyncio
from backend.core.database import AsyncSessionLocal
from backend.models import models
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as db:
        team_res = await db.execute(select(models.Team))
        teams = team_res.scalars().all()
        chal_res = await db.execute(select(models.Challenge))
        chal = chal_res.scalars().first()
        
        # Add team 4 as rank 1 solve in round 1
        team4 = next(t for t in teams if t.name == "team4")
        log1 = models.ScoreLog(team_id=team4.id, challenge_id=chal.id, round_num=1, score_change=0.0, reason="成功攻破自有靶机 (Rank: 1)", log_type="attack_success")
        db.add(log1)
        
        # Add team 1 as rank 2 solve in round 1
        team1 = next(t for t in teams if t.name == "team1")
        log2 = models.ScoreLog(team_id=team1.id, challenge_id=chal.id, round_num=1, score_change=0.0, reason="成功攻破自有靶机 (Rank: 2)", log_type="attack_success")
        db.add(log2)

        # Add team 2 as rank 3 solve in round 1
        team2 = next(t for t in teams if t.name == "team2")
        log3 = models.ScoreLog(team_id=team2.id, challenge_id=chal.id, round_num=1, score_change=0.0, reason="成功攻破自有靶机 (Rank: 3)", log_type="attack_success")
        db.add(log3)

        # Add team 3 as rank 4 solve in round 1
        team3 = next(t for t in teams if t.name == "team3")
        log4 = models.ScoreLog(team_id=team3.id, challenge_id=chal.id, round_num=1, score_change=0.0, reason="成功攻破自有靶机 (Rank: 4)", log_type="attack_success")
        db.add(log4)

        await db.commit()

asyncio.run(main())
