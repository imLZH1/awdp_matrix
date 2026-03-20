import docker
import socket
import uuid
import asyncio
import os
import tarfile

def get_host_ip():
    try:
        # 获取本机对外的IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

client = docker.from_env()

def start_attack_container(image_name: str, flag_str: str):
    """
    启动攻击靶机并注入 FLAG
    """
    container = client.containers.run(
        image=image_name,
        detach=True,
        environment={"FLAG": flag_str},
        publish_all_ports=True  # 自动映射内部 EXPOSE 的所有端口到主机的随机端口
    )
    
    # 重新加载容器以获取分配的端口
    container.reload()
    ports = container.attrs['NetworkSettings']['Ports']
    
    mapped_port = None
    if ports:
        # 找到第一个被映射的端口
        for internal_port, bindings in ports.items():
            if bindings:
                mapped_port = bindings[0]['HostPort']
                break
                
    host_ip = get_host_ip()
    conn_info = f"{host_ip}:{mapped_port}" if mapped_port else "No Port Exposed"
    
    return container.id, conn_info

def stop_and_remove_container(container_id: str):
    """
    停止并删除容器
    """
    try:
        container = client.containers.get(container_id)
        container.stop(timeout=2)
        container.remove()
    except docker.errors.NotFound:
        pass
    except Exception as e:
        print(f"Error stopping container {container_id}: {e}")

async def run_defense_check(check_image: str, patch_file_path: str, timeout: int = 30) -> tuple[int, str]:
    """
    运行防御验证容器，解耦架构：
    平台仅注入 update.tar.gz 并执行 /platform_run.py。
    
    返回: (状态码, 日志信息/错误原因)
    状态码约定:
    0: 防御成功 (Defense Success)
    1: 服务异常 (Service Down)
    2: 漏洞未修复 (Exploit Success)
    3: 非法脚本 (Illegal Script)
    -1: 平台执行出错或超时
    """
    task_uuid = uuid.uuid4().hex
    container_name = f"awdp_check_{task_uuid}"
    container = None
    
    try:
        # 1. 启动 Check 沙箱容器 (无外网，注入随机测试 FLAG 防止 EXP 找不到目标报错)
        test_flag = f"flag{{{uuid.uuid4().hex}}}"
        container = client.containers.run(
            image=check_image,
            name=container_name,
            detach=True,
            network_mode='none',
            environment={"FLAG": test_flag},
            mem_limit='256m',
            cpu_period=100000,
            cpu_quota=50000, # 0.5 核
        )
        
        # 2. 将 update.tar.gz 拷贝到容器内
        # docker sdk 并没有直接的 cp file to container，只能通过 tar 归档传输
        # 所以我们需要把 patch_file_path 再包一层 tar 发送进去，或者使用 os.system 调用原生 docker cp
        import subprocess
        cp_result = subprocess.run(["docker", "cp", patch_file_path, f"{container_name}:/tmp/update.tar.gz"], capture_output=True, text=True)
        if cp_result.returncode != 0:
            return -1, f"Failed to inject patch file into container: {cp_result.stderr}"
            
        # 3. 执行容器内的平台统一入口脚本
        exec_cmd = "python3 /platform_run.py /tmp/update.tar.gz"
        exec_id = client.api.exec_create(container.id, cmd=exec_cmd, stdout=True, stderr=True)
        
        # 异步等待执行完成 (自己实现一个简单的轮询等待，避免阻塞主线程)
        exec_stream = client.api.exec_start(exec_id['Id'], detach=False, stream=True)
        
        logs = []
        for chunk in exec_stream:
            logs.append(chunk.decode('utf-8', errors='replace'))
            
        # 获取执行结果
        exec_inspect = client.api.exec_inspect(exec_id['Id'])
        exit_code = exec_inspect['ExitCode']
        
        full_logs = "".join(logs)
        
        if exit_code in [0, 1, 2, 3]:
            return exit_code, full_logs
        else:
            return -1, f"Unknown Exit Code {exit_code} from platform_run.py.\nLogs:\n{full_logs}"
            
    except docker.errors.ImageNotFound:
        return -1, f"系统错误: Check 镜像 {check_image} 不存在，请联系裁判。"
    except Exception as e:
        return -1, f"系统错误: 容器调度失败: {str(e)}"
    finally:
        # 4. 清理容器
        if container:
            try:
                container.remove(force=True)
            except:
                pass
