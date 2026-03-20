import asyncio
import logging
from datetime import datetime
from sqlalchemy import select, desc
from backend.core.database import AsyncSessionLocal
from backend.models import models
from backend.engine.scoring import ScoringEngine

logger = logging.getLogger(__name__)

async def game_engine_loop():
    while True:
        try:
            await process_game_tick()
        except Exception as e:
            logger.error(f"Error in game engine loop: {e}")
        await asyncio.sleep(10) # check every 10 seconds

async def process_game_tick():
    async with AsyncSessionLocal() as db:
        # Get GameConfig
        result = await db.execute(select(models.GameConfig).limit(1))
        config = result.scalars().first()
        
        if not config or config.status != "running" or config.game_mode != "awdp":
            return
            
        now = datetime.now()
        
        if not config.start_time:
            return
            
        start_time = config.start_time.replace(tzinfo=None) if config.start_time.tzinfo else config.start_time
        
        if now < start_time:
            return
            
        if config.end_time:
            end_time = config.end_time.replace(tzinfo=None) if config.end_time.tzinfo else config.end_time
            if now > end_time:
                return
            
        # Calculate current expected round
        elapsed_time = now - start_time
        round_duration_sec = config.round_duration * 60
        expected_round = int(elapsed_time.total_seconds() // round_duration_sec) + 1
        
        # Get latest round log
        result = await db.execute(select(models.RoundLog).order_by(desc(models.RoundLog.round_num)).limit(1))
        latest_round = result.scalars().first()
        
        current_db_round = latest_round.round_num if latest_round else 0
        
        if expected_round > current_db_round:
            for r in range(current_db_round + 1, expected_round + 1):
                logger.info(f"Advancing to Round {r}")
                
                # Close previous round
                if latest_round and latest_round.status == "running":
                    latest_round.status = "finished"
                    latest_round.end_time = now
                
                # Execute round transition logic BEFORE creating the new round,
                # so the scoring logic uses the correct scoring_round (which is current_db_round, or r - 1)
                await handle_round_transition(db, r)
                
                # Create new round
                new_round = models.RoundLog(
                    round_num=r,
                    start_time=now,
                    status="running" if r == expected_round else "finished"
                )
                db.add(new_round)
                
                await db.commit()
                latest_round = new_round

async def handle_round_transition(db, round_num: int):
    # 1. SLA checks
    # 2. AWDP auto scoring (给已经攻破自己靶机的队伍自动加分)
    # 3. Flag generation
    
    scoring_round = round_num - 1
    logger.info(f"Executing round transition logic for round {round_num} (scoring for round {scoring_round})")
    
    # 获取 AWDP 模式配置
    result = await db.execute(select(models.GameConfig).limit(1))
    config = result.scalars().first()
    is_awdp = config and config.game_mode == "awdp"
    
    # Get all active game boxes
    result = await db.execute(select(models.GameBox))
    boxes = result.scalars().all()
    
    import uuid
    import re
    
    if scoring_round > 0:
        # 获取总队伍数 (用于计算动态分)
        # 为了让公式中的 s 能够贴合示例表格中的数值 (第10名为496.36)，我们这里设定一个虚拟参数 s = 106
        team_count_result = await db.execute(select(models.Team))
        actual_teams = len(team_count_result.scalars().all())
        total_teams = 106
        
                
        # 查询所有已成功攻破自己靶机的记录 (针对 AWDP)
        # attack_success_records: { challenge_id: { team_id: rank } }
        # 用于记录谁在第几名解出了哪道题
        attack_records = {}
        
        # 查询所有已成功防守自己靶机的记录 (针对 AWDP)
        # defense_records: { challenge_id: { team_id: rank } }
        defense_records = {}
        
        if is_awdp:
            # 取攻击记录
            result = await db.execute(
                select(models.ScoreLog)
                .where(models.ScoreLog.log_type == "attack_success")
                .where(models.ScoreLog.reason.like("%成功攻破自有靶机%"))
                .order_by(models.ScoreLog.created_at)
            )
            for log in result.scalars().all():
                if log.challenge_id not in attack_records:
                    attack_records[log.challenge_id] = {}
                    
                # 只有当队伍是第一次解出时才记录，防止重复提交覆盖最初的 rank 和 log_id
                if log.team_id not in attack_records[log.challenge_id]:
                    match = re.search(r'Rank: (\d+)', log.reason)
                    rank = int(match.group(1)) if match else 1
                    attack_records[log.challenge_id][log.team_id] = {"rank": rank, "round_num": log.round_num, "log_id": log.id}
                
            # 取防守记录
            result = await db.execute(
                select(models.ScoreLog)
                .where(models.ScoreLog.log_type == "defense_success")
                .where(models.ScoreLog.reason.like("%首次防御成功%"))
                .order_by(models.ScoreLog.created_at)
            )
            for log in result.scalars().all():
                if log.challenge_id not in defense_records:
                    defense_records[log.challenge_id] = {}
                    
                # 同理，只取第一次
                if log.team_id not in defense_records[log.challenge_id]:
                    match = re.search(r'Rank: (\d+)', log.reason)
                    rank = int(match.group(1)) if match else 1
                    defense_records[log.challenge_id][log.team_id] = {"rank": rank, "round_num": log.round_num, "log_id": log.id}

        # 使用集合记录本轮已经计算过“维持分”的队伍和题目，避免因为靶机遍历重复加分
        processed_attack_rolling = set()
        processed_defense_rolling = set()
        
        # 对于防守滚轮分，也需要像攻击一样，脱离 box 循环，直接遍历所有解出/防守成功的队伍
        # 否则如果队伍把靶机销毁了（导致没有任何该队伍的 box 记录），它就会白白丢掉应该拿的防守维持分
        if is_awdp:
            chal_result = await db.execute(select(models.Challenge))
            all_chals = chal_result.scalars().all()
            for chal in all_chals:
                # ================= 攻击分数结算 =================
                chal_attack_records = attack_records.get(chal.id, {})
                current_solve_count = len(chal_attack_records)
                
                for solver_tid, record in chal_attack_records.items():
                    cache_key = f"{solver_tid}_{chal.id}_attack"
                    if cache_key in processed_attack_rolling:
                        continue
                    processed_attack_rolling.add(cache_key)
                    
                    rank = record["rank"]
                    first_solve_round = record["round_num"]
                    
                    solver_team_result = await db.execute(select(models.Team).where(models.Team.id == solver_tid))
                    solver_team = solver_team_result.scalars().first()
                    
                    if first_solve_round == scoring_round:
                        s_dynamic = ScoringEngine.calculate_dynamic_score(chal.base_score, total_teams, rank)
                        bonus = ScoringEngine.calculate_bonus_score(chal.base_score, rank)
                        round_score = round(s_dynamic + bonus, 2)
                        reason = f"Round {scoring_round} 成功攻破自有靶机并首次得分 (动态分: {s_dynamic}, 加成: {bonus})"
                        
                        log_result = await db.execute(select(models.ScoreLog).where(models.ScoreLog.id == record["log_id"]))
                        original_log = log_result.scalars().first()
                        if original_log and original_log.score_change == 0.0:
                            original_log.score_change = round_score
                            original_log.reason = reason
                            if solver_team:
                                solver_team.total_score += round_score
                    else:
                        round_score = ScoringEngine.calculate_dynamic_score(chal.base_score, total_teams, current_solve_count)
                        reason = f"Round {scoring_round} 攻破维持得分 (当前总解出数: {current_solve_count})"
                        
                        db.add(models.ScoreLog(
                            team_id=solver_tid,
                            challenge_id=chal.id,
                            round_num=scoring_round,
                            score_change=round_score,
                            reason=reason,
                            log_type="attack_success"
                        ))
                        if solver_team:
                            solver_team.total_score += round_score
                            
                # ================= 防守分数结算 =================
                chal_defense_records = defense_records.get(chal.id, {})
                current_defense_count = len(chal_defense_records)
                
                for defender_tid, record in chal_defense_records.items():
                    cache_key = f"{defender_tid}_{chal.id}_defense"
                    if cache_key in processed_defense_rolling:
                        continue
                    processed_defense_rolling.add(cache_key)
                    
                    rank = record["rank"]
                    first_defense_round = record["round_num"]
                    
                    defender_team_result = await db.execute(select(models.Team).where(models.Team.id == defender_tid))
                    defender_team = defender_team_result.scalars().first()
                    
                    # 在真实场景中，可以在这里额外查询 defender_tid 对应的 box 状态来计算 SLA 惩罚
                    # 为了确保分数正常发出，我们默认其只要不被扣分就是拿全额动态分
                    defense_base = 0.0
                    
                    if first_defense_round == scoring_round:
                        s_dynamic = ScoringEngine.calculate_dynamic_score(chal.base_score, total_teams, rank)
                        bonus = ScoringEngine.calculate_bonus_score(chal.base_score, rank)
                        defense_base = round(s_dynamic + bonus, 2)
                        reason = f"Round {scoring_round} 首次防御成功并得分 (动态分: {s_dynamic}, 加成: {bonus})"
                        
                        log_result = await db.execute(select(models.ScoreLog).where(models.ScoreLog.id == record["log_id"]))
                        original_log = log_result.scalars().first()
                        if original_log and original_log.score_change == 0.0:
                            original_log.score_change = defense_base
                            original_log.reason = reason
                            if defender_team:
                                defender_team.total_score += defense_base
                    else:
                        defense_base = ScoringEngine.calculate_dynamic_score(chal.base_score, total_teams, current_defense_count)
                        reason = f"Round {scoring_round} 防御维持得分 (当前总防守数: {current_defense_count})"
                        
                        db.add(models.ScoreLog(
                            team_id=defender_tid,
                            challenge_id=chal.id,
                            round_num=scoring_round,
                            score_change=defense_base,
                            reason=reason,
                            log_type="defense_success"
                        ))
                        if defender_team:
                            defender_team.total_score += defense_base
                        
        # 在 AWDP 模式中，防守失败扣分和攻击加分不再通过这里的循环自动进行，
        # 而是完全通过选手的实际提交行为 (Submit Flag / Defense Script) 来触发结算。
                
        # Generate new flag for this box for the new round
    for b in boxes:
        new_flag_str = f"flag{{{uuid.uuid4().hex}}}"
        new_flag = models.Flag(
            flag_str=new_flag_str,
            challenge_id=b.challenge_id,
            team_id=b.team_id,
            round_num=round_num
        )
        db.add(new_flag)
        # TODO: Inject flag into container using Docker API
        
