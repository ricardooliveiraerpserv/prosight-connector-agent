# Prosight Connector — Instalação no Linux (systemd)

O agente é o mesmo dos dois SOs. No Linux ele roda como **serviço systemd** e controla os
AppServers Protheus via `systemctl`. Requisitos: **Python 3.8+** (ou o binário Linux do Release).

## 1. Instalar

```bash
sudo mkdir -p /opt/prosight-connector
cd /opt/prosight-connector

# Opção A — binário do Release (sem Python):
#   baixe prosight-connector-linux, torne executável
sudo curl -L -o prosight-connector <URL_DO_BINARIO_LINUX>
sudo chmod +x prosight-connector

# Opção B — fonte Python:
sudo cp prosight_connector.py totvs.py requirements.txt config.example.json /opt/prosight-connector/
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
```

## 2. Configurar

```bash
sudo cp config.example.json config.json
sudo nano config.json
```
Preencha a seção `totvs` com caminhos Linux:
```json
"totvs": {
  "appserver_ini": "/totvs/protheus/appserver.ini",
  "rpo_glob": "/totvs/protheus/apo/*.rpo",
  "host": "127.0.0.1",
  "service_prefix": "protheus_",
  "service_manager": "systemd"
}
```
> A **unit** de cada AppServer = `service_prefix` + nome do AppServer (ex.: `protheus_APP01` → `systemctl start protheus_APP01.service`). Ajuste `service_prefix` ao nome real das units do cliente.

Teste a descoberta (não conecta):
```bash
./prosight-connector discover        # binário
# ou: python3 prosight_connector.py discover
```

## 3. Conectar (enroll)

Gere o token no Minutor (Configuração → Prosight → Connector → **Gerar token**) e:
```bash
./prosight-connector enroll --token <TOKEN>
```

## 4. Rodar como serviço systemd

Crie `/etc/systemd/system/prosight-connector.service`:
```ini
[Unit]
Description=Prosight Connector Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/prosight-connector
# binário:
ExecStart=/opt/prosight-connector/prosight-connector run
# (fonte Python: ExecStart=/opt/prosight-connector/.venv/bin/python prosight_connector.py run)
Restart=always
RestartSec=10
# Precisa controlar as units do Protheus. Rodar como root é o mais simples:
User=root

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now prosight-connector
sudo systemctl status prosight-connector
journalctl -u prosight-connector -f      # logs ao vivo
```

## 5. Permissão para controlar o Protheus (sem rodar como root)

Se preferir um usuário dedicado em vez de `root`, dê a ele só o controle das units Protheus via sudoers:
```
# /etc/sudoers.d/prosight-connector
prosight ALL=(root) NOPASSWD: /usr/bin/systemctl start protheus_*, /usr/bin/systemctl stop protheus_*, /usr/bin/systemctl restart protheus_*
```
E ajuste o `ExecStart`/`control_service` para usar `sudo systemctl` (ou mantenha `User=root`).

## Notas
- **Outbound-only:** o agente só faz conexões de saída para o Minutor (HTTPS). Nenhuma porta é aberta.
- **Nenhum caminho/segredo trafega:** só nomes de AppServer, portas up/down e hash do RPO.
- Para atualizar: pare o serviço, troque o binário/fonte, `daemon-reload` e `start`.
