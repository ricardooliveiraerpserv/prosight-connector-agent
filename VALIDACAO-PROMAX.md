# Checklist de validação — Prosight Connector na máquina da PROMAX

Rodar **na máquina on-prem** onde está o Protheus (Windows). Objetivo: afinar a descoberta
(`appserver.ini`/RPO/serviço) e confirmar cada capacidade até a jornada ficar **4/4**.

> Marque cada item. Onde der diferente do esperado, **anote e me envie** — ajusto o agente.

---

## 0. Pré-requisitos
- [ ] Saída HTTPS liberada para o Minutor (`https://minutor-backend-homolog.onrender.com`).
- [ ] `prosight-connector.exe` (ou Python 3.8+ com `pip install -r requirements.txt`) + `totvs.py` na mesma pasta.
- [ ] Caminho do `appserver.ini` e da pasta do `.rpo` conhecidos.
- [ ] Usuário com permissão para **parar/iniciar o serviço** do AppServer (só para os testes 7).

## 1. Configurar `config.json`
- [ ] Copiar `config.example.json` → `config.json`.
- [ ] Preencher `totvs.appserver_ini` com o caminho real do `appserver.ini`.
- [ ] Preencher `totvs.rpo_glob` (ex.: `D:\TOTVS\...\apo\*.rpo`) e `service_prefix` (prefixo do serviço Windows).

## 2. Validar a DESCOBERTA (dry-run — não conecta nada)
```bat
prosight-connector.exe discover
```
- [ ] A lista mostra **exatamente os AppServers reais** (nomes e portas).
- [ ] **Se aparecer algo que não é AppServer** (ex.: `[TCP]` do listener) → **anotar** (vou filtrar).
- [ ] A coluna `rpo=` mostra um hash (achou o `.rpo`). Se `não encontrado` → ajustar `rpo_glob`.

## 3. Validar UP/DOWN real
- [ ] Com os AppServers **no ar**, rodar `discover` → coluna `up=True` nos AppServers reais.
- [ ] (Opcional) Parar UM AppServer e rodar `discover` de novo → aquele fica `up=False`.

## 4. Enrolar o agente
- [ ] No Minutor: Prosight → Configuração → empresa **PROMAX** → ambiente → Connector → **Gerar token**.
- [ ] `prosight-connector.exe enroll --token <TOKEN>` → mensagem `Enrolled!` e `state.json` criado.

## 5. Colocar online + reportar
```bat
prosight-connector.exe run
```
- [ ] No Minutor (seção Connector), o status vira **Connector: online**.
- [ ] Os **AppServers reais** aparecem como detectados (com os nomes do `appserver.ini`).

## 6. Completar a jornada (fica 4/4)
- [ ] **AppServers vinculados**: no Minutor, confirmar o vínculo dos AppServers detectados aos cadastrais.
- [ ] **RPO confirmado**: na seção RPO/Operações RPO, confirmar o Target (deve estar **consistente** — mesmo hash de RPO em todos os AppServers do mesmo publish unit).
- [ ] A jornada mostra **Configuração 4 de 4 · ready**.

## 7. Validar EXECUÇÃO (start/stop/restart) — ⚠️ com cuidado (mexe no AppServer)
> Fazer **fora do horário** ou num AppServer não crítico. Confirmar o `service_prefix`/nome do serviço antes.
- [ ] No Minutor (Operações RPO / Operações), disparar um **restart** num AppServer de teste.
- [ ] O agente executa `sc stop/start <serviço>`; o AppServer reinicia; o Minutor mostra a operação **reconciliada com nova incarnação**.
- [ ] (Se o nome do serviço estiver errado) o agente reporta falha **antes do efeito** (nada quebra) → ajustar `service_prefix`.

## 8. Rodar como serviço (produção)
- [ ] Instalar como serviço (NSSM ou Agendador — ver `INSTALL-ONPREM.md`) para ficar sempre no ar.

---

## O que me enviar de volta
1. Saída do `discover` (para eu afinar o filtro do `appserver.ini`, se preciso).
2. Se o `.rpo` não foi encontrado: a estrutura real da pasta `apo`/RPO.
3. Nome real do **serviço Windows** do AppServer (para o `service_prefix`).
4. Qualquer erro exibido pelo agente (copiar a linha completa).

Com isso eu fecho os ajustes finais e a integração fica **100% física** na PROMAX.
