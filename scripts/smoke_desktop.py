"""Start the actual desktop entrypoint in an isolated data folder."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


def main():
    with tempfile.TemporaryDirectory(prefix='smallcloset desktop ') as d:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        environment={**os.environ,'SM_DATA_DIR':str(Path(d)/'작은옷장 데이터'),'SM_PORT':str(port),'SM_NO_AUTO_OPEN':'1'}
        with tempfile.TemporaryFile() as log:
            process=subprocess.Popen([sys.executable,'-m','smallcloset.desktop'],cwd=ROOT,env=environment,stdout=log,stderr=log)
            try:
                opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for _ in range(100):
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/api/health',timeout=1) as response:
                            if json.load(response)['app']=='smallcloset':break
                    except OSError:pass
                    if process.poll() is not None:raise AssertionError('desktop server exited early')
                    time.sleep(0.1)
                else:raise AssertionError('desktop readiness timed out')
                with opener.open(f'http://127.0.0.1:{port}/api/state') as response:
                    assert json.load(response)['products']==[]
                with opener.open(f'http://127.0.0.1:{port}/') as response:
                    assert '작은옷장' in response.read().decode('utf-8')
                second=subprocess.run([sys.executable,'-m','smallcloset.desktop'],cwd=ROOT,env=environment,capture_output=True,timeout=15)
                assert second.returncode==0
                assert b'already running' in second.stdout
                assert process.poll() is None
                print('PASS: desktop server ready, Korean data path, empty DB, HTML, reuse existing server. No browser was auto-opened during this test.')
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
                if process.returncode not in (0,-15,1):
                    log.seek(0)
                    print(log.read().decode('utf-8',errors='replace')[-2000:])


if __name__=='__main__':main()
