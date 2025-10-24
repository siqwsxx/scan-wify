# main.py
import sys
import os
import json
import socket
import platform
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial

from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QUrl, QObject, pyqtSlot, pyqtSignal
from PyQt5.QtWebChannel import QWebChannel

# ---------- utilitários de rede ----------
def get_local_ip():
    """Tenta descobrir o IP local associando a 8.8.8.8 (não envia tráfego)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def ip_from_base_and_offset(base_ip, offset):
    parts = base_ip.split('.')
    parts[-1] = str(offset)
    return '.'.join(parts)

def ping(ip, timeout=1000):
    """Ping a um IP. Retorna True se respondeu. timeout em ms (aplicável no Windows)."""
    plat = platform.system().lower()
    if plat == "windows":
        # -n 1 (1 echo), -w timeout(ms)
        cmd = ["ping", "-n", "1", "-w", str(timeout), ip]
    else:
        # unix: -c 1 (1 packet), -W 1 (timeout em segundos) -> convertemos ms para s arredondando
        t = max(1, int(round(timeout / 1000.0)))
        cmd = ["ping", "-c", "1", "-W", str(t), ip]
    try:
        # suprime output
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return res.returncode == 0
    except Exception:
        return False

def resolve_hostname(ip):
    """Tenta obter hostname via reverse DNS; se falhar, devolve string vazia."""
    try:
        name, _, _ = socket.gethostbyaddr(ip)
        return name
    except Exception:
        return ""

def scan_ip(ip):
    """Scaneia um único IP: ping + hostname."""
    alive = ping(ip, timeout=800)
    if not alive:
        return None
    host = resolve_hostname(ip)
    return {"ip": ip, "hostname": host}

def scan_subnet(base_ip, start=1, end=254, max_workers=80, progress_callback=None):
    """
    Faz scan de base_ip (ex: 192.168.1.100 -> base 192.168.1.*).
    progress_callback(op, data) onde op é 'found' ou 'progress' ou 'done'.
    """
    parts = base_ip.split('.')
    parts[-1] = "0"
    base = '.'.join(parts)
    # Vamos usar o base do host local (substituímos o último octeto pelos offsets)
    base_for_replace = base_ip.rsplit('.', 1)[0] + '.'
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = { ex.submit(scan_ip, base_for_replace + str(i)): i for i in range(start, end + 1) }
        total = end - start + 1
        completed = 0
        for fut in as_completed(futures):
            completed += 1
            try:
                res = fut.result()
            except Exception:
                res = None
            if res:
                results.append(res)
                if progress_callback:
                    progress_callback('found', res)
            if progress_callback:
                progress_callback('progress', {"done": completed, "total": total})
    if progress_callback:
        progress_callback('done', {"count": len(results)})
    return results

# ---------- Bridge Py <-> JS ----------
class Bridge(QObject):
    sendToJs = pyqtSignal(str)  # envia textos (JSON) para o JS

    @pyqtSlot()
    def startScan(self):
        """Slot chamado pelo JS para iniciar o scan."""
        # executa scan e envia eventos progressivamente
        local_ip = get_local_ip()
        # Emite informação inicial
        self.sendToJs.emit(json.dumps({"type": "info", "msg": f"IP local: {local_ip}"}))

        def progress_cb(op, data):
            payload = {"type": None, "data": None}
            if op == 'found':
                payload["type"] = "found"
                payload["data"] = data
            elif op == 'progress':
                payload["type"] = "progress"
                payload["data"] = data
            elif op == 'done':
                payload["type"] = "done"
                payload["data"] = data
            else:
                return
            try:
                self.sendToJs.emit(json.dumps(payload))
            except Exception as e:
                print("Erro a enviar para JS:", e)

        # Faz o scan (bloqueante dentro desta slot, mas a UI continua responsiva
        # porque a chamada vem do thread do Qt; em projetos maiores usar threads explícitos)
        try:
            scan_subnet(local_ip, start=1, end=254, max_workers=120, progress_callback=progress_cb)
        except Exception as e:
            self.sendToJs.emit(json.dumps({"type": "error", "msg": str(e)}))

    @pyqtSlot(str)
    def receiveFromJs(self, msg):
        """Recebe mensagens arbitrárias do JS (para debug)."""
        print("[JS -> PY]", msg)
        self.sendToJs.emit(json.dumps({"type": "info", "msg": f"Python recebeu: {msg}"}))


# ---------- HTML builder ----------
def resource_base_url():
    base = os.path.abspath(os.path.dirname(__file__)) + os.sep
    return QUrl.fromLocalFile(base)

def build_html():
    html = """<!doctype html>
<html lang="pt-PT">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Scanner de Rede - App</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="card">
    <h1>Scanner de Rede</h1>
    <p id="status">Estado: pronto</p>

    <div class="controls">
      <button id="scanBtn">Iniciar Scan da Rede</button>
    </div>

    <div class="progress-bar" id="progressBar" style="display:none;">
      <div id="progressText">0/0</div>
    </div>

    <h3>Dispositivos encontrados</h3>
    <div id="devices" class="messages"></div>
  </div>

  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <script src="script.js"></script>
</body>
</html>
"""
    return html

# ---------- App Qt ----------
def main():
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("Scanner de Rede (PyQt)")
    window.resize(800, 600)

    view = QWebEngineView(window)
    window.setCentralWidget(view)

    bridge = Bridge()
    channel = QWebChannel()
    channel.registerObject('bridge', bridge)
    view.page().setWebChannel(channel)

    html = build_html()
    base = resource_base_url()
    view.setHtml(html, base)

    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
