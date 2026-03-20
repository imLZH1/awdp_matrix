from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List
import os
import uuid

from backend.core.database import get_db
from backend.api.v1.api import get_current_user
from backend.models import models
from backend.core.security import get_password_hash, verify_password

admin_router = APIRouter()

# --- Schemas ---
class TeamCreate(BaseModel):
    name: str
    password: str = None

class TeamUpdate(BaseModel):
    password: Optional[str] = None
    avatar_url: Optional[str] = None

class AdminPasswordUpdate(BaseModel):
    old_password: str
    new_password: str

class ChallengeCreate(BaseModel):
    name: str
    description: str
    category: str = "web"
    is_visible: bool = True
    chal_type: str = "awdp"
    attachment_url: Optional[str] = None
    is_dynamic_score: bool = False
    min_score: float = 100.0
    attack_image: Optional[str] = None
    check_image: Optional[str] = None
    base_score: float = 500.0
    initial_defense_count: int = 10

class ChallengeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    is_visible: Optional[bool] = None
    chal_type: Optional[str] = None
    attachment_url: Optional[str] = None
    is_dynamic_score: Optional[bool] = None
    min_score: Optional[float] = None
    attack_image: Optional[str] = None
    check_image: Optional[str] = None
    base_score: Optional[float] = None
    initial_defense_count: Optional[int] = None

class AnnouncementCreate(BaseModel):
    title: str
    content: str
    is_visible: bool = True

class AnnouncementUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    is_visible: Optional[bool] = None

class GameConfigUpdate(BaseModel):
    name: str
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    round_duration: int # minutes
    status: str
    game_mode: str = "awdp"
    ctf_scoring_type: str = "dynamic"

