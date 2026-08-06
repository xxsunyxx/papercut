# -*- coding: utf-8 -*-
"""
启动脚本：读取 env.txt 配置，生成前端 .env，然后启动后端和前端服务
双击 start.bat 即会调用本脚本
"""

import os
import sys
import subprocess
import time
from pathlib import Path

# 全局进程引用，用于优雅关闭
_backend_proc = None
_frontend_proc = None


def _shutdown():
    """终止所有子进程"""
    global _backend_proc, _frontend_proc
    print("\n[Shutdown] Stopping services...")
    for name, proc in [("Backend", _backend_proc), ("Frontend", _frontend_proc)]:
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
                print(f"  {name} stopped.")
            except Exception:
                try:
                    proc.kill()
                    print(f"  {name} killed.")
                except Exception:
                    pass
    print("All services stopped.")


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

    # 切换到脚本所在目录
    os.chdir(Path(__file__).parent)

    print("=" * 50)
    print("  A3 PaperCut Smart Split System - Start")
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
    fe_env_path = Path("frontend/.env")
    fe_env_path.parent.mkdir(parents=True, exist_ok=True)
    fe_env_path.write_text(fe_env, encoding="utf-8")

    print(f"  后端 API:   {be_host}:{be_port}")
    print(f"  前端 WebUI: {fe_host}:{fe_port}")
    print(f"  API 代理:   {fe_api}")
    print()

    # 检查依赖
    if not Path(".venv/Scripts/python.exe").exists():
        print("[ERROR] Virtual environment not found. Please run setup.bat first.")
        input("Press Enter to exit...")
        sys.exit(1)

    if not Path("frontend/node_modules").exists():
        print("[ERROR] Frontend dependencies not found. Please run setup.bat first.")
        input("Press Enter to exit...")
        sys.exit(1)

    # 设置环境变量
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = "1"
    env["GLOG_minloglevel"] = "2"

    base_dir = str(Path(__file__).parent)

    # 启动后端（新窗口）
    print("[1/2] Starting backend (FastAPI + PaddleOCR)...")
    _backend_proc = subprocess.Popen(
        [".venv/Scripts/python.exe", "-m", "uvicorn",
         "backend.app:app", "--host", be_host, "--port", be_port],
        cwd=base_dir,
        env=env,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )

    # 等待后端启动
    print("[2/2] Waiting for backend to start (5s)...")
    time.sleep(5)

    # 启动前端（新窗口）
    print("[2/2] Starting frontend (Vite Dev Server)...")
    frontend_dir = str(Path(__file__).parent / "frontend")
    # 使用 node 直接调用 vite，避免 npm 在 PATH 中找不到的问题
    vite_script = str(Path(frontend_dir) / "node_modules" / "vite" / "bin" / "vite.js")
    _frontend_proc = subprocess.Popen(
        ["cmd", "/k", "node", vite_script],
        cwd=frontend_dir,
        env=env,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )

    print()
    print("=" * 50)
    print("  System started!")
    print(f"  Frontend:  http://localhost:{fe_port}")
    print(f"  Backend:   http://localhost:{be_port}/docs")
    print(f"  Health:    http://localhost:{be_port}/api/health")
    print("=" * 50)
    print()
    print("Press Ctrl+C to stop all services...")
    print()

    try:
        # 等待后端进程结束
        _backend_proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown()


if __name__ == "__main__":
    main()
