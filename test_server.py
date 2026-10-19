#!/usr/bin/env python
"""Test script to start server and verify it works."""
import asyncio
import subprocess
import time
import sys
import os
import requests

def test_server():
    # Set up environment - explicitly unset DATABASE_URL to use .env
    venv_python = "/Users/hidekinishida/Documents/Projetos/Agente de IA Local/.venv/bin/python"
    project_dir = "/Users/hidekinishida/Documents/Projetos/Agente de IA Local"
    src_dir = "/Users/hidekinishida/Documents/Projetos/Agente de IA Local/src"
    env = os.environ.copy()
    env["PYTHONPATH"] = src_dir
    # Remove DATABASE_URL from env so .env file takes effect
    env.pop("DATABASE_URL", None)
    
    # First verify config is loaded
    result = subprocess.run([
        venv_python, "-c", 
        "from agent.config import get_settings; s = get_settings(); print('database_url:', s.database_url); print('resolved_database_url:', s.resolved_database_url())"
    ], cwd=project_dir, env=env, capture_output=True, text=True)
    print("Config test:")
    print(result.stdout)
    print(result.stderr)
    
    # Start the server
    proc = subprocess.Popen([
        venv_python, "-m", "uvicorn", "agent.api.main:app",
        "--host", "127.0.0.1", "--port", "8765"
    ], cwd=project_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    
    # Wait for server to start
    time.sleep(5)
    
    # Test health endpoint
    try:
        resp = requests.get("http://127.0.0.1:8765/health", timeout=5)
        print(f"Health check: {resp.status_code} - {resp.json()}")
        success = resp.status_code == 200
    except Exception as e:
        print(f"Health check failed: {e}")
        success = False
    
    # Get server logs
    try:
        stdout, stderr = proc.communicate(timeout=2)
        print(f"STDOUT:\n{stdout.decode()}")
        print(f"STDERR:\n{stderr.decode()}")
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        print(f"STDOUT:\n{stdout.decode()}")
        print(f"STDERR:\n{stderr.decode()}")
    
    return success

if __name__ == "__main__":
    result = test_server()
    sys.exit(0 if result else 1)