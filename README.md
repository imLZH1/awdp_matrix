# AWDP Matrix Platform

![AWDP Matrix](https://img.shields.io/badge/Status-Beta-brightgreen)
![Python](https://img.shields.io/badge/Python-3.13-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104.1-teal)
![Vue3](https://img.shields.io/badge/Vue.js-3.x-4fc08d)
![Docker](https://img.shields.io/badge/Docker-Engine-2496ed)

AWDP Matrix 是一款现代化、轻量级且高度解耦的**攻防对抗（AWDP）与解题（CTF）综合赛事平台**。

本项目致力于解决传统 AWDP 平台部署繁琐、判题逻辑与平台高度耦合、资源占用过高等痛点。通过“瘦平台、胖容器”的设计理念，实现题目环境的完全隔离与灵活调度。

## ✨ 核心特性

### 1. 动态积分引擎 (Dynamic Scoring)
内置了符合国际主流赛制的二次函数动态衰减计分模型：
- **AWDP 模式**：
  - 首轮破题基础分（含名次加成：一二三血额外奖励）
  - 每轮自动结算攻击/防守维持滚轮分
  - 自动化扣减靶机宕机 (SLA) 惩罚
- ~~**CTF 模式**：~~


### 2. 独创的 Check 沙箱解耦架构
传统的 AWDP 平台通常在后端编写大量的代码去解析选手上传的 Patch、过滤恶意命令、重启服务。本平台采用**“胖容器”沙箱机制**：
- 平台后端**不解析**选手的任何压缩包，仅负责调度和状态回收。
- 裁判为每道题提供一个 `check_image`，内置 `platform_run.py` 统筹脚本和 `check.py` 判题脚本。
- 选手提交补丁后，平台拉起无网沙箱容器，传入补丁，由容器内部进行命令白名单过滤、Patch 覆盖、EXP 攻击测试。
- 平台通过读取 `Exit Code` (0=防御成功, 1=服务异常, 2=漏洞未修) 实现高度精准和安全的防守判定。

### 3. 实时攻防大屏矩阵 (Scoreboard)
- 基于 Vue 3 + Element Plus 构建的现代化大屏。
- 实时倒计时推演与计分板自动刷新。
- **精美的 UI 交互**：攻击/防御分数分开展示，支持一二三血的呼吸灯与发光特效，让赛况一目了然。

### 4. 完整的控制台管理 (Admin Dashboard)
- **赛题管理**：支持一键上传附件、配置靶机镜像、调整分数。
- **环境监控**：实时查看各队伍的靶机运行状态（Up/Down），支持一键重置宕机环境。
- **全局控制**：一键开始、暂停、结束比赛；一键清空重置比赛数据。
- **审计日志**：可视化的分数变动流水账与 Flag 提交审计。

## 🚀 快速开始

### 环境依赖
- Python 3.10+
- Docker Engine (必须允许当前用户调用 Docker API)
- SQLite (默认内置)

### 安装部署
```bash
# 1. 克隆仓库
cd /opt/ && git clone https://github.com/imLZH1/awdp_matrix.git

mov awdp_matrix awdp
cd awdp

# 2. 创建并激活虚拟环境
python3 -m venv venv
source venv/bin/activate

# 3. 安装依赖
pip install -r backend/requirements.txt


### 初始化数据
(venv) ➜  awdp git:(main) ✗ venv/bin/python init_data.py
# 4. 启动平台 (开发模式)                                                                                                     
(venv) ➜  awdp git:(main) ✗ source /opt/awdp/venv/bin/activate && export PYTHONPATH=/opt/awdp && uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload



# 写死了，所以  mov awdp_matrix awdp 了， 你可以可以自行修改
# (venv) ➜  awdp git:(main) grep -R "/opt/awdp/"
# grep: backend/__pycache__/main.cpython-312.pyc: binary file matches
# backend/main.py:frontend_dir = "/opt/awdp/frontend"
# backend/api/v1/admin.py:    upload_dir = "/opt/awdp/frontend/avatars"
# backend/api/v1/admin.py:    upload_dir = "/opt/awdp/frontend/attachments"
# grep: backend/api/v1/__pycache__/api.cpython-312.pyc: binary file matches
# grep: backend/api/v1/__pycache__/admin.cpython-312.pyc: binary file matches
# backend/api/v1/api.py:    upload_dir = "/opt/awdp/frontend/avatars"
# backend/api/v1/api.py:    upload_dir = "/opt/awdp/patches"


```

默认管理员账号：`admin` / `admin`

## 📂 目录结构说明

```text
awdp-matrix/
├── backend/                  # FastAPI 后端核心
│   ├── api/v1/               # 路由层 (选手端 API, 后台 Admin API)
│   ├── core/                 # 核心模块 (数据库、认证、Docker 调度引擎)
│   ├── engine/               # 计分引擎与轮次调度器 (scheduler.py)
│   ├── models/               # SQLAlchemy 数据模型
│   └── main.py               # 应用入口
├── frontend/                 # 前端静态页面 (无 Node.js 构建依赖，开箱即用)
│   ├── index.html            # 选手控制台
│   ├── scoreboard.html       # 实时计分板大屏
│   ├── admin.html            # 裁判/管理员后台
│   └── static/               # CSS / JS / Assets (内置 Vue3 & Element Plus)
├── pwn1_awdp_break_fix/      # 示例赛题目录 (展示如何打包攻击机与Check机)
├── patches/                  # 运行时保存选手上传的防御补丁 (自动生成)
└── init_data.py              # 初始化测试数据的脚本
```

## 🎮 赛题环境制作指南

在 AWDP Matrix 中，每道题需要准备两个 Docker 镜像：
1. **Attack Image (攻击靶机)**：
   正常启动漏洞服务。启动时平台会向其注入 `FLAG` 环境变量，内部脚本需将其写入指定位置（如 `/flag`）。
2. **Check Image (防守检测沙箱)**：
   在 Attack Image 的基础上，安装 Python3 和相关测试库（如 pwntools）。必须在根目录放置平台约定的 `/platform_run.py` 调度脚本。

详细的题目制作与打包示例，请参考目录下的 `pwn1_awdp_break_fix` 文件夹。

## bug 
可能存在很多bug 和漏洞,还没有测，

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
