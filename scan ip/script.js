// script.js
document.addEventListener('DOMContentLoaded', function() {
    const scanBtn = document.getElementById('scanBtn');
    const status = document.getElementById('status');
    const devices = document.getElementById('devices');
    const progressBar = document.getElementById('progressBar');
    const progressText = document.getElementById('progressText');

    function addDevice(obj) {
        const el = document.createElement('div');
        el.className = 'device';
        const left = document.createElement('div');
        left.className = 'left';
        const ip = document.createElement('div');
        ip.className = 'ip';
        ip.textContent = obj.ip;
        const host = document.createElement('div');
        host.className = 'host';
        host.textContent = obj.hostname ? obj.hostname : '(hostname não encontrado)';
        left.appendChild(ip);
        left.appendChild(host);

        const right = document.createElement('div');
        right.className = 'right';
        right.textContent = 'visto agora';

        el.appendChild(left);
        el.appendChild(right);
        devices.appendChild(el);
        devices.scrollTop = devices.scrollHeight;
    }

    function setStatus(txt) {
        status.textContent = 'Estado: ' + txt;
    }

    if (typeof QWebChannel === 'undefined') {
        setStatus('QWebChannel não encontrado — executa com PyQt WebEngine.');
        return;
    }

    new QWebChannel(qt.webChannelTransport, function(channel) {
        window.bridge = channel.objects.bridge;

        // recibe mensagens do Python via signal sendToJs
        if (window.bridge.sendToJs.connect) {
            window.bridge.sendToJs.connect(function(payload) {
                try {
                    const obj = JSON.parse(payload);
                    if (obj.type === 'info') {
                        setStatus(obj.msg);
                    } else if (obj.type === 'found') {
                        addDevice(obj.data);
                        setStatus('Encontrado ' + obj.data.ip);
                    } else if (obj.type === 'progress') {
                        progressBar.style.display = 'block';
                        progressText.textContent = `${obj.data.done}/${obj.data.total}`;
                    } else if (obj.type === 'done') {
                        setStatus(`Scan terminado — ${obj.data.count} dispositivo(s) encontrados`);
                        progressBar.style.display = 'none';
                    } else if (obj.type === 'error') {
                        setStatus('Erro: ' + obj.msg);
                        progressBar.style.display = 'none';
                    } else {
                        console.log('Mensagem:', obj);
                    }
                } catch (e) {
                    console.log('Payload não JSON:', payload);
                }
            });
        }

        scanBtn.addEventListener('click', function() {
            // limpa anterior
            devices.innerHTML = '';
            setStatus('A iniciar scan...');
            progressBar.style.display = 'block';
            progressText.textContent = '0/0';
            // chama slot Python startScan
            if (window.bridge && window.bridge.startScan) {
                window.bridge.startScan();
            } else {
                setStatus('bridge.startScan não disponível');
            }
        });
    });
});