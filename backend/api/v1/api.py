from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import List
from datetime import datetime, timedelta
import os
from pydantic import BaseModel
import uuid

from backend.core.database import get_db
from backend.core.security import verify_password, create_access_token, get_password_hash
from backend.core.config import settings
from backend.models import models
from backend.engine.scoring import ScoringEngine

api_router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login")

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    from jose import jwt, JWTError
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    
    result = await db.execute(select(models.User).where(models.User.username == username))
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user

class LoginData(BaseModel):
    username: str
    password: str

class PasswordUpdate(BaseModel):
    old_password: str
    new_password: str

@api_router.post("/login")
async def login(login_data: LoginData, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.User).where(models.User.username == login_data.username))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not verify_password(login_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 将是否是 admin 写入 token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "is_admin": user.is_admin}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "is_admin": user.is_admin}

@api_router.get("/me")
async def read_users_me(current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.team_id:
        result = await db.execute(select(models.Team).where(models.Team.id == current_user.team_id))
        team = result.scalars().first()
        return {
            "username": current_user.username,
            "is_admin": current_user.is_admin,
            "team_id": current_user.team_id,
            "team_name": team.name if team else None,
            "avatar_url": team.avatar_url if team else None
        }
    return {
        "username": current_user.username,
        "is_admin": current_user.is_admin,
        "team_id": current_user.team_id
    }

@api_router.post("/me/avatar")
async def update_avatar(file: UploadFile = File(...), current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not current_user.team_id:
        raise HTTPException(status_code=400, detail="User does not belong to a team")
        
    # Check file size (max 1MB)
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    if file_size > 1 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件大小不能超过 1MB")
        
    # Check file extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".gif"]:
        raise HTTPException(status_code=400, detail="只允许上传 jpg, png, gif 格式的图片")
        
    upload_dir = "/opt/awdp/frontend/avatars"
    os.makedirs(upload_dir, exist_ok=True)
    
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(upload_dir, safe_filename)
    
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
        
    avatar_url = f"/static/avatars/{safe_filename}"
    
    # Update DB
    result = await db.execute(select(models.Team).where(models.Team.id == current_user.team_id))
    team = result.scalars().first()
    if team:
        team.avatar_url = avatar_url
        await db.commit()
        
    return {"message": "头像更新成功", "avatar_url": avatar_url}

@api_router.post("/me/password")
async def update_password(data: PasswordUpdate, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not verify_password(data.old_password, current_user.password):
        raise HTTPException(status_code=400, detail="原密码错误")
        
    current_user.password = get_password_hash(data.new_password)
    await db.commit()
    return {"message": "密码修改成功"}

from backend.core.docker_mgr import start_attack_container, stop_and_remove_container, run_defense_check
import os
import uuid

class FlagSubmit(BaseModel):
    flag: str

@api_router.get("/announcements")
async def get_public_announcements(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Announcement)
        .where(models.Announcement.is_visible == True)
        .order_by(models.Announcement.created_at.desc())
    )
    return result.scalars().all()

@api_router.get("/scoreboard")
async def get_scoreboard(db: AsyncSession = Depends(get_db)):
    # 获取所有的题目
    chal_result = await db.execute(select(models.Challenge))
    challenges = chal_result.scalars().all()
    
    # 获取所有的队伍
    team_result = await db.execute(select(models.Team).order_by(models.Team.total_score.desc()))
    teams = team_result.scalars().all()
    
    # 获取所有的 GameBox 状态
    box_result = await db.execute(select(models.GameBox))
    boxes = box_result.scalars().all()
    
    # 获取所有的 ScoreLog 用于计算每个题目每个队伍的攻击分和防御分
    score_result = await db.execute(select(models.ScoreLog))
    score_logs = score_result.scalars().all()
    
    # 获取比赛模式以决定是否需要提前预演计算首杀分数
    config_result = await db.execute(select(models.GameConfig).limit(1))
    config = config_result.scalars().first()
    is_awdp = config and config.game_mode == "awdp"
    
    # 组装数据
    box_map = {}
    for box in boxes:
        if box.team_id not in box_map:
            box_map[box.team_id] = {}
        box_map[box.team_id][box.challenge_id] = box.status
        
    # score_map 结构: team_id -> { chal_id: { "attack": 0, "defense": 0, "blood": None, "defense_blood": None } }
    score_map = {}
    
    import re
    
    # 在 AWDP 模式下，对于那些 "成功攻破自有靶机" 但得分为 0.0 的首轮待结算记录，我们在此实时预演它的预期分数
    for log in score_logs:
        if log.team_id not in score_map:
            score_map[log.team_id] = {}
        if log.challenge_id:
            if log.challenge_id not in score_map[log.team_id]:
                score_map[log.team_id][log.challenge_id] = {"attack": 0.0, "defense": 0.0, "blood": None, "defense_blood": None}
            
            score_change = log.score_change
            
            # 如果是 AWDP 模式的待结算记录（分数为 0），实时推演当前能获得的分数
            if is_awdp and log.log_type == "attack_success" and log.score_change == 0.0 and "成功攻破自有靶机" in log.reason:
                # 只有当这是最新一轮（还未结算）的占坑记录时，才进行预演，防止和已经结算的流水重复加分
                has_been_settled = any(l.team_id == log.team_id and l.challenge_id == log.challenge_id and l.log_type == "attack_success" and l.score_change > 0 and "成功攻破自有靶机" in l.reason for l in score_logs)
                
                if not has_been_settled:
                    match = re.search(r'Rank: (\d+)', log.reason)
                    if match:
                        rank = int(match.group(1))
                        
                        # 获取题目基础信息推演
                        chal = next((c for c in challenges if c.id == log.challenge_id), None)
                        if chal:
                            effective_team_count = 106
                            # 预演首轮新解出的分数：(自身排名动态分 + 一次性加成)
                            s_dynamic = ScoringEngine.calculate_dynamic_score(chal.base_score, effective_team_count, rank)
                            bonus = ScoringEngine.calculate_bonus_score(chal.base_score, rank)
                            score_change = round(s_dynamic + bonus, 2)
                            
            elif is_awdp and log.log_type == "defense_success" and log.score_change == 0.0 and "首次防御成功" in log.reason:
                # 同样的逻辑，为刚提交还没被 scheduler 结算的防御预演分数
                has_been_settled = any(l.team_id == log.team_id and l.challenge_id == log.challenge_id and l.log_type == "defense_success" and l.score_change > 0 and "首次防御成功" in l.reason for l in score_logs)
                
                if not has_been_settled:
                    match = re.search(r'Rank: (\d+)', log.reason)
                    if match:
                        rank = int(match.group(1))
                        chal = next((c for c in challenges if c.id == log.challenge_id), None)
                        if chal:
                            effective_team_count = 106
                            s_dynamic = ScoringEngine.calculate_dynamic_score(chal.base_score, effective_team_count, rank)
                            bonus = ScoringEngine.calculate_bonus_score(chal.base_score, rank)
                            score_change = round(s_dynamic + bonus, 2)
                        
            # 将该条记录的得分累加到对应的分数池中
            if log.log_type == "attack_success" and "成功攻破自有靶机" not in log.reason:
                # 只累加已经真实结算的分数（或者剥削加分）
                score_map[log.team_id][log.challenge_id]["attack"] += score_change
            elif log.log_type == "attack_success" and "成功攻破自有靶机" in log.reason and score_change > 0:
                # 对于那些预演出的分数，我们也加进去展示
                score_map[log.team_id][log.challenge_id]["attack"] += score_change
            elif log.log_type == "defense_success" and "首次防御成功" in log.reason and score_change > 0:
                # 防御预演分
                score_map[log.team_id][log.challenge_id]["defense"] += score_change
            elif log.log_type in ["defense_success", "defense_failed", "sla"] and "首次防御成功" not in log.reason:
                # 真实的结算防守分 / sla 扣分
                score_map[log.team_id][log.challenge_id]["defense"] += score_change

    # 简单模拟计算一血、二血、三血
    # 先把所有的 attack_success 按题目分组并按时间排序
    for chal in challenges:
        chal_logs = [log for log in score_logs if log.challenge_id == chal.id and log.log_type == "attack_success"]
        chal_logs.sort(key=lambda x: x.created_at)
        
        # 取前三个不同队伍的攻击记录作为一、二、三血
        blood_teams = []
        for log in chal_logs:
            if log.team_id not in blood_teams:
                blood_teams.append(log.team_id)
            if len(blood_teams) == 3:
                break
                
        for idx, t_id in enumerate(blood_teams):
            if t_id in score_map and chal.id in score_map[t_id]:
                score_map[t_id][chal.id]["blood"] = idx + 1 # 1: 一血, 2: 二血, 3: 三血
                
        # 同样为防守计算防守的一血、二血、三血
        def_logs = [log for log in score_logs if log.challenge_id == chal.id and log.log_type == "defense_success" and "首次防御成功" in log.reason]
        def_logs.sort(key=lambda x: x.created_at)
        
        def_blood_teams = []
        for log in def_logs:
            if log.team_id not in def_blood_teams:
                def_blood_teams.append(log.team_id)
            if len(def_blood_teams) == 3:
                break
                
        for idx, t_id in enumerate(def_blood_teams):
            if t_id in score_map and chal.id in score_map[t_id]:
                score_map[t_id][chal.id]["defense_blood"] = idx + 1

    team_data = []
    for team in teams:
        team_status = {}
        team_scores = {}
        
        # AWDP 模式下，我们不再使用数据库直接累计的 team.total_score（因为它在重启时可能和流水不同步）
        # 而是直接从本接口组装的各项得分中动态累加，这样保证计分板的总分一定是各项分数之和
        realtime_total_score = 0.0
        
        for chal in challenges:
            team_status[str(chal.id)] = box_map.get(team.id, {}).get(chal.id, "down")
            
            # 获取该题目该队伍的攻防得分
            chal_score_data = score_map.get(team.id, {}).get(chal.id, {"attack": 0.0, "defense": 0.0, "blood": None, "defense_blood": None})
            team_scores[str(chal.id)] = {
                "attack": round(chal_score_data["attack"], 2),
                "defense": round(chal_score_data["defense"], 2),
                "blood": chal_score_data["blood"],
                "defense_blood": chal_score_data["defense_blood"]
            }
            if not is_awdp:
                realtime_total_score += chal_score_data["attack"] + chal_score_data["defense"]
            else:
                # 在 AWDP 模式下，为了让计分板看起来合理（总分 = 各题攻击分 + 各题防守分），
                # 我们不再使用数据库的 team.total_score，而是根据流水重新聚合计算该队伍的真实总分。
                realtime_total_score += chal_score_data["attack"] + chal_score_data["defense"]
            
        team_data.append({
            "id": team.id,
            "name": team.name,
            "total_score": round(realtime_total_score, 2), 
            "avatar_url": team.avatar_url,
            "status": team_status,
            "scores": team_scores
        })
        
    # 对团队重新按照预演后的总分进行排序
    team_data.sort(key=lambda x: x["total_score"], reverse=True)
    
    # 动态计算每道题当前的实时价值，用于在 Battle Field 中展示
    challenge_data = []
    for c in challenges:
        # 只统计首杀记录的个数，也就是有多少支不同的队伍解出了这道题
        current_solve_count = sum(1 for l in score_logs if l.challenge_id == c.id and l.log_type == "attack_success" and "成功攻破自有靶机" in l.reason)
        # 根据人数预演下一支队伍解出该题的动态得分 (作为卡片右上角的价值展示)
        next_rank = current_solve_count + 1
        current_dynamic_value = ScoringEngine.calculate_dynamic_score(c.base_score, 106, next_rank)
        challenge_data.append({
            "id": c.id, 
            "name": c.name,
            "category": c.category,
            "chal_type": c.chal_type,
            "base_score": c.base_score,
            "current_value": current_dynamic_value
        })
        
    return {
        "challenges": challenge_data,
        "teams": team_data
    }

@api_router.get("/challenges")
async def get_challenges(current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # 获取所有可见的题目
    result = await db.execute(select(models.Challenge).where(models.Challenge.is_visible == True))
    challenges = result.scalars().all()
    
    # 获取当前用户队伍的靶机状态
    boxes_result = await db.execute(select(models.GameBox).where(models.GameBox.team_id == current_user.team_id))
    boxes = {box.challenge_id: box for box in boxes_result.scalars().all()}
    
    # 动态计算每道题当前的实时价值
    config_result = await db.execute(select(models.GameConfig).limit(1))
    config = config_result.scalars().first()
    is_awdp = config and config.game_mode == "awdp"
    
    score_result = await db.execute(select(models.ScoreLog))
    score_logs = score_result.scalars().all()
    
    resp = []
    for chal in challenges:
        box = boxes.get(chal.id)
        
        current_attack_score = chal.base_score
        current_defense_score = chal.base_score
        if is_awdp:
            current_solve_count = sum(1 for l in score_logs if l.challenge_id == chal.id and l.log_type == "attack_success" and "成功攻破自有靶机" in l.reason)
            next_rank = current_solve_count + 1
            current_attack_score = ScoringEngine.calculate_dynamic_score(chal.base_score, 106, next_rank)
            
            current_defense_count = sum(1 for l in score_logs if l.challenge_id == chal.id and l.log_type == "defense_success" and "首次防御成功" in l.reason)
            next_defense_rank = current_defense_count + 1
            current_defense_score = ScoringEngine.calculate_dynamic_score(chal.base_score, 106, next_defense_rank)
            
        resp.append({
            "id": chal.id,
            "name": chal.name,
            "category": chal.category,
            "description": chal.description,
            "chal_type": chal.chal_type,
            "attachment_url": chal.attachment_url,
            "base_score": chal.base_score,
            "current_attack_score": current_attack_score,
            "current_defense_score": current_defense_score,
            "initial_defense_count": chal.initial_defense_count,
            "attack_status": box.status if box else "down",
            "attack_connection_info": box.attack_connection_info if box else "",
            "remaining_defense_count": box.remaining_defense_count if box else chal.initial_defense_count
        })
    return resp

@api_router.post("/challenges/{challenge_id}/start")
async def start_challenge(challenge_id: int, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # 检查比赛是否正在进行
    config_result = await db.execute(select(models.GameConfig).limit(1))
    config = config_result.scalars().first()
    if not config or config.status != "running":
        raise HTTPException(status_code=403, detail="比赛当前未处于运行状态，无法开启题目环境")

    result = await db.execute(select(models.Challenge).where(models.Challenge.id == challenge_id))
    chal = result.scalars().first()
    if not chal:
        raise HTTPException(status_code=404, detail="Challenge not found")
        
    result = await db.execute(select(models.GameBox).where(models.GameBox.team_id == current_user.team_id, models.GameBox.challenge_id == challenge_id))
    box = result.scalars().first()
    
    if box and box.status == "up":
        return {"message": "容器已在运行", "connection_info": box.attack_connection_info}
        
    if not box:
        box = models.GameBox(team_id=current_user.team_id, challenge_id=challenge_id)
        db.add(box)
        
    # 生成 UUID Flag
    flag_str = f"flag{{{uuid.uuid4()}}}"
    new_flag = models.Flag(flag_str=flag_str, challenge_id=challenge_id, team_id=current_user.team_id, round_num=1)
    db.add(new_flag)
    
    # 调用 Docker 引擎拉起环境
    try:
        container_id, conn_info = start_attack_container(chal.attack_image, flag_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Docker 启动失败，请检查镜像是否存在或联系裁判: {str(e)}")
        
    box.attack_container_id = container_id
    box.attack_connection_info = conn_info
    box.status = "up"
    
    await db.commit()
    return {"message": "攻击靶机已启动", "connection_info": conn_info}

@api_router.post("/challenges/{challenge_id}/destroy")
async def destroy_challenge(challenge_id: int, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.GameBox).where(models.GameBox.team_id == current_user.team_id, models.GameBox.challenge_id == challenge_id))
    box = result.scalars().first()
    
    if not box or box.status != "up":
        raise HTTPException(status_code=400, detail="容器未运行")
        
    if box.attack_container_id:
        stop_and_remove_container(box.attack_container_id)
        
    box.status = "down"
    box.attack_container_id = None
    box.attack_connection_info = None
    
    await db.commit()
    return {"message": "攻击靶机已销毁"}

@api_router.post("/challenges/{challenge_id}/submit_flag")
async def submit_flag(challenge_id: int, flag_in: FlagSubmit, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # 检查比赛是否正在进行
    config_result = await db.execute(select(models.GameConfig).limit(1))
    config = config_result.scalars().first()
    if not config or config.status != "running":
        raise HTTPException(status_code=403, detail="比赛当前未处于运行状态，无法提交 Flag")

    # 查找 flag
    result = await db.execute(
        select(models.Flag)
        .where(models.Flag.flag_str == flag_in.flag)
        .where(models.Flag.challenge_id == challenge_id)
    )
    flag_record = result.scalars().first()
    
    if not flag_record:
        raise HTTPException(status_code=400, detail="Flag 错误或已过期")
        
    # 查找题目信息，用于计算分数
    chal_result = await db.execute(select(models.Challenge).where(models.Challenge.id == challenge_id))
    chal = chal_result.scalars().first()
    if not chal:
        raise HTTPException(status_code=404, detail="题目不存在")

    if config.game_mode == "awdp":
        # AWDP 模式：提交自己开启的靶机的 Flag 证明攻破成功，开启每轮自动加分
        if flag_record.team_id != current_user.team_id:
            return {"message": "AWDP模式下，请提交您自己靶机的 Flag 作为攻破凭证！"}
            
        # 检查是否已经攻破过
        score_check = await db.execute(
            select(models.ScoreLog)
            .where(models.ScoreLog.team_id == current_user.team_id)
            .where(models.ScoreLog.challenge_id == challenge_id)
            .where(models.ScoreLog.log_type == "attack_success")
            .where(models.ScoreLog.reason.like("%成功攻破自有靶机%"))
        )
        if score_check.scalars().first():
            return {"message": "您已成功攻破此题，请勿重复提交，后续将自动获得轮次攻击分！"}
            
        team_result = await db.execute(select(models.Team).where(models.Team.id == current_user.team_id))
        team = team_result.scalars().first()
        
        # 获取当前题目的被攻破次数（用于计算排名 rank）
        blood_count_result = await db.execute(
            select(models.ScoreLog)
            .where(models.ScoreLog.challenge_id == challenge_id)
            .where(models.ScoreLog.log_type == "attack_success")
            .where(models.ScoreLog.reason.like("%成功攻破自有靶机%"))
            .order_by(models.ScoreLog.created_at)
        )
        blood_count = len(blood_count_result.scalars().all())
        rank = blood_count + 1
        
        # AWDP 模式下，提交 Flag 不再立刻加分，而是打上标记，交由轮次引擎统一进行滚轮赋分
        reason = f"成功攻破自有靶机 (Rank: {rank})"
        
        log = models.ScoreLog(
            team_id=current_user.team_id,
            challenge_id=challenge_id,
            round_num=flag_record.round_num,
            score_change=0.0, # 初始记为 0，由引擎在轮次结束时结算本轮的 动态分+加成分
            reason=reason,
            log_type="attack_success"
        )
        db.add(log)
        
        await db.commit()
        return {"message": f"Flag 正确！您是第 {rank} 个攻破此题的队伍。引擎将在本轮结束时为您结算动态得分与加成！"}
        
    else:
        # CTF 模式逻辑
        if flag_record.team_id == current_user.team_id:
            return {"message": "不能提交自己队伍的 Flag！"}
            
        # 检查是否已经提交过该队伍的 flag
        score_check = await db.execute(
            select(models.ScoreLog)
            .where(models.ScoreLog.team_id == current_user.team_id)
            .where(models.ScoreLog.challenge_id == challenge_id)
            .where(models.ScoreLog.reason.like(f"%偷取队伍 {flag_record.team_id} 的 Flag%"))
        )
        if score_check.scalars().first():
            return {"message": "您已经成功攻击过该队伍，请勿重复提交本轮 Flag！"}
            
        # 统计该题目被解出的总人数（计算动态衰减分和血量）
        solve_count_result = await db.execute(
            select(models.ScoreLog)
            .where(models.ScoreLog.challenge_id == challenge_id)
            .where(models.ScoreLog.log_type == "attack_success")
            .order_by(models.ScoreLog.created_at)
        )
        # 这里需要去重，看有多少个不同的队伍解出了这道题
        solve_logs = solve_count_result.scalars().all()
        solved_teams = set([l.team_id for l in solve_logs])
        
        is_first_blood_for_team = current_user.team_id not in solved_teams
        solve_count = len(solved_teams)
        n = solve_count + 1 if is_first_blood_for_team else 0
        blood_rank = n
        
        # CTF 动态计分 S_break = L + (H - L) * (0.5^(n-1))
        # 考虑到 CTF 一般不使用带参赛总队伍数的二次衰减，这里保留一个简单的降级调用
        if chal.is_dynamic_score and is_first_blood_for_team:
            s_break = ScoringEngine.calculate_dynamic_score(chal.base_score, 10, n, chal.min_score)
        else:
            s_break = chal.base_score
            
        blood_bonus = ScoringEngine.calculate_blood_bonus(s_break, blood_rank) if is_first_blood_for_team else 0.0
        
        attack_score = s_break + blood_bonus
        
        reason = f"成功偷取队伍 {flag_record.team_id} 的 Flag"
        if blood_bonus > 0:
            blood_names = {1: "一血", 2: "二血", 3: "三血"}
            reason += f" (获得{blood_names[blood_rank]}奖励 +{blood_bonus}分)"
            
        # 给攻击者加分
        team_result = await db.execute(select(models.Team).where(models.Team.id == current_user.team_id))
        team = team_result.scalars().first()
        
        log = models.ScoreLog(
            team_id=current_user.team_id,
            challenge_id=challenge_id,
            round_num=flag_record.round_num,
            score_change=attack_score, 
            reason=reason,
            log_type="attack_success"
        )
        db.add(log)
        team.total_score += attack_score
        
        # 给被攻击者扣分
        victim_result = await db.execute(select(models.Team).where(models.Team.id == flag_record.team_id))
        victim_team = victim_result.scalars().first()
        if victim_team:
            victim_log = models.ScoreLog(
                team_id=victim_team.id,
                challenge_id=challenge_id,
                round_num=flag_record.round_num,
                score_change=-attack_score, 
                reason=f"被队伍 {current_user.team_id} 攻击成功，丢失 Flag",
                log_type="defense_failed"
            )
            db.add(victim_log)
            victim_team.total_score -= attack_score
        
        await db.commit()
        return {"message": f"Flag 正确！成功攻击队伍 {flag_record.team_id}，获得 {attack_score} 分！"}

@api_router.post("/challenges/{challenge_id}/defense")
async def upload_defense(challenge_id: int, file: UploadFile = File(...), current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # 检查比赛是否正在进行
    config_result = await db.execute(select(models.GameConfig).limit(1))
    config = config_result.scalars().first()
    if not config or config.status != "running":
        raise HTTPException(status_code=403, detail="比赛当前未处于运行状态，无法上传防御脚本")

    if not file.filename.endswith(('.tar.gz', '.gz')):
        raise HTTPException(status_code=400, detail="必须上传 tar.gz 格式的防御脚本")
    
    # 获取题目信息
    chal_result = await db.execute(select(models.Challenge).where(models.Challenge.id == challenge_id))
    chal = chal_result.scalars().first()
    if not chal:
        raise HTTPException(status_code=404, detail="赛题不存在")

    # 获取当前队伍靶机信息，检查剩余防御次数
    box_result = await db.execute(
        select(models.GameBox)
        .where(models.GameBox.team_id == current_user.team_id)
        .where(models.GameBox.challenge_id == challenge_id)
    )
    box = box_result.scalars().first()
    
    # 如果没启动过靶机，允许上传吗？理论上需要靶机记录，如果没有则创建一个
    if not box:
        box = models.GameBox(
            team_id=current_user.team_id,
            challenge_id=challenge_id,
            status="down",
            remaining_defense_count=chal.initial_defense_count
        )
        db.add(box)
        await db.flush()
        
    if box.remaining_defense_count <= 0:
        raise HTTPException(status_code=403, detail="防御次数已用完")

    # 扣减次数
    box.remaining_defense_count -= 1

    # 保存文件
    upload_dir = "/opt/awdp/patches"
    os.makedirs(upload_dir, exist_ok=True)
    
    safe_filename = f"team_{current_user.team_id}_chal_{challenge_id}_{uuid.uuid4().hex[:8]}.tar.gz"
    file_path = os.path.join(upload_dir, safe_filename)
    
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
        
    # 记录到数据库
    ds = models.DefenseScript(
        team_id=current_user.team_id,
        challenge_id=challenge_id,
        file_path=file_path,
        status="pending"
    )
    db.add(ds)
    await db.commit()
    
    return {"message": f"防御脚本 {file.filename} 上传成功！剩余次数: {box.remaining_defense_count}。请点击申请 Check 进行验证。"}

@api_router.post("/challenges/{challenge_id}/check/{defense_script_id}")
async def check_defense(challenge_id: int, defense_script_id: int, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # 检查比赛是否正在进行
    config_result = await db.execute(select(models.GameConfig).limit(1))
    config = config_result.scalars().first()
    if not config or config.status != "running":
        raise HTTPException(status_code=403, detail="比赛当前未处于运行状态，无法申请 Check")

    if config.game_mode == "awdp":
        # 1. 获取指定的提交记录
        ds_result = await db.execute(
            select(models.DefenseScript)
            .where(models.DefenseScript.id == defense_script_id)
            .where(models.DefenseScript.team_id == current_user.team_id)
            .where(models.DefenseScript.challenge_id == challenge_id)
        )
        target_ds = ds_result.scalars().first()
        if not target_ds:
            raise HTTPException(status_code=404, detail="未找到该补丁提交记录")
            
        if target_ds.status == "success":
            return {"message": "该补丁已验证成功！", "status": target_ds.status}
            
        if target_ds.status == "checking":
            raise HTTPException(status_code=400, detail="该补丁正在验证中...")
            
        # 2. 获取题目的 check_image
        chal_result = await db.execute(select(models.Challenge).where(models.Challenge.id == challenge_id))
        chal = chal_result.scalars().first()
        if not chal or not chal.check_image:
            raise HTTPException(status_code=500, detail="该题目未配置防御检测环境(Check Image)")
            
        # 3. 标记为 checking 并开始检测
        target_ds.status = "checking"
        await db.commit()
        
        try:
            # 异步调用 docker_mgr 进行检测
            exit_code, logs = await run_defense_check(chal.check_image, target_ds.file_path, timeout=30)
            
            target_ds.check_log = logs
            
            if exit_code == 0:
                target_ds.status = "success"
                msg = "防御成功！"
                
                # 记录首次防御成功
                score_check = await db.execute(
                    select(models.ScoreLog)
                    .where(models.ScoreLog.team_id == current_user.team_id)
                    .where(models.ScoreLog.challenge_id == challenge_id)
                    .where(models.ScoreLog.log_type == "defense_success")
                )
                if not score_check.scalars().first():
                    # 获取最新轮次
                    round_result = await db.execute(select(models.RoundLog).order_by(models.RoundLog.round_num.desc()).limit(1))
                    latest_round = round_result.scalars().first()
                    round_num = latest_round.round_num if latest_round else 1
                    
                    # 计算 rank
                    defense_count_result = await db.execute(
                        select(models.ScoreLog)
                        .where(models.ScoreLog.challenge_id == challenge_id)
                        .where(models.ScoreLog.log_type == "defense_success")
                    )
                    rank = len(defense_count_result.scalars().all()) + 1
                    
                    log = models.ScoreLog(
                        team_id=current_user.team_id,
                        challenge_id=challenge_id,
                        round_num=round_num,
                        score_change=0.0,
                        reason=f"首次防御成功 (Rank: {rank})",
                        log_type="defense_success"
                    )
                    db.add(log)
                    msg += f" 您是第 {rank} 个修复此题的队伍。引擎将在本轮结束时为您结算防御得分！"
                    
            elif exit_code == 1:
                target_ds.status = "failed"
                msg = "服务异常"
            elif exit_code == 2:
                target_ds.status = "exploited"
                msg = "漏洞未修复(被攻破)"
            elif exit_code == 3:
                target_ds.status = "failed"
                msg = "防御失败(脚本非法)"
            else:
                target_ds.status = "failed"
                msg = "防御失败(检测异常)"
                
            await db.commit()
            return {"message": msg, "status": target_ds.status}
            
        except Exception as e:
            target_ds.status = "failed"
            target_ds.check_log = str(e)
            await db.commit()
            raise HTTPException(status_code=500, detail=f"检测过程中发生异常: {str(e)}")
            
    else:
        return {"message": "当前比赛模式不是 AWDP，不支持防御验证。"}

@api_router.get("/challenges/{challenge_id}/defense/history")
async def get_defense_history(challenge_id: int, current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.DefenseScript)
        .where(models.DefenseScript.team_id == current_user.team_id)
        .where(models.DefenseScript.challenge_id == challenge_id)
        .order_by(models.DefenseScript.uploaded_at.desc())
    )
    history = result.scalars().all()
    
    # 将 file_path 转换为只有文件名的格式，方便前端展示
    return [
        {
            "id": item.id,
            "filename": os.path.basename(item.file_path),
            "status": item.status,
            "uploaded_at": item.uploaded_at
        }
        for item in history
    ]

@api_router.get("/status")
async def get_public_status(db: AsyncSession = Depends(get_db)):
    """公开的比赛状态接口，供大屏和选手查看剩余时间"""
    result = await db.execute(select(models.GameConfig).limit(1))
    config = result.scalars().first()
    
    if not config:
        return {
            "is_running": False,
            "current_round": 0,
            "remaining_time": "00:00:00",
            "status": "pending"
        }
        
    from datetime import datetime
    now = datetime.now()
    
    is_running = config.status == "running"
    current_round = 0
    remaining_time_str = "00:00:00"
    
    if config.start_time:
        start_time = config.start_time
        if start_time.tzinfo:
            start_time = start_time.replace(tzinfo=None)
            
        end_time = config.end_time
        if end_time and end_time.tzinfo:
            end_time = end_time.replace(tzinfo=None)
            
        if now < start_time:
            time_diff = start_time - now
            total_seconds = int(time_diff.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            remaining_time_str = f"-{hours:02d}:{minutes:02d}:{seconds:02d}"
        elif end_time and now > end_time:
            current_round = "Ended"
            remaining_time_str = "00:00:00"
            is_running = False
        else:
            if config.status == "running":
                elapsed_time = now - start_time
                round_duration_sec = config.round_duration * 60
                current_round = int(elapsed_time.total_seconds() // round_duration_sec) + 1
                
                round_elapsed = elapsed_time.total_seconds() % round_duration_sec
                round_remaining = round_duration_sec - round_elapsed
                
                total_seconds = int(round_remaining)
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                seconds = total_seconds % 60
                remaining_time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                
    return {
        "is_running": is_running,
        "current_round": current_round,
        "remaining_time": remaining_time_str,
        "status": config.status
    }

@api_router.get("/score_logs", response_model=List[dict])
async def get_score_logs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.ScoreLog)
        .order_by(models.ScoreLog.created_at.desc())
        .limit(100)
    )
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "team_id": log.team_id,
            "challenge_id": log.challenge_id,
            "round_num": log.round_num,
            "score_change": log.score_change,
            "reason": log.reason,
            "log_type": log.log_type,
            "created_at": log.created_at.isoformat() if log.created_at else None
        }
        for log in logs
    ]
