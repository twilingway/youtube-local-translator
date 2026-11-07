"""Own a project-local, loopback CUDA Qwen3-TTS server with no network models."""
import base64,io,json,secrets,socket,subprocess,time
from pathlib import Path
import httpx
import soundfile as sf
from .config import ROOT

class NativeTTSClient:
    def __init__(self,token=None,port=8767):
        token=token or (ROOT/'.runtime/tts-native/session.key').read_text(encoding='utf-8').strip()
        self.client=httpx.Client(base_url=f'http://127.0.0.1:{port}',headers={'Authorization':'Bearer '+token,'Origin':'http://127.0.0.1:8765'},trust_env=False,timeout=httpx.Timeout(25,connect=2))

    def synthesize(self,text,reference,seed=20261106):
        result=self.client.post('/tts',json={'input':text,'lang':'ru','speaker_ref_b64':base64.b64encode(reference).decode(),
            'seed':seed,'n_predict':512,'response_format':'wav','stream':False})
        result.raise_for_status();audio,rate=sf.read(io.BytesIO(result.content),dtype='float32')
        import numpy as np
        if audio.ndim>1:audio=audio.mean(axis=1)
        if not np.all(np.isfinite(audio)) or len(audio)<rate*.15 or np.max(np.abs(audio))<.001:
            raise ValueError('Qwen returned empty or invalid speech')
        return audio,rate

    def close(self):self.client.close()

class NativeTTS(NativeTTSClient):
    def __init__(self,log_path,port=8767):
        source=json.loads((ROOT/'reports/native-tts-sources.json').read_text())
        runtime=Path(source['runtime']);model=ROOT/'models/qwen3-tts-gguf/Qwen3-TTS-12Hz-1.7B-Base-Q8_0.gguf'
        with socket.socket() as check:check.bind(('127.0.0.1',port))
        token=secrets.token_urlsafe(32);keyfile=ROOT/'.runtime/tts-native/session.key';keyfile.write_text(token,encoding='utf-8')
        self.log=Path(log_path).open('w',encoding='utf-8');self.process=None
        super().__init__(token,port)
        try:
            self.process=subprocess.Popen([str(runtime/'llama-server.exe'),'-m',str(model),'--mmproj',str(model.parent/'mmproj-Qwen3-TTS-12Hz-1.7B-Base-bf16.gguf'),
                '-ngl','999','--flash-attn','on','--ctx-size','2048','--parallel','1','--host','127.0.0.1','--port',str(port),'--no-webui',
                '--api-key-file',str(keyfile),'--cors-origins','http://127.0.0.1:8765'],cwd=runtime,stdout=self.log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            for _ in range(120):
                if self.process.poll() is not None:raise RuntimeError('Native TTS exited; inspect its local log')
                try:
                    if self.client.get('/health',timeout=1).status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(1)
            else:raise TimeoutError('Native TTS startup timeout')
        except Exception:self.close();raise
    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(10)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(5)
        self.client.close();self.log.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
