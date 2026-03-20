from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.core.database import Base

class Announcement(Base):
    __tablename__ = "announcements"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    is_visible = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, index=True)
    total_score = Column(Float, default=0.0)
    avatar_url = Column(String(500), default="/static/avatars/laoma.png")
    
    users = relationship("User", back_populates="team")
    score_logs = relationship("ScoreLog", back_populates="team")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    password = Column(String(100))
    avatar_url = Column(String(500), default="/static/avatars/laoma.png")
    is_admin = Column(Boolean, default=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)

    team = relationship("Team", back_populates="users")

class Challenge(Base):
    __tablename__ = "challenges"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True)
    description = Column(Text)
    category = Column(String(50), default="web") # web, pwn, crypto, misc, etc.
    is_visible = Column(Boolean, default=True)
    
    # 扩展字段
    chal_type = Column(String(20), default="awdp") # awdp, ctf_docker, ctf_attachment
    attachment_url = Column(String(500), nullable=True)
    is_dynamic_score = Column(Boolean, default=False)
    min_score = Column(Float, default=100.0)
    
    attack_image = Column(String(100), nullable=True)
    check_image = Column(String(100), nullable=True)
    base_score = Column(Float, default=500.0)
    initial_defense_count = Column(Integer, default=10)

class GameBox(Base):
    __tablename__ = "game_boxes"
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    challenge_id = Column(Integer, ForeignKey("challenges.id"))
    attack_container_id = Column(String(100), nullable=True)
    check_container_id = Column(String(100), nullable=True)
    status = Column(String(20), default="down") # up, down
    attack_connection_info = Column(String(100), nullable=True)
    remaining_defense_count = Column(Integer, default=10)
    
    # 扩展字段：CTF 动态靶机的过期时间
    expires_at = Column(DateTime(timezone=True), nullable=True)

class Flag(Base):
    __tablename__ = "flags"
    id = Column(Integer, primary_key=True, index=True)
    flag_str = Column(String(100), unique=True, index=True)
    challenge_id = Column(Integer, ForeignKey("challenges.id"))
    team_id = Column(Integer, ForeignKey("teams.id"))
    round_num = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class DefenseScript(Base):
    __tablename__ = "defense_scripts"
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    challenge_id = Column(Integer, ForeignKey("challenges.id"))
    file_path = Column(String(255))
    status = Column(String(20), default="pending") # pending, success, failed
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    check_log = Column(Text, nullable=True)

class GameConfig(Base):
    __tablename__ = "game_config"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), default="AWDP Championship")
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    round_duration = Column(Integer, default=5) # in minutes
    status = Column(String(20), default="pending") # pending, running, paused, finished
    
    # CTF / AWDP 双模式扩展字段
    game_mode = Column(String(20), default="awdp") # awdp, ctf
    ctf_scoring_type = Column(String(20), default="dynamic") # static, dynamic

class RoundLog(Base):
    __tablename__ = "round_logs"
    id = Column(Integer, primary_key=True, index=True)
    round_num = Column(Integer, unique=True, index=True)
    start_time = Column(DateTime(timezone=True), server_default=func.now())
    end_time = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default="running") # running, finished

class ScoreLog(Base):
    __tablename__ = "score_logs"
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"))
    challenge_id = Column(Integer, ForeignKey("challenges.id"), nullable=True)
    round_num = Column(Integer, nullable=True)
    score_change = Column(Float)
    reason = Column(String(200)) 
    log_type = Column(String(20)) # bonus, attack_first, attack_roll, defense_first, defense_roll, sla
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    team = relationship("Team", back_populates="score_logs")