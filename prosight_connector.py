#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prosight Connector — Agente on-prem (referência funcional).

Canal OUTBOUND-ONLY: o agente roda na máquina do cliente (onde está o Protheus),
conecta-se SOZINHO ao Minutor e reporta presença. Nenhum caminho/INI/segredo do
Protheus trafega neste agente de referência — só identidade Ed25519 + heartbeat.

Fluxo:
  1) enroll  — troca o token de enrollment (gerado no Prosight) por uma identidade
               Ed25519 (agent_id). Roda UMA vez; a identidade fica em state.json.
  2) whoami  — prova o canal (requisição assinada).
  3) heartbeat (loop) — a cada N segundos; faz o ambiente ficar "online" no Prosight.

Protocolo de assinatura (AGENT-V1), string canônica separada por \\n:
  AGENT-V1
  {agent_id}
  {METHOD}
  {path COM /api/v1, sem querystring}
  {sha256(body) hex minúsculo}
  {timestamp unix}
  {nonce}
Assinada com Ed25519 (64 bytes) → Base64 no header X-Signature.

Dependência única: `cryptography`  (pip install cryptography)
HTTP: urllib (stdlib). Compatível Python 3.8+ (Windows/Linux/macOS).
"""

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

AGENT_VERSION = "ref-1.0.0"
DEFAULT_BASE = "https://minutor-backend-homolog.onrender.com/api/v1"
STATE_FILE = os.environ.get("PROSIGHT_STATE", "state.json")


# ──────────────────────────────────────────────────────────────────────────────
# Estado / identidade
# ──────────────────────────────────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_state(st):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2)
    os.replace(tmp, STATE_FILE)
    try:
        os.chmod(STATE_FILE, 0o600)  # chave privada: só o dono lê
    except OSError:
        pass


def private_key_from_state(st):
    pem = st["private_key_pem"].encode("utf-8")
    return serialization.load_pem_private_key(pem, password=None)


# ──────────────────────────────────────────────────────────────────────────────
# Inventário — AppServers observados (refs ESTÁVEIS por incarnação)
# ──────────────────────────────────────────────────────────────────────────────
def _uuid():
    import uuid
    return str(uuid.uuid4())


def ensure_appservers(st):
    """
    Lista de AppServers reportados. O `ref` (uuid) é a IDENTIDADE ESTÁVEL do AppServer
    (autoridade de binding no Prosight) → gerado UMA vez e persistido em state.json.
    Num agente real, isto viria da topologia observada do Protheus; aqui é um exemplo
    editável. Ajuste nomes/versões em state.json conforme o ambiente real do cliente.
    """
    apps = st.get("appservers")
    if not apps:
        # 1ª execução: tenta ler os AppServers REAIS do cliente de config.json; senão usa exemplo.
        cfg = _load_config()
        declared = cfg.get("appservers") if isinstance(cfg, dict) else None
        if declared:
            apps = [{
                "ref": _uuid(), "name": a.get("name", f"APP{i+1:02d}"),
                "version": a.get("version"), "build": a.get("build"), "patch": a.get("patch"),
            } for i, a in enumerate(declared)]
        else:
            apps = [
                {"ref": _uuid(), "name": "APP01", "version": "12.1.2410", "build": "9999", "patch": "12"},
                {"ref": _uuid(), "name": "APP02", "version": "12.1.2410", "build": "9999", "patch": "12"},
            ]
        st["appservers"] = apps
        save_state(st)
    return apps


def _load_config():
    """config.json (opcional): {base, appservers:[{name,version,build,patch}]}. Editado pelo cliente."""
    path = os.environ.get("PROSIGHT_CONFIG", "config.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    return {}


def _discover_and_merge(st):
    """
    Se config.json tiver a seção `totvs` (appserver.ini), descobre os AppServers REAIS e mescla
    no state (ref estável por nome + up/rpo_hash observados). Requer totvs.py. Sem isso, no-op.
    """
    cfg = _load_config()
    totvs_cfg = cfg.get("totvs") if isinstance(cfg, dict) else None
    if not totvs_cfg:
        return False
    try:
        import totvs
    except ImportError:
        return False
    found = totvs.discover(totvs_cfg)
    if not found:
        return False
    by_name = {a["name"]: a for a in st.get("appservers", [])}
    merged = []
    for d in found:
        prev = by_name.get(d["name"], {})
        merged.append({
            "ref": prev.get("ref") or _uuid(),   # ref ESTÁVEL por nome (persiste)
            "_pi": prev.get("_pi"),
            "name": d["name"],
            "up": bool(d.get("up")),
            "_rpo_hash": d.get("rpo_hash"),        # hash REAL do .rpo do disco
        })
    st["appservers"] = merged
    save_state(st)
    return True


def build_inventory(st, trigger=None):
    now = int(time.time())
    _discover_and_merge(st)               # descoberta REAL (se totvs configurado)
    apps = ensure_appservers(st)
    appservers = []
    rpo = []
    dirty = False
    for a in apps:
        up = a.get("up", True)
        # process_instance_id: IDENTIDADE DA INCARNAÇÃO do processo (muda a cada restart do AppServer).
        # PERSISTIDA em state.json → estável entre heartbeats; só o restart a troca (nova incarnação).
        pi = a.get("_pi")
        if not pi:
            pi = secrets.token_urlsafe(16)[:24]
            a["_pi"] = pi
            dirty = True
        appservers.append({
            "ref": a["ref"], "name": a["name"], "up": up,
            "version": a.get("version"), "build": a.get("build"), "patch": a.get("patch"),
            "uptime_s": 60 if up else 0, "process_instance_id": pi,
        })
        # 1 RPO por appserver. Membros do MESMO publish unit publicam o MESMO RPO → hash IGUAL.
        # hash REAL do .rpo (descoberto pela camada TOTVS) quando disponível; senão derivado.
        pu = "U" + hashlib.sha256(("unit:" + st["agent_id"]).encode()).hexdigest()[:16]
        real_hash = a.get("_rpo_hash")
        rpo.append({
            "appserver_ref": a["ref"],
            "hash": real_hash if real_hash else hashlib.sha256(("rpo:" + pu).encode()).hexdigest(),
            "version": "TTTP", "size": 1024, "mtime": now,
            "publish_unit_id": pu,
        })
    if dirty:
        save_state(st)   # persiste as incarnações recém-geradas (estabilidade entre processos)
    # Bloco TOPOLOGY — descoberta RPO: papéis por AppServer (1º compilador, demais slaves).
    # Habilita o Prosight a detectar e confirmar o Target RPO. role_source=observed (o agente viu).
    members = []
    for i, a in enumerate(apps):
        members.append({
            "appserver_ref": a["ref"],
            "role": "compiler" if i == 0 else "slave",
            "role_source": "observed",
            "environment_name": a.get("name"),
        })
    body = {"observed_at": now, "appservers": appservers, "rest": [], "rpo": rpo,
            "topology": {"observed_at": now, "members": members}}
    if trigger:
        body["trigger"] = trigger
    return body


# ──────────────────────────────────────────────────────────────────────────────
# HTTP + assinatura
# ──────────────────────────────────────────────────────────────────────────────
def _request(base, method, path, body_bytes=b"", headers=None):
    url = base.rstrip("/") + path
    req = urllib.request.Request(url, data=body_bytes if method != "GET" else None, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        payload = e.read().decode("utf-8")
        try:
            payload = json.loads(payload)
        except ValueError:
            pass
        return e.code, payload


def canonical(agent_id, method, full_path, body_bytes, ts, nonce):
    # full_path = path COM /api/v1 (é o que o servidor vê em getPathInfo), sem query.
    path = "/" + full_path.split("?", 1)[0].lstrip("/")
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    return "\n".join(["AGENT-V1", agent_id, method.upper(), path, body_hash, str(ts), nonce])


def signed_request(base, st, method, path, body_obj=None):
    priv = private_key_from_state(st)
    body_bytes = json.dumps(body_obj).encode("utf-8") if body_obj is not None else b""
    ts = int(time.time())
    nonce = secrets.token_urlsafe(24)          # [A-Za-z0-9_-], 32 chars → casa o regex do servidor
    full_path = urlparse(base).path.rstrip("/") + path   # /api/v1 + /connector/...
    msg = canonical(st["agent_id"], method, full_path, body_bytes, ts, nonce).encode("utf-8")
    sig = priv.sign(msg)                        # Ed25519 → 64 bytes
    headers = {
        "X-Agent-Id": st["agent_id"],
        "X-Timestamp": str(ts),
        "X-Nonce": nonce,
        "X-Signature": base64.b64encode(sig).decode("ascii"),
    }
    return _request(base, method, path, body_bytes, headers)


# ──────────────────────────────────────────────────────────────────────────────
# Comandos
# ──────────────────────────────────────────────────────────────────────────────
def cmd_enroll(base, token):
    if load_state():
        print("[i] Já existe uma identidade em", STATE_FILE, "— use 'run' ou apague o arquivo p/ re-enroll.")
        return 0
    # Gera par Ed25519. A privada NUNCA sai da máquina.
    priv = Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    pub_b64 = base64.b64encode(pub_raw).decode("ascii")   # Base64 dos 32 bytes crus (formato aceito)
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")

    status, resp = _request(
        base, "POST", "/connector/enroll",
        json.dumps({"enrollment_token": token, "public_key": pub_b64, "agent_version": AGENT_VERSION}).encode("utf-8"),
    )
    if status != 201:
        print(f"[x] Falha no enroll (HTTP {status}): {resp}")
        if status == 409:
            print("    → Este ambiente já tem um agente ativo. Revogue-o no Prosight (Configuração → Connector) e gere um novo token.")
        if status == 401:
            print("    → Token inválido/expirado/usado. Gere um novo token no Prosight (expira em ~15min, uso único).")
        return 1

    st = {
        "agent_id": resp["agent_id"],
        "private_key_pem": priv_pem,
        "public_key_b64": pub_b64,
        "base": base,
        "enrolled_at": int(time.time()),
    }
    save_state(st)
    print(f"[✓] Enrolled! agent_id={resp['agent_id']}  (server_time={resp.get('server_time')})")
    print(f"    Identidade salva em {STATE_FILE}. Agora rode:  python prosight_connector.py run")
    return 0


def cmd_whoami(base, st):
    status, resp = signed_request(base, st, "GET", "/connector/whoami")
    print(f"[whoami] HTTP {status}: {resp}")
    return 0 if status == 200 else 1


def cmd_inventory(base, st, trigger=None):
    body = build_inventory(st, trigger)
    status, resp = signed_request(base, st, "POST", "/connector/inventory", body)
    stamp = time.strftime("%H:%M:%S")
    n = len(body["appservers"])
    if status in (200, 201):
        print(f"[{stamp}] inventário enviado: {n} AppServer(s) + {len(body['rpo'])} RPO (HTTP {status})")
    else:
        print(f"[{stamp}] inventário FALHOU HTTP {status}: {resp}")
    return status, resp


def handle_command(base, st, cmd):
    cid = cmd["id"]
    ctype = cmd["command_type"]
    ctoken = cmd["claim_token"]
    stamp = time.strftime("%H:%M:%S")
    print(f"[{stamp}] comando recebido: #{cid} {ctype}")
    # ACK (claimed→running) — opcional, mas deixa o estado explícito no Prosight.
    signed_request(base, st, "POST", f"/connector/commands/{cid}/ack", {"claim_token": ctoken})
    t0 = time.time()
    if ctype == "collect_inventory_now":
        status, _ = cmd_inventory(base, st, trigger={"type": "command", "command_id": cid})
        outcome = "ok" if status in (200, 201) else "fail"
    else:
        print(f"[{stamp}] comando '{ctype}' não suportado por esta referência.")
        outcome = "fail"
    dur = int((time.time() - t0) * 1000)
    rs, rr = signed_request(base, st, "POST", f"/connector/commands/{cid}/result",
                            {"claim_token": ctoken, "outcome": outcome, "duration_ms": dur,
                             "observed_at": int(time.time())})
    print(f"[{stamp}] result #{cid} → {outcome} (HTTP {rs}: {rr})")


def poll_commands(base, st):
    """Um long-poll de comandos (hold ~25s no servidor). 204 = nada."""
    status, resp = signed_request(base, st, "GET", "/connector/commands/next")
    if status == 200 and isinstance(resp, dict) and resp.get("data"):
        handle_command(base, st, resp["data"])
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Operações — start / stop / restart (canal C-4.1, claim single-shot)
# ──────────────────────────────────────────────────────────────────────────────
def apply_operation_effect(st, op_type, aref):
    """
    Aplica o efeito LOCAL da operação no AppServer (identificado por ref) e persiste.
    Num agente real, aqui entraria o start/stop/restart de verdade do AppServer Protheus.
    - start   → up=True
    - stop    → up=False
    - restart → up=True + NOVA incarnação (process_instance_id muda), autoridade de reconciliação.
    Retorna (ok, msg). ok=False → falha ANTES do efeito (determinístico, efeito 0).
    """
    apps = ensure_appservers(st)
    target = next((a for a in apps if a["ref"] == aref), None)
    if not target:
        return False, f"appserver_ref {aref[:8]}… desconhecido"
    if op_type not in ("start", "stop", "restart"):
        return False, f"op_type '{op_type}' não suportado"

    # EXECUÇÃO FÍSICA (camada TOTVS): controla o serviço Windows do AppServer, se configurado.
    cfg = _load_config()
    totvs_cfg = cfg.get("totvs") if isinstance(cfg, dict) else None
    physical_note = "simulado"
    if totvs_cfg:
        try:
            import totvs
            ok, msg = totvs.control_service(totvs_cfg, target["name"], op_type)
            if not ok and msg != "not_windows":
                return False, f"execução física falhou: {msg}"   # falha ANTES do efeito (pre_effect)
            physical_note = "físico" if ok else "simulado (fora do Windows)"
        except ImportError:
            pass

    # Reflete o estado local (o inventário pós-efeito confirma pelo C-2).
    if op_type == "start":
        target["up"] = True
    elif op_type == "stop":
        target["up"] = False
    else:  # restart
        target["up"] = True
        target["_pi"] = secrets.token_urlsafe(16)[:24]   # nova incarnação
    save_state(st)
    return True, f"{op_type} em {target['name']} ({physical_note})"


def handle_operation(base, st, op):
    opid = op["operation_id"]
    op_type = op["op_type"]
    aref = op["appserver_ref"]
    exid = op["execution_id"]           # AUTORIDADE do servidor — o agente só ecoa
    stamp = time.strftime("%H:%M:%S")
    print(f"[{stamp}] operação recebida: #{opid} {op_type} appserver={aref[:8]}…")

    # (1) BARREIRA — execution_committed (claimed → execution_committed). Cruzou = comprometido.
    s1, r1 = signed_request(base, st, "POST", f"/connector/operations/{opid}/ack",
                            {"execution_id": exid, "phase": "execution_committed"})
    if s1 != 200 or not (isinstance(r1, dict) and r1.get("ok")):
        print(f"[{stamp}] barreira NÃO cruzada (#{opid}) HTTP {s1}: {r1} — abortando sem efeito.")
        return
    # (2) Efeito local (start/stop/restart).
    ok, msg = apply_operation_effect(st, op_type, aref)
    if not ok:
        # Falha ANTES do efeito → result(fail, pre_effect) = determinístico, efeito 0.
        signed_request(base, st, "POST", f"/connector/operations/{opid}/result",
                       {"execution_id": exid, "outcome": "fail", "phase": "pre_effect", "error": msg[:200]})
        print(f"[{stamp}] #{opid} falhou pre_effect: {msg}")
        return
    # (3) Marca o efeito iniciado (execution_committed → executing).
    signed_request(base, st, "POST", f"/connector/operations/{opid}/ack",
                   {"execution_id": exid, "phase": "effect_started"})
    print(f"[{stamp}] {msg}")
    # (4) Result ok pós-efeito → verifying (autoridade do desfecho é o C-2/inventário).
    s4, r4 = signed_request(base, st, "POST", f"/connector/operations/{opid}/result",
                            {"execution_id": exid, "outcome": "ok", "phase": "post_effect"})
    print(f"[{stamp}] result #{opid} → ok/verifying (HTTP {s4}: {r4})")
    # (5) Inventário pós-efeito: o C-2 reconcilia verifying → succeeded/failed pelo estado OBSERVADO.
    cmd_inventory(base, st, trigger={"type": "operation", "operation_id": opid})


def poll_operations(base, st):
    """Operações usam short-poll (sem hold). Recupera claim perdido via /current."""
    status, resp = signed_request(base, st, "GET", "/connector/operations/next")
    if status == 200 and isinstance(resp, dict) and resp.get("data"):
        handle_operation(base, st, resp["data"])
        return True
    # Sem operação nova: checa se há um claim em andamento a retomar (resiliência a crash).
    cs, cr = signed_request(base, st, "GET", "/connector/operations/current")
    if cs == 200 and isinstance(cr, dict) and cr.get("data"):
        handle_operation(base, st, cr["data"])
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Patch — execução governada (canal C-Patch/P2, claim + journal + candidate)
# ──────────────────────────────────────────────────────────────────────────────
def compute_candidate_digest(ex):
    """
    Digest do artefato CANDIDATO (SIMULADO): deriva deterministicamente da base + do lote
    + dos digests dos itens. Num agente real seria o sha256 do RPO resultante da aplicação
    dos itens sobre a base. 64 hex (o servidor exige, e correlaciona ao candidate).
    """
    parts = [ex.get("base_rpo_hash", ""), ex.get("batch_digest", "")]
    parts += [str(i.get("item_digest", "")) for i in ex.get("items", [])]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def handle_patch(base, st, ex):
    pid = ex.get("id")                    # id numérico da execução (necessário p/ ack/result)
    exid = ex["execution_id"]
    stamp = time.strftime("%H:%M:%S")
    if pid is None:
        print(f"[{stamp}] execução patch sem 'id' numérico no payload — backend precisa expô-lo. Abortando.")
        return
    items = sorted(ex.get("items", []), key=lambda i: i.get("batch_order", 0))
    print(f"[{stamp}] execução PATCH #{pid} (exec {exid[:8]}…, fence={ex.get('fence_token')}, {len(items)} item(ns), modo={ex.get('execution_mode')})")

    def ack(phase, item_order=None):
        body = {"execution_id": exid, "phase": phase}
        if item_order is not None:
            body["item_order"] = item_order
        s, r = signed_request(base, st, "POST", f"/connector/patch-executions/{pid}/ack", body)
        ok = s == 200 and isinstance(r, dict) and r.get("ok")
        tag = phase + (f"[{item_order}]" if item_order else "")
        print(f"[{time.strftime('%H:%M:%S')}]   ack {tag} → {'ok' if ok else f'FALHA HTTP {s}: {r}'}")
        return ok

    # Journal do P2 (ordem CONGELADA). Qualquer falha aborta ANTES do result success.
    if not ack("base_verified"):                     # agente confere active_rpo == base_rpo_hash (ref: assume ok)
        return
    if not ack("patch_effect_started"):              # BARREIRA (fencing) — só o detentor da autoridade cruza
        return
    for it in items:                                 # aplica cada item do lote, em ordem
        order = it["batch_order"]
        if not ack("patch_item_started", order):
            return
        # (agente real aplicaria o item aqui; SIMULADO = no-op determinístico)
        if not ack("patch_item_committed", order):
            return
    if not ack("patch_effect_committed"):            # exige todos os itens committed
        return
    if not ack("artifact_verified"):                 # exige effect committed
        return
    cd = compute_candidate_digest(ex)
    s, r = signed_request(base, st, "POST", f"/connector/patch-executions/{pid}/result",
                          {"execution_id": exid, "outcome": "success", "candidate_digest": cd})
    print(f"[{time.strftime('%H:%M:%S')}]   result success (candidate={cd[:12]}…) → HTTP {s}: {r}")


def poll_patch(base, st):
    """Patch usa short-poll (execução em ST_CLAIMED)."""
    status, resp = signed_request(base, st, "GET", "/connector/patch-executions/next")
    if status == 200 and isinstance(resp, dict) and resp.get("data"):
        handle_patch(base, st, resp["data"])
        return True
    return False


def cmd_run(base, st, interval, once=False):
    # Prova o canal antes de entrar no loop.
    if cmd_whoami(base, st) != 0:
        print("[x] whoami falhou — identidade inválida/revogada. Abortando.")
        return 1
    started = int(time.time())
    # Inventário inicial (para o Prosight já ver AppServers assim que conecta).
    cmd_inventory(base, st, trigger={"type": "scheduled"})
    print(f"[i] Heartbeat ~{interval}s + long-poll de comandos. Ctrl+C para parar.")
    while True:
        body = {
            "observed_at": int(time.time()),
            "agent_uptime_s": int(time.time()) - started,
            "agent_reported_status": "ok",
        }
        t0 = time.time()
        status, resp = signed_request(base, st, "POST", "/connector/heartbeat", body)
        stamp = time.strftime("%H:%M:%S")
        if status == 200:
            print(f"[{stamp}] heartbeat ok (server_time={resp.get('server_time')})")
        else:
            print(f"[{stamp}] heartbeat FALHOU HTTP {status}: {resp}")
        if once:
            return 0 if status == 200 else 1
        # Operações (start/stop/restart) — short-poll, prioridade sobre comandos.
        try:
            while poll_operations(base, st):
                pass
        except urllib.error.URLError as e:
            print(f"[{stamp}] poll de operações falhou: {e}")
        # Patch (execução governada) — short-poll.
        try:
            while poll_patch(base, st):
                pass
        except urllib.error.URLError as e:
            print(f"[{stamp}] poll de patch falhou: {e}")
        # Long-poll de comandos (segura até ~25s); se veio comando, drena mais um.
        try:
            if poll_commands(base, st):
                poll_commands(base, st)
        except urllib.error.URLError as e:
            print(f"[{stamp}] poll de comandos falhou: {e}")
        # Completa a cadência do heartbeat (o long-poll já consumiu parte do intervalo).
        rest = interval - (time.time() - t0)
        if rest > 0:
            time.sleep(rest)


def main():
    ap = argparse.ArgumentParser(description="Prosight Connector — agente on-prem (referência).")
    ap.add_argument("command", choices=["enroll", "whoami", "run", "heartbeat", "inventory", "operations", "patch", "discover"], help="ação")
    ap.add_argument("--token", help="token de enrollment (só no enroll)")
    ap.add_argument("--base", default=os.environ.get("PROSIGHT_BASE", DEFAULT_BASE), help="URL base da API (…/api/v1)")
    ap.add_argument("--interval", type=int, default=60, help="intervalo do heartbeat em segundos (run)")
    args = ap.parse_args()

    if args.command == "discover":
        # Dry-run da camada TOTVS: mostra o que o agente descobriria do appserver.ini (sem enrolar).
        cfg = _load_config()
        totvs_cfg = cfg.get("totvs") if isinstance(cfg, dict) else None
        if not totvs_cfg:
            print("[i] Sem seção 'totvs' no config.json — o agente usaria a lista manual de appservers.")
            return 0
        try:
            import totvs
        except ImportError:
            print("[x] totvs.py não encontrado ao lado do agente."); return 2
        parsed = totvs.parse_appserver_ini(totvs_cfg["appserver_ini"]) if os.path.exists(totvs_cfg.get("appserver_ini", "")) else None
        if not parsed:
            print(f"[x] appserver.ini não encontrado: {totvs_cfg.get('appserver_ini')}"); return 2
        print(f"[i] appserver.ini: {totvs_cfg['appserver_ini']}")
        print(f"[i] source_path: {parsed['source_path']}")
        found = totvs.discover(totvs_cfg)
        print(f"[i] {len(found)} AppServer(s) descoberto(s):")
        for a in found:
            print(f"    - {a['name']:<24} porta={a['port']:<6} up={a['up']}  rpo={ (a['rpo_hash'] or 'não encontrado')[:16] }")
        print("[!] Confira se a lista bate com os AppServers REAIS. Se aparecer seção que não é AppServer")
        print("    (ex.: [TCP] do listener), ajuste o appserver.ini/config ou me avise para filtrar.")
        return 0

    if args.command == "enroll":
        if not args.token:
            print("[x] --token é obrigatório no enroll."); return 2
        return cmd_enroll(args.base, args.token.strip())

    st = load_state()
    if not st:
        print(f"[x] Sem identidade ({STATE_FILE}). Rode primeiro:  python prosight_connector.py enroll --token <TOKEN>")
        return 2
    base = st.get("base", args.base)

    if args.command == "whoami":
        return cmd_whoami(base, st)
    if args.command == "inventory":
        status, _ = cmd_inventory(base, st, trigger={"type": "scheduled"})
        return 0 if status in (200, 201) else 1
    if args.command == "operations":
        # Drena operações pendentes uma vez (start/stop/restart).
        n = 0
        while poll_operations(base, st):
            n += 1
        print(f"[i] {n} operação(ões) processada(s)." if n else "[i] Nenhuma operação pendente.")
        return 0
    if args.command == "patch":
        n = 0
        while poll_patch(base, st):
            n += 1
        print(f"[i] {n} execução(ões) de patch processada(s)." if n else "[i] Nenhuma execução de patch pendente.")
        return 0
    if args.command == "heartbeat":
        return cmd_run(base, st, args.interval, once=True)
    if args.command == "run":
        return cmd_run(base, st, args.interval)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[i] Encerrado.")
        sys.exit(0)
