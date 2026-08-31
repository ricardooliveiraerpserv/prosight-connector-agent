# Prosight — Conectar uma empresa nova (passo a passo)

Guia completo do zero até a integração funcionando. Há **dois cenários** — escolha pelo tipo do Protheus do cliente:

| Cenário | Protheus | O que dá pra fazer | Precisa do agente? |
|---|---|---|---|
| **A) Cloud** (ex.: PROMAX) | TOTVS Cloud | **Inventário RPO** (comparar fonte × RPO) | ❌ Não |
| **B) On-premise** (ex.: Comlub) | Servidor do cliente | Inventário + **operar** (start/stop/restart, RPO, patch) | ✅ Sim (executável) |

---

## PARTE 1 — Comum aos dois (no Minutor)

Login como **admin** → menu **Prosight**.

### 1.1 Selecionar/confirmar a empresa
- No **seletor global** (topo) escolha a empresa (tem **busca por texto**). Se não existir, ela precisa estar cadastrada como cliente (Central de Fontes/Cadastros).

### 1.2 Cadastrar o ambiente
- **Configuração → sub-aba "Prosight" → seção "Connector (agente por ambiente)"** → **"Cadastrar ambiente"** → nome (ex.: `Produção`) + tipo.
- (Se a empresa nunca teve vault: o 1º cadastro pede o **bootstrap do vault** no Cofre — uma vez só.)

### 1.3 Configurar o repositório Git (fontes)
- **Configuração → Prosight → "Repositórios Git da empresa"** → URL do repo + branch + token (se privado). Salvar.

### 1.4 Configurar o RPO (REST AdvPL)
- **Configuração → Prosight → "Integração RPO (REST AdvPL)"** → escolha o ambiente e preencha:
  - **URL do endpoint AdvPL** (ex.: `https://servidor:4050/rest/PROSIGHTREST/prosight/rpo-inventory`)
  - **Usuário** e **Senha** REST AdvPL
  - **Padrões de exclusão** (ex.: `._*,TEST*,_BINA*,*TST*`)
- Clique **Testar API** → deve dar "Conexão AdvPL ok".
- Clique **Gerar inventário** → aparece o dashboard (saúde, donut, cards clicáveis, Exportar Excel).

> **Cliente CLOUD (PROMAX) para aqui** — o inventário é o entregável. Operar serviços/RPO exige agente on-prem (não se aplica a cloud).

---

## PARTE 2 — Só ON-PREMISE (instalar o agente / executável)

### 2.1 Obter o executável
O agente vira um `prosight-connector.exe` (Windows). Como gerar:

**Opção A — GitHub Actions (recomendado):** com o repo `prosight-connector-agent` no GitHub, o workflow `.github/workflows/build-exe.yml` builda o `.exe` num runner Windows → baixe em **Actions → run → Artifacts**.

**Opção B — numa máquina Windows:**
```bat
pip install pyinstaller cryptography
pyinstaller prosight-connector.spec
:: sai em dist\prosight-connector.exe
```

**Opção C — sem .exe:** instalar Python 3.8+ no cliente e rodar o `.py` (`pip install -r requirements.txt`).

### 2.2 Instalar na máquina do Protheus
- Copie a pasta (com `prosight-connector.exe` + `totvs.py` + `config.example.json`) para ex. `C:\Prosight\`.
- Copie `config.example.json` → `config.json` e preencha a seção **`totvs`**:
  ```json
  {
    "base": "https://minutor-backend-homolog.onrender.com/api/v1",
    "totvs": {
      "appserver_ini": "D:\\TOTVS\\...\\appserver.ini",
      "rpo_glob": "D:\\TOTVS\\...\\apo\\*.rpo",
      "service_prefix": "Protheus_"
    }
  }
  ```
- **Confira a descoberta** (dry-run, não conecta): `prosight-connector.exe discover` → deve listar os AppServers reais.

### 2.3 Gerar o token e conectar
- No Minutor: **Configuração → Prosight → Connector** → escolha o ambiente → **"Gerar token de conexão"** (aparece uma vez, copie).
- Na máquina do cliente:
  ```bat
  prosight-connector.exe enroll --token <TOKEN>
  prosight-connector.exe run
  ```
- Instale como **serviço do Windows** (NSSM/Agendador — ver `INSTALL-ONPREM.md`) para ficar sempre no ar.

### 2.4 Fechar a jornada (4 de 4)
No Minutor, na seção **"Integração Protheus (Connector · AppServers · RPO)"**:
1. **Connector online** → ✅ assim que o heartbeat chega.
2. **AppServers vinculados** → em "Detectados não vinculados", clique **"Registrar e vincular"** em cada um (cria o cadastral a partir do detectado e vincula — **sem digitar nada**).
3. **RPO confirmado** → confirme o Target na seção RPO / **Operações RPO**.

Jornada em **4 de 4 · pronto** → aí a aba **Operação** (start/stop/restart, compilação, patch) fica ativa para o ambiente.

---

## Resumo rápido
- **Toda empresa:** empresa → ambiente → Git → RPO REST → inventário. (Configuração → Prosight)
- **Cloud:** para aqui (só inventário).
- **On-prem:** + instalar o `.exe`, `config.json`, gerar token, `enroll`+`run`, registrar e vincular AppServers, confirmar RPO.
- **Executável:** `prosight-connector.exe` (build via GitHub Actions ou Windows; ou rodar o `.py` com Python).
