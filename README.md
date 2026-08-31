# Prosight Connector — Agente on-prem (referência)

Agente **outbound-only** que roda na máquina do cliente (onde está o Protheus),
conecta-se sozinho ao Minutor e reporta presença. Prova o canal seguro
(identidade **Ed25519** + assinatura AGENT-V1) sem nunca expor caminho/INI/segredo.

> Este é o componente que faltava para "conectar o ambiente de verdade". No Minutor
> (Prosight → Configuração → Connector) você **gera o token**; aqui o agente troca esse
> token por uma identidade e passa a bater heartbeat (o ambiente fica **online**).

## Requisitos
- Python 3.8+
- `pip install cryptography`

## Uso

```bash
# 1) Gere o token no Prosight (Configuração → empresa → ambiente → Connector → "Gerar token de conexão")
#    e cole abaixo. O token é de uso único e expira em ~15 min.
python prosight_connector.py enroll --token <TOKEN>

# 2) Prove o canal (opcional)
python prosight_connector.py whoami

# 3) Rode o loop (heartbeat + inventário + comandos + operações start/stop/restart)
python prosight_connector.py run                 # mantém online, reporta AppServers, atende comandos/operações
python prosight_connector.py heartbeat           # 1 batida de presença só (teste)
python prosight_connector.py inventory           # envia 1 inventário de AppServers (teste)
python prosight_connector.py operations          # drena operações pendentes uma vez (teste)
python prosight_connector.py patch               # drena execuções de patch pendentes (teste)
```

Os AppServers reportados ficam em `state.json` (chave `appservers`), com `ref` **estável**
(identidade de binding). Edite nomes/versões conforme o ambiente real do cliente; num
agente de produção isso viria da topologia observada do Protheus.

Base da API (default = homolog). Troque com `--base` ou a env `PROSIGHT_BASE`:
```
https://minutor-backend-homolog.onrender.com/api/v1
```

## O que fica na máquina
- `state.json` (modo `0600`): `agent_id` + **chave privada Ed25519** (PKCS8 PEM).
  A privada **nunca** sai da máquina; o servidor só guarda a pública + fingerprint.
- Apague `state.json` para forçar um novo enroll (exige revogar o agente anterior no Prosight).

## Protocolo (o que o servidor espera)
- **Enroll** (sem sessão, token no corpo): `POST /connector/enroll`
  `{enrollment_token, public_key (Base64 dos 32 bytes crus Ed25519), agent_version?}`
  → `201 {agent_id, server_time, heartbeat_interval_s}`
- **Requisições assinadas** (headers): `X-Agent-Id`, `X-Timestamp` (unix s), `X-Nonce`
  (16–128, base64url), `X-Signature` (Base64 da assinatura Ed25519 de 64 bytes).
- **String canônica AGENT-V1** (campos separados por `\n`):
  ```
  AGENT-V1
  {agent_id}
  {MÉTODO}
  {path COM /api/v1, sem querystring}
  {sha256(corpo) hex minúsculo}
  {timestamp unix}
  {nonce}
  ```
- **Endpoints assinados**: `GET /connector/whoami`, `POST /connector/heartbeat`
  (`{observed_at?, agent_uptime_s?, agent_reported_status: ok|starting|error, error?}`),
  `POST /connector/inventory`, `GET /connector/commands/next` + `.../{id}/ack|result`,
  além de `operations` e `patch-executions` (mesmo padrão claim→ack→result).

## Status desta referência
Implementa: **enroll · whoami · heartbeat · inventário (AppServers + RPO) · comandos
(`collect_inventory_now`) · operações start/stop/restart**.

**Operações (canal C-4.1)** — máquina de estados por operação:
`GET /connector/operations/next` (ou `/current` p/ retomar claim perdido) →
`ack {execution_id, phase:execution_committed}` (**barreira**: comprometido) →
efeito local (start=up · stop=down · restart=up + **nova incarnação**) →
`ack {phase:effect_started}` → `result {outcome:ok, phase:post_effect}` → **verifying** →
**inventário pós-efeito correlacionado** (`trigger.operation_id`) → o **C-2** (servidor) reconcilia
`verifying → reconciled_success` (autoridade do desfecho é a observação, não o agente).
`execution_id` é do **servidor**; o agente só ecoa. Falha antes do efeito → `result(fail, pre_effect)`
(determinístico, efeito 0).

**Patch (canal C-Patch/P2)** — execução governada com fencing + journal + candidate:
`GET /connector/patch-executions/next` → `ack base_verified` → `ack patch_effect_started`
(**barreira**, valida fence_token contra o workspace lock) → por item: `ack patch_item_started{item_order}`
→ aplica → `ack patch_item_committed{item_order}` → `ack patch_effect_committed` (exige todos committed)
→ `ack artifact_verified` → `result {outcome:success, candidate_digest}` → servidor gera o **artefato
candidato** e libera o workspace lock. `outcome` ∈ success|failed|partial (partial/failed → zero candidate).
O `candidate_digest` (64 hex) é o sha256 do RPO resultante (aqui derivado de base+lote+itens).

**Compile NÃO tem canal de agente:** é executado **server-side por adapter**
(`SimulatedCompileAdapter` in-process / `LiveCompileAdapter` gated), não pelo agente outbound —
não há nada a implementar no agente para compile.

## Validado
Testado contra `minutor-backend-homolog` em 2026-08-29, ambiente **CONCRESERV HOMOLOG (env 8)**:
- enroll `201` · whoami `200` · heartbeat `200` → **online**.
- inventário `200` → 2 AppServers (APP01/APP02) + RPO observados no Prosight.
- comando `collect_inventory_now`: claim → ack → coleta → **result ok / `succeeded`**.
- operação **start** (#305): claim → barreira → efeito → result ok/verifying; postimage `up:true` → reconcile `reconciled_success`.
- operação **restart** (#309): idem, com **incarnação alterada** (`v8Wka… → H2xux…`) gravada no
  `postimage_snapshot` correlacionado (autoridade do desfecho do restart).
- **patch** (execução #9, 2 itens): base_verified → barreira(fencing) → itens started/committed →
  effect_committed → artifact_verified → **result success** → status `candidate` + artefato candidato
  gerado + **workspace lock liberado** (`released`, barrier_crossed).

> **Fix de backend necessário (aplicado):** o `agentView` do patch não expunha o `id` numérico da
> execução — sem ele o agente não monta `/patch-executions/{id}/ack|result`. Acréscimo aditivo
> `'id' => $x->id` (commit no backend homolog `014f5713`).

> Gates server-side (não do agente): **stop/restart** exigem presença **online** + AppServer alvo
> **up** + **não ser o último** up + janela de manutenção; senão o dispatch é bloqueado (`canceled`).
> **start** não tem gate destrutivo.
