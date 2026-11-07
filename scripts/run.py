"""Own only this project's Ollama and uvicorn children; no system installation."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
import psutil

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from service.config import config
os.chdir(ROOT)
use_qwen=config().get('tts_backend','silero')=='qwen-native'
for port in ((8765,11439,8767) if use_qwen else (8765,11439)):
    with socket.socket() as check:
        try: check.bind(('127.0.0.1',port))
        except OSError: raise SystemExit(f'Порт {port} занят. Посторонний процесс не остановлен.')

profile=ROOT/'.runtime/ollama-profile'
profile.mkdir(parents=True,exist_ok=True)
env=dict(os.environ)
env.update(HF_HOME=str(ROOT/'models/huggingface'),TORCH_HOME=str(ROOT/'models/torch'),
           HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OLLAMA_HOST='127.0.0.1:11439',
           OLLAMA_MODELS=str(ROOT/'models/ollama'),OLLAMA_NO_CLOUD='1',
           OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_NUM_PARALLEL='1',OLLAMA_CONTEXT_LENGTH='2048',OLLAMA_KEEP_ALIVE='-1',
           OLLAMA_DEBUG_LOG_REQUESTS='0',OLLAMA_NOHISTORY='1')
# Ollama unconditionally creates a key under os.UserHomeDir(). Scope that home to
# its child process without changing the user's environment or existing config.
ollama_env={**env,'USERPROFILE':str(profile)}
children=[]
descendants={}
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
log=(ROOT/'reports/ollama.log').open('w',encoding='utf-8')
native=None
try:
    if use_qwen:
        from service.native_tts import NativeTTS
        print('Загрузка Qwen Base CUDA…',flush=True)
        native=NativeTTS(ROOT/'reports/native-tts-service.log')
        children.append(native.process)
    child=subprocess.Popen([str(ROOT/'.runtime/ollama/ollama.exe'),'serve'],env=ollama_env,
        stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
    children.append(child)
    child=subprocess.Popen([sys.executable,'-m','uvicorn','service.app:app','--host','127.0.0.1',
        '--port','8765','--ws-max-size','524288','--no-access-log'],env=env)
    children.append(child)
    print('Сервис: 127.0.0.1:8765; Ollama: 127.0.0.1:11439. Ctrl+C — остановка.',flush=True)
    while all(p.poll() is None for p in children):
        for proc in psutil.Process().children(recursive=True):
            try:descendants[(proc.pid,proc.create_time())]=proc
            except psutil.NoSuchProcess:pass
        time.sleep(.5)
except KeyboardInterrupt:
    print('Остановка процессов проекта…',flush=True)
finally:
    owned=[]
    for p in children:
        if p.poll() is None:
            try:
                proc=psutil.Process(p.pid)
                owned.extend(proc.children(recursive=True));owned.append(proc)
            except psutil.NoSuchProcess:pass
    # The uvicorn worker can exit before its CPU worker; keep the identities
    # observed while they were descendants, without touching unknown PIDs.
    for (pid,created),proc in descendants.items():
        try:
            if proc.is_running() and proc.create_time()==created:owned.append(proc)
        except psutil.NoSuchProcess:pass
    owned=list({p.pid:p for p in owned}.values())
    for proc in reversed(owned):
        try:proc.terminate()
        except psutil.NoSuchProcess:pass
    _,remaining=psutil.wait_procs(owned,timeout=5)
    for proc in remaining:
        try:proc.kill()
        except psutil.NoSuchProcess:pass
    if native:native.close()
    log.close()