# --- Middleware-like check ---
async def get_current_admin(current_user: models.User = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可访问")
    return current_user

# --- Team Management ---
@admin_router.get("/teams")
async def list_teams(db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    result = await db.execute(select(models.Team))
    return result.scalars().all()

@admin_router.post("/teams")
async def create_team(team_in: TeamCreate, db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    new_team = models.Team(name=team_in.name, total_score=0.0)
    db.add(new_team)
    await db.commit()
    await db.refresh(new_team)
    
    # 自动为队伍创建一个默认用户
    default_user = models.User(
        username=team_in.name,
        password=get_password_hash(team_in.password or "123456"),
        team_id=new_team.id,
        is_admin=False
    )
    db.add(default_user)
    await db.commit()
    return new_team

@admin_router.put("/teams/{team_id}")
async def update_team(team_id: int, team_in: TeamUpdate, db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    result = await db.execute(select(models.Team).where(models.Team.id == team_id))
    team = result.scalars().first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
        
    if team_in.avatar_url is not None:
        team.avatar_url = team_in.avatar_url
        
    if team_in.password:
        user_result = await db.execute(select(models.User).where(models.User.team_id == team_id))
        user = user_result.scalars().first()
        if user:
            user.password = get_password_hash(team_in.password)
            
    await db.commit()
    return {"message": "队伍信息更新成功"}

@admin_router.post("/teams/{team_id}/avatar")
async def upload_team_avatar_admin(team_id: int, file: UploadFile = File(...), admin: models.User = Depends(get_current_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Team).where(models.Team.id == team_id))
    team = result.scalars().first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
        
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
    team.avatar_url = avatar_url
    await db.commit()
    
    return {"message": "头像上传成功", "avatar_url": avatar_url}
    
@admin_router.delete("/teams/{team_id}")
async def delete_team(team_id: int, db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    await db.execute(delete(models.User).where(models.User.team_id == team_id))
    await db.execute(delete(models.Team).where(models.Team.id == team_id))
    await db.commit()
    return {"message": "队伍已删除"}

@admin_router.post("/me/password")
async def update_admin_password(data: AdminPasswordUpdate, db: AsyncSession = Depends(get_db), current_admin: models.User = Depends(get_current_admin)):
    if not verify_password(data.old_password, current_admin.password):
        raise HTTPException(status_code=400, detail="原密码错误")
        
    current_admin.password = get_password_hash(data.new_password)
    await db.commit()
    return {"message": "管理员密码修改成功"}

@admin_router.get("/challenges")
async def list_challenges(db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    result = await db.execute(select(models.Challenge))
    return result.scalars().all()

@admin_router.post("/challenges")
async def create_challenge(chal_in: ChallengeCreate, db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    new_chal = models.Challenge(**chal_in.dict())
    db.add(new_chal)
    await db.commit()
    await db.refresh(new_chal)
    return new_chal

@admin_router.delete("/challenges/{challenge_id}")
async def delete_challenge(challenge_id: int, db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    await db.execute(delete(models.Challenge).where(models.Challenge.id == challenge_id))
    await db.commit()
    return {"message": "题目已删除"}

@admin_router.post("/challenges/upload_attachment")
async def upload_challenge_attachment(file: UploadFile = File(...), admin: models.User = Depends(get_current_admin)):
    upload_dir = "/opt/awdp/frontend/attachments"
    os.makedirs(upload_dir, exist_ok=True)
    
    # Generate unique filename
    ext = os.path.splitext(file.filename)[1]
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(upload_dir, safe_filename)
    
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
        
    return {"url": f"/static/attachments/{safe_filename}"}

@admin_router.put("/challenges/{challenge_id}")
async def update_challenge(challenge_id: int, chal_in: ChallengeUpdate, db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    result = await db.execute(select(models.Challenge).where(models.Challenge.id == challenge_id))
    chal = result.scalars().first()
    if not chal:
        raise HTTPException(status_code=404, detail="Challenge not found")
        
    update_data = chal_in.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(chal, key, value)
        
    await db.commit()
    await db.refresh(chal)
    return chal

# --- Game Control ---
@admin_router.get("/game/config")
async def get_game_config(db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    result = await db.execute(select(models.GameConfig).limit(1))
    config = result.scalars().first()
    if not config:
        config = models.GameConfig()
        db.add(config)
        await db.commit()
        await db.refresh(config)
        
    return {
        "id": config.id,
        "name": config.name,
        "start_time": config.start_time.isoformat() if config.start_time else None,
        "end_time": config.end_time.isoformat() if config.end_time else None,
        "round_duration": config.round_duration,
        "status": config.status,
        "game_mode": config.game_mode,
        "ctf_scoring_type": config.ctf_scoring_type
    }

@admin_router.post("/game/config")
async def update_game_config(config_in: GameConfigUpdate, db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    result = await db.execute(select(models.GameConfig).limit(1))
    config = result.scalars().first()
    if not config:
        config = models.GameConfig()
        db.add(config)
    
    config.name = config_in.name
    config.game_mode = config_in.game_mode
    config.ctf_scoring_type = config_in.ctf_scoring_type
    
    # 前端传过来的是本地时间，直接存储即可，不需要强制转成 UTC，否则会导致时间差 8 小时
    start_time = config_in.start_time
    if start_time and start_time.tzinfo:
        start_time = start_time.replace(tzinfo=None)
    config.start_time = start_time
    
    end_time = config_in.end_time
    if end_time and end_time.tzinfo:
        end_time = end_time.replace(tzinfo=None)
    config.end_time = end_time
    
    config.round_duration = config_in.round_duration
    config.status = config_in.status
    
    await db.commit()
    return {"message": "比赛配置已更新"}

import logging

logger = logging.getLogger(__name__)

@admin_router.post("/game/reset")
async def reset_game(db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    """
    重置比赛状态，清空所有队伍的分数、得分流水、Flag 提交记录，
    将比赛状态重置为 pending，并且轮次清零。
    注意：不清理题目、队伍本身和容器环境。
    """
    try:
        # 1. 停止比赛，重置配置
        config_result = await db.execute(select(models.GameConfig).limit(1))
        config = config_result.scalars().first()
        if config:
            config.status = "pending"
            if hasattr(config, 'current_round'):
                config.current_round = 0
            
        # 2. 将所有队伍的分数重置为 0
        teams_result = await db.execute(select(models.Team))
        teams = teams_result.scalars().all()
        for team in teams:
            team.total_score = 0.0
            
        # 3. 删除所有的得分流水和 Flag 提交记录
        if hasattr(models, 'ScoreLog'):
            await db.execute(delete(models.ScoreLog))
        if hasattr(models, 'Flag'):
            await db.execute(delete(models.Flag))
            
        # 清理防御脚本记录
        if hasattr(models, 'DefenseScript'):
            await db.execute(delete(models.DefenseScript))
            
        # 清理轮次记录
        if hasattr(models, 'RoundLog'):
            await db.execute(delete(models.RoundLog))
            
        # 4. 删除所有的 GameBox 记录，以清空容器监控面板
        # （真正的 Docker 容器销毁需要另外处理或在后台脚本中进行，这里仅清理数据库记录）
        if hasattr(models, 'GameBox'):
            await db.execute(delete(models.GameBox))
        
        await db.commit()
        return {"message": "比赛已成功重置：分数、流水、轮次和容器监控均已清零（题目保留）"}
    except Exception as e:
        await db.rollback()
        logger.error(f"Reset game failed: {str(e)}")
        raise HTTPException(status_code=500, detail="重置比赛失败")

@admin_router.post("/game/control/{action}")
async def control_game(action: str, db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    if action not in ["start", "pause", "stop"]:
        raise HTTPException(status_code=400, detail="Invalid action")
        
    result = await db.execute(select(models.GameConfig).limit(1))
    config = result.scalars().first()
    
    if action == "start":
        config.status = "running"
    elif action in ["pause", "stop"]:
        if action == "pause":
            config.status = "paused"
        else:
            config.status = "finished"
            
        # 比赛暂停或终止时，关闭所有正在运行的容器
        from backend.core.docker_mgr import stop_and_remove_container
        
        boxes_result = await db.execute(
            select(models.GameBox).where(models.GameBox.status == "up")
        )
        active_boxes = boxes_result.scalars().all()
        
        for box in active_boxes:
            if box.attack_container_id:
                stop_and_remove_container(box.attack_container_id)
            if box.check_container_id:
                stop_and_remove_container(box.check_container_id)
            
            box.status = "down"
            box.attack_container_id = None
            box.check_container_id = None
            box.attack_connection_info = None
            
    await db.commit()
    return {"message": f"比赛状态已切换为: {config.status}"}

@admin_router.get("/status")
async def get_system_status(db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
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
    
    # 计算当前轮次和剩余时间
    if config.start_time:
        # 确保时区一致，由于前端传过来的是本地时间，我们也用本地时间来计算
        from datetime import datetime
        now = datetime.now()
        
        start_time = config.start_time
        if start_time.tzinfo:
            start_time = start_time.replace(tzinfo=None)
            
        end_time = config.end_time
        if end_time and end_time.tzinfo:
            end_time = end_time.replace(tzinfo=None)
            
        if now < start_time:
            # 比赛尚未开始
            time_diff = start_time - now
            total_seconds = int(time_diff.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            remaining_time_str = f"-{hours:02d}:{minutes:02d}:{seconds:02d}" # 负数表示距离开始还有多久
        elif end_time and now > end_time:
            # 比赛已结束
            current_round = "Ended"
            remaining_time_str = "00:00:00"
            if config.status != "finished":
                config.status = "finished"
                await db.commit()
                is_running = False
        else:
            # 比赛进行中，或者没有设置结束时间，计算轮次
            if config.status == "running":
                elapsed_time = now - start_time
                round_duration_sec = config.round_duration * 60
                
                # 计算已经过去的完整轮次数 + 1 就是当前轮次
                current_round = int(elapsed_time.total_seconds() // round_duration_sec) + 1
                
                # 距离本轮结束的剩余时间
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

# --- Container Matrix ---
@admin_router.get("/containers")
async def get_containers(db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    # 联表查询 Team, Challenge, GameBox
    result = await db.execute(
        select(models.GameBox, models.Team.name, models.Challenge.name)
        .outerjoin(models.Team, models.GameBox.team_id == models.Team.id)
        .outerjoin(models.Challenge, models.GameBox.challenge_id == models.Challenge.id)
    )
    rows = result.all()
    
    # 组装返回数据供前端展示
    response = []
    for box, team_name, challenge_name in rows:
        response.append({
            "id": box.id,
            "team_id": box.team_id,
            "team_name": team_name or "Unknown",
            "challenge_id": box.challenge_id,
            "challenge_name": challenge_name or "Unknown",
            "status": box.status,
            "remaining_defense_count": box.remaining_defense_count,
            "attack_connection_info": box.attack_connection_info,
        })
    return response

@admin_router.post("/containers/{box_id}/reset")
async def reset_container(box_id: int, db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    from backend.core.docker_mgr import stop_and_remove_container, start_attack_container
    
    result = await db.execute(
        select(models.GameBox, models.Challenge)
        .outerjoin(models.Challenge, models.GameBox.challenge_id == models.Challenge.id)
        .where(models.GameBox.id == box_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Container not found")
        
    box, challenge = row
        
    if box.attack_container_id:
        stop_and_remove_container(box.attack_container_id)
        
    if challenge and challenge.attack_image:
        try:
            # 简单生成一个flag供重置使用，实际应从Flag表获取最新有效flag
            flag_str = f"flag{{reset_test_{box_id}}}"
            container_id, conn_info = start_attack_container(challenge.attack_image, flag_str)
            box.attack_container_id = container_id
            box.attack_connection_info = conn_info
            box.status = "up"
        except Exception as e:
            box.status = "down"
            raise HTTPException(status_code=500, detail=f"Failed to start container: {e}")
            
    await db.commit()
    return {"message": "容器已重置拉起"}



# --- Audit Logs ---
@admin_router.get("/logs/flags")
async def get_flag_logs(db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    result = await db.execute(
        select(
            models.Flag.created_at,
            models.Team.name.label('team_name'),
            models.Challenge.name.label('challenge_name'),
            models.Flag.flag_str.label('flag'),
        ).join(models.Team, models.Flag.team_id == models.Team.id)
         .join(models.Challenge, models.Flag.challenge_id == models.Challenge.id)
         .order_by(models.Flag.created_at.desc())
         .limit(100)
    )
    logs = result.all()
    return [{"created_at": l.created_at, "team_name": l.team_name, "challenge_name": l.challenge_name, "flag": l.flag, "status": "success"} for l in logs]

# --- Announcement Management ---
@admin_router.get("/announcements")
async def list_announcements(db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    result = await db.execute(select(models.Announcement).order_by(models.Announcement.created_at.desc()))
    return result.scalars().all()

@admin_router.post("/announcements")
async def create_announcement(ann_in: AnnouncementCreate, db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    new_ann = models.Announcement(**ann_in.dict())
    db.add(new_ann)
    await db.commit()
    await db.refresh(new_ann)
    return new_ann

@admin_router.put("/announcements/{ann_id}")
async def update_announcement(ann_id: int, ann_in: AnnouncementUpdate, db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    result = await db.execute(select(models.Announcement).where(models.Announcement.id == ann_id))
    ann = result.scalars().first()
    if not ann:
        raise HTTPException(status_code=404, detail="Announcement not found")
        
    for key, value in ann_in.dict(exclude_unset=True).items():
        setattr(ann, key, value)
        
    await db.commit()
    return {"message": "公告更新成功"}

@admin_router.delete("/announcements/{ann_id}")
async def delete_announcement(ann_id: int, db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    await db.execute(delete(models.Announcement).where(models.Announcement.id == ann_id))
    await db.commit()
    return {"message": "公告已删除"}

@admin_router.get("/logs/scores")
async def get_score_logs(db: AsyncSession = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    result = await db.execute(
        select(models.ScoreLog, models.Team.name, models.Challenge.name)
        .outerjoin(models.Team, models.ScoreLog.team_id == models.Team.id)
        .outerjoin(models.Challenge, models.ScoreLog.challenge_id == models.Challenge.id)
        .order_by(models.ScoreLog.created_at.desc())
    )
    rows = result.all()
    response = []
    for log, team_name, challenge_name in rows:
        response.append({
            "id": log.id,
            "team_id": log.team_id,
            "team_name": team_name or "Unknown",
            "challenge_id": log.challenge_id,
            "challenge_name": challenge_name or "Unknown",
            "round_num": log.round_num,
            "score_change": log.score_change,
            "reason": log.reason,
            "log_type": log.log_type,
            "created_at": log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else ""
        })
    return response
