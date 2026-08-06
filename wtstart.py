# -*- coding: utf-8 -*-
"""
启动脚本：读取 env.txt 配置，生成前端 .env，
使用 Windows Terminal 新建标签运行后端、前端
wt.exe 自定义路径：C:\terminal\wt.exe
注意：Ctrl+C 无法自动关闭标签内服务，请手动关闭WT标签页
双击 start.bat 调用本脚本
"""

import os
import sys
import subprocess
import time
from pathlib import Path

_backend_proc = None
_frontend_proc = None

# 【配置】wt.exe 绝对路径，根据你的环境写死
WT_EXE = r"C:\terminal\wt.exe"


def _shutdown():
    """wt模式下无法接管内部进程，仅提示信息"""
    print("\n[Shutdown Notice]")
    print("Since Windows Terminal spawns independent tabs, services cannot be auto terminated.")
    print("Please manually close Backend / Frontend WT tabs.")


# ==================== 读取 env.txt ====================
def read_env_txt(path: str = "env.txt") -> dict:
    config = {}
    p = Path(path)
    if not p.exists():
        print(f"[WARN] {path} not found, using defaults")
        return config
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        config[key.strip()] = value.strip()
    return config


def main():
    global _backend_proc, _frontend_proc

    # 校验wt文件是否存在
    if not Path(WT_EXE).exists():
        print(f"[FATAL] Cannot find Windows Terminal at {WT_EXE}")
        input("Press Enter to exit...")
        sys.exit(1)

    # 切换到脚本所在目录
    os.chdir(Path(__file__).parent)
    root_dir = Path(__file__).parent
    base_dir = str(root_dir)

    print("=" * 50)
    print("  A3 PaperCut Smart Split System - Start (WT Tab Mode)")
    print("=" * 50)
    print()

    # 读取配置
    cfg = read_env_txt("env.txt")

    # 提取配置，设置默认值
    be_host = cfg.get("HOST", "0.0.0.0")
    be_port = cfg.get("PORT", "8000")
    fe_host = cfg.get("FRONTEND_HOST", "0.0.0.0")
    fe_port = cfg.get("FRONTEND_PORT", "5173")
    fe_api = cfg.get("FRONTEND_API_TARGET", f"http://localhost:{be_port}")
    fe_allowed_hosts = cfg.get("FRONTEND_ALLOWED_HOSTS", "hom.my.to,*")

    # 生成前端 .env
    fe_env = (
        f"VITE_HOST={fe_host}\n"
        f"VITE_PORT={fe_port}\n"
        f"VITE_API_TARGET={fe_api}\n"
        f"VITE_ALLOWED_HOSTS={fe_allowed_hosts}\n"
    )
    fe_env_path = root_dir / "frontend/.env"
    fe_env_path.parent.mkdir(parents=True, exist_ok=True)
    fe_env_path.write_text(fe_env, encoding="utf-8")

    print(f"  后端 API:   {be_host}:{be_port}")
    print(f"  前端 WebUI: {fe_host}:{fe_port}")
    print(f"  API 代理:   {fe_api}")
    print()

    # 检查依赖
    venv_python = root_dir / ".venv/Scripts/python.exe"
    if not venv_python.exists():
        print("[ERROR] Virtual environment not found. Please run setup.bat first.")
        input("Press Enter to exit...")
        sys.exit(1)

    frontend_node_modules = root_dir / "frontend/node_modules"
    if not frontend_node_modules.exists():
        print("[ERROR] Frontend dependencies not found. Please run setup.bat first.")
        input("Press Enter to exit...")
        sys.exit(1)

    # 设置环境变量
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "1"
    env["GLOG_minloglevel"] = "2"

    frontend_dir = str(root_dir / "frontend")
    vite_script = str(root_dir / "frontend/node_modules/vite/bin/vite.js")

    # ====================== 启动后端：WT新建标签 ======================
    print("[1/2] Starting backend (FastAPI + PaddleOCR) in new WT tab...")
    backend_command = [
        str(venv_python),
        "-m", "uvicorn",
        "backend.app:app",
        "--host", be_host,
        "--port", be_port
    ]
    cmd_backend = f'cd /d "{base_dir}" && {subprocess.list2cmdline(backend_command)}'
    wt_cmd_backend = f'"{WT_EXE}" --window 0 new-tab --title "Backend API" cmd /k "{cmd_backend}"'

    _backend_proc = subprocess.Popen(
        wt_cmd_backend,
        shell=True,
        cwd=base_dir,
        env=env
    )

    print("Waiting for backend initialization (5s)...")
    time.sleep(5)

    # ====================== 启动前端：WT新建标签 ======================
    print("[2/2] Starting frontend (Vite Dev Server) in new WT tab...")
    frontend_command = [
        "node", vite_script
    ]
    cmd_frontend = f'cd /d "{frontend_dir}" && {subprocess.list2cmdline(frontend_command)}'
    wt_cmd_frontend = f'"{WT_EXE}" --window 0 new-tab --title "Frontend Vite" cmd /k "{cmd_frontend}"'

    _frontend_proc = subprocess.Popen(
        wt_cmd_frontend,
        shell=True,
        cwd=frontend_dir,
        env=env
    )

    print()
    print("=" * 50)
    print("  System launched!")
    print(f"  Frontend:  http://localhost:{fe_port}")
    print(f"  Backend:   http://localhost:{be_port}/docs")
    print(f"  Health:    http://localhost:{be_port}/api/health")
    print("=" * 50)
    print()
    print("⚠️ NOTICE: Ctrl+C CANNOT stop backend/frontend tabs!")
    print("Please manually close WT tabs to shut down services.")
    print("Press Ctrl+C to exit starter script...")
    print()

    try:
        # 阻塞等待，保持启动脚本不关闭
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown()


if __name__ == "__main__":
    main()