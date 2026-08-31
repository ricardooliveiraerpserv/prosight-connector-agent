# Prosight Connector — Instalação on-prem (na máquina do cliente)

Guia para instalar o agente **na máquina on-prem** onde roda o Protheus (geralmente Windows).
O agente conecta **outbound** ao Minutor (só HTTPS de saída) — não precisa abrir porta de entrada.

## Pré-requisitos
- Acesso de saída HTTPS ao endpoint do Minutor (ex.: `https://minutor-backend-homolog.onrender.com`).
- **Ou** Python 3.8+ instalado, **ou** o executável `prosight-connector.exe` (não exige Python).

---

## Opção 1 — Executável (.exe) — recomendado p/ cliente (sem Python)

O `.exe` precisa ser **gerado numa máquina Windows** (PyInstaller é por-plataforma):
```bat
pip install pyinstaller cryptography
pyinstaller prosight-connector.spec
:: sai em dist\prosight-connector.exe
```
Copie `dist\prosight-connector.exe` + `config.json` para a máquina do cliente (ex.: `C:\Prosight\`).

## Opção 2 — Python
```bat
:: na máquina do cliente
python -m pip install -r requirements.txt
```

---

## Passo a passo

1. **Configurar os AppServers reais** — copie `config.example.json` → `config.json` e liste os AppServers deste ambiente:
   ```json
   {
     "base": "https://minutor-backend-homolog.onrender.com/api/v1",
     "appservers": [
       { "name": "PROMAX_PROD_01", "version": "12.1.2410", "build": "9999", "patch": "12" },
       { "name": "PROMAX_PROD_02", "version": "12.1.2410", "build": "9999", "patch": "12" }
     ]
   }
   ```

2. **Gerar o token** no Minutor: Prosight → Configuração → empresa/ambiente → Connector → **Gerar token de conexão**.

3. **Enrolar** (uma vez):
   ```bat
   prosight-connector.exe enroll --token <TOKEN>       :: (.exe)
   python prosight_connector.py enroll --token <TOKEN> :: (Python)
   ```
   Cria `state.json` (identidade Ed25519 + AppServers). **Guarde/backupe** — a chave privada fica só aqui.

4. **Rodar** (loop contínuo): `prosight-connector.exe run` → o ambiente fica **online**, reporta AppServers e atende comandos/operações.

---

## Rodar como serviço do Windows (fica sempre no ar)

### Via NSSM (recomendado)
```bat
nssm install ProsightConnector "C:\Prosight\prosight-connector.exe" run
nssm set ProsightConnector AppDirectory "C:\Prosight"
nssm set ProsightConnector Start SERVICE_AUTO_START
nssm start ProsightConnector
```

### Via Agendador de Tarefas
Crie uma tarefa "Ao iniciar o computador" que execute `C:\Prosight\prosight-connector.exe run` com "Reiniciar em caso de falha".

---

## Completar a jornada no Minutor (fica 100%)
Com o agente rodando, em **Prosight → Configuração → Connector**:
1. **Connector online** ✅ (assim que o heartbeat chega)
2. **AppServers vinculados** → o agente reporta; você confirma o vínculo dos AppServers detectados
3. **RPO confirmado** → confirme o Target na seção RPO / Operações RPO

---

## Camada TOTVS — descoberta e execução FÍSICA (`totvs.py`)
Com a seção `totvs` no `config.json`, o agente passa a usar dados **reais** da máquina:
- **Descoberta de AppServers**: lê o `appserver.ini` (nomes + portas).
- **Up/down real**: conexão TCP na porta de cada AppServer.
- **RPO real**: `sha256` do arquivo `.rpo` do disco (mesmo hash por publish unit → target consistente).
- **Start/stop/restart real**: controla o **serviço Windows** (`sc stop/start`, nome = `service_prefix` + AppServer).

Sem a seção `totvs`, o agente cai na lista manual de `appservers` (nomes declarados).

### O que ainda precisa de ajuste/validação numa máquina Protheus real
- **Convenção do `appserver.ini`**: a heurística "seção com Port = AppServer" pode pegar seções que não são AppServer (ex.: `[TCP]` do listener principal). Ajustar o filtro/glob conforme o `appserver.ini` real do cliente.
- **Serviço Windows**: o nome do serviço (`service_prefix`) e o start/stop só rodam/valida **no Windows** com o AppServer instalado como serviço.
- **Localização do `.rpo`**: confirmar o `rpo_glob` conforme a estrutura do cliente.
- **Patch físico**: continua no-op no protocolo; a aplicação física do patch no RPO é a integração TOTVS a plugar.

> A lógica de parsing/porta/hash é validada em qualquer SO (`python test_totvs.py`). A execução de serviço e a validação ponta-a-ponta exigem a máquina Protheus/Windows real.
