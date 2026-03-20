#!/usr/bin/env python3
import os
import sys
import tarfile
import re
import subprocess
import shutil

# 定义状态码常量
EXIT_SUCCESS = 0       # 防御成功
EXIT_SERVICE_DOWN = 1  # 服务异常 (把题修坏了)
EXIT_EXPLOIT_OK = 2    # EXP依然能打通 (没防住)
EXIT_ILLEGAL = 3       # 非法脚本或文件错误

PATCH_DIR = "/tmp/patch_env"

def print_log(msg):
    # 将日志输出到 stderr，避免污染 stdout (虽然平台目前主要看 exit code)
    print(f"[Platform Run] {msg}", file=sys.stderr)

def main():
    if len(sys.argv) < 2:
        print_log("Usage: python3 platform_run.py <path_to_update.tar.gz>")
        sys.exit(EXIT_ILLEGAL)

    tar_path = sys.argv[1]
    
    if not os.path.exists(tar_path):
        print_log(f"Error: {tar_path} not found.")
        sys.exit(EXIT_ILLEGAL)

    # 1. 创建临时解压目录并解压
    if os.path.exists(PATCH_DIR):
        shutil.rmtree(PATCH_DIR)
    os.makedirs(PATCH_DIR, exist_ok=True)

    print_log(f"Extracting {tar_path} to {PATCH_DIR}...")
    try:
        with tarfile.open(tar_path, "r:gz") as tar:
            # 简单的防目录穿越保护
            for member in tar.getmembers():
                if member.name.startswith('/') or '..' in member.name:
                    print_log("Illegal file path in tarball.")
                    sys.exit(EXIT_ILLEGAL)
            tar.extractall(path=PATCH_DIR)
    except Exception as e:
        print_log(f"Failed to extract tarball: {e}")
        sys.exit(EXIT_ILLEGAL)

    run_sh_path = os.path.join(PATCH_DIR, "run.sh")
    if not os.path.exists(run_sh_path):
        print_log("Error: run.sh not found in the tarball.")
        sys.exit(EXIT_ILLEGAL)

    # 2. 白名单解析 run.sh
    print_log("Parsing run.sh for whitelist validation...")
    valid_commands = []
    try:
        with open(run_sh_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                # 忽略空行和注释
                if not line or line.startswith('#'):
                    continue
                
                # 白名单正则：必须以 cp 或 mv 开头，中间至少一个空格，后面跟参数
                # 为了防止 &&, ;, | 等命令注入，禁止这些特殊字符
                if re.search(r'[&;|><$]', line):
                    print_log(f"Line {line_num} contains illegal characters: {line}")
                    sys.exit(EXIT_ILLEGAL)
                    
                if not re.match(r'^(cp|mv)\s+', line):
                    print_log(f"Line {line_num} contains non-whitelisted command: {line}")
                    sys.exit(EXIT_ILLEGAL)
                
                valid_commands.append(line)
    except Exception as e:
        print_log(f"Failed to read run.sh: {e}")
        sys.exit(EXIT_ILLEGAL)

    # 3. 安全执行替换命令
    print_log("Executing approved commands...")
    # 切换到解压目录，保证 run.sh 里的相对路径 (如 cp fix_pwn ...) 正确
    os.chdir(PATCH_DIR) 
    for cmd in valid_commands:
        print_log(f"Executing: {cmd}")
        # 使用 subprocess.run 执行，shell=True 因为已经过滤了特殊字符
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print_log(f"Command failed: {cmd}\nError: {result.stderr}")
            # 执行失败通常意味着选手写错了路径，也算作失败
            sys.exit(EXIT_ILLEGAL)

    # 对于 PWN 题，修改完文件后，可能需要给执行权限
    # 这一步平台可以帮忙兜底，或者出题人在这里写死
    if os.path.exists("/home/ctf/pwn"):
        os.system("chmod +x /home/ctf/pwn")

    # 4. 调用 check_pwn.py 进行最终验证
    print_log("Starting check_pwn.py...")
    # 假设 check_pwn.py 放在容器的根目录 (根据 Dockerfile COPY ./files/check_pwn.py /)
    check_script = "/check_pwn.py"
    if not os.path.exists(check_script):
        print_log("Error: check_pwn.py not found in the container.")
        sys.exit(EXIT_ILLEGAL)

    # 运行 check_pwn.py 并获取其退出码
    result = subprocess.run(["python3", check_script], capture_output=True, text=True)
    
    print_log(f"check_pwn.py stdout:\n{result.stdout}")
    print_log(f"check_pwn.py stderr:\n{result.stderr}")
    print_log(f"check_pwn.py returned code: {result.returncode}")

    # 将 check_pwn.py 的退出码原样返回给外部平台
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
