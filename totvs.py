#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Camada TOTVS — descoberta e execução FÍSICA de AppServers/RPO na máquina on-prem.

Substitui a lista manual do config.json por descoberta REAL a partir do appserver.ini
(padrão Protheus), checagem de "up" por porta TCP, e hash do arquivo .rpo do disco.
A execução (start/stop/restart) usa o serviço do Windows.

⚠️ Validação: a lógica de parsing/hash/porta é testável em qualquer SO (ver test_totvs.py).
O start/stop/restart via serviço só roda no **Windows** com o AppServer instalado como serviço —
não há como validar isto fora de uma máquina Protheus real.

Como o AGENTE usa (config.json):
  "totvs": {
    "appserver_ini": "D:\\TOTVS\\Protheus\\appserver.ini",  # Linux: "/totvs/protheus/appserver.ini"
    "rpo_glob": "D:\\TOTVS\\Protheus\\apo\\*.rpo",   # opcional; senão deriva do ini
    "host": "127.0.0.1",                              # host p/ checar porta (default localhost)
    "service_prefix": "Protheus_",                    # serviço = prefix+appserver (Windows sc; Linux systemd unit)
    "service_manager": "auto"                          # auto|windows|systemd (auto = pelo SO)
  }

Multiplataforma: descoberta (ini/porta/hash do .rpo) roda em Windows E Linux. O controle de
serviço usa `sc` no Windows e `systemctl` no Linux (systemd) — a unit é service_prefix+appserver
(ex.: "protheus_APP01" → systemctl start protheus_APP01.service).
"""

import configparser
import glob
import hashlib
import os
import socket
import subprocess


# ──────────────────────────────────────────────────────────────────────────────
# DESCOBERTA
# ──────────────────────────────────────────────────────────────────────────────
def parse_appserver_ini(path):
    """
    Lê o appserver.ini e devolve os AppServers configurados.
    Cada AppServer no Protheus é uma seção com uma chave de porta (TCP/PORT/Port).
    Também captura SourcePath/RootPath (p/ localizar o RPO) da seção [GENERAL]/[ENVIRONMENT].

    @return {"appservers":[{"name","port","env"}], "source_path": str|None, "environments":[...]}
    """
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    # Protheus ini pode ter chaves duplicadas/case variável; lê tolerante.
    cp.optionxform = str
    with open(path, "r", encoding="latin-1", errors="replace") as f:
        cp.read_file(f)

    appservers = []
    environments = []
    source_path = None

    for sec in cp.sections():
        keys = {k.lower(): v for k, v in cp.items(sec)}
        # Porta TCP de um AppServer (seção com Port/TCPPort e normalmente Type=TCP).
        port = keys.get("port") or keys.get("tcpport") or keys.get("tcp")
        if port and str(port).strip().isdigit():
            appservers.append({"name": sec, "port": int(str(port).strip()), "env": keys.get("environment")})
        # Ambientes Protheus (seção com SourcePath/RootPath).
        if "sourcepath" in keys or "rootpath" in keys:
            environments.append({"name": sec, "source_path": keys.get("sourcepath"), "root_path": keys.get("rootpath")})
            source_path = source_path or keys.get("sourcepath") or keys.get("rootpath")

    return {"appservers": appservers, "source_path": source_path, "environments": environments}


def port_is_up(host, port, timeout=2.0):
    """Um AppServer 'up' aceita conexão TCP na sua porta. Checagem local, não intrusiva."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def rpo_hash(path):
    """sha256 do arquivo .rpo (identidade do RPO compilado). None se não achar."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def discover(totvs_cfg):
    """
    Descoberta REAL a partir do appserver.ini. Devolve no formato que o agente reporta:
      [{"name","port","up","rpo_path","rpo_hash"}]
    Se não houver appserver.ini configurado/legível, devolve [] (o agente cai no config manual).
    """
    ini = (totvs_cfg or {}).get("appserver_ini")
    if not ini or not os.path.exists(ini):
        return []
    host = (totvs_cfg or {}).get("host", "127.0.0.1")
    parsed = parse_appserver_ini(ini)

    # Localiza o(s) arquivo(s) RPO: glob explícito, senão deriva de source_path/apo.
    rpo_files = []
    rpo_glob = (totvs_cfg or {}).get("rpo_glob")
    if rpo_glob:
        rpo_files = sorted(glob.glob(rpo_glob))
    elif parsed["source_path"]:
        for pat in ("*.rpo", os.path.join("apo", "*.rpo")):
            rpo_files += sorted(glob.glob(os.path.join(parsed["source_path"], pat)))
    # RPO principal = maior arquivo (heurística padrão do RPO custom).
    main_rpo = max(rpo_files, key=lambda p: os.path.getsize(p), default=None) if rpo_files else None
    main_hash = rpo_hash(main_rpo) if main_rpo else None

    out = []
    for a in parsed["appservers"]:
        out.append({
            "name": a["name"],
            "port": a["port"],
            "up": port_is_up(host, a["port"]),
            "rpo_path": main_rpo,      # todos os AppServers do ambiente compartilham o RPO
            "rpo_hash": main_hash,
        })
    return out


# ──────────────────────────────────────────────────────────────────────────────
# EXECUÇÃO — start/stop/restart do serviço do AppServer (Windows sc / Linux systemd)
# ──────────────────────────────────────────────────────────────────────────────
def _service_name(totvs_cfg, appserver_name):
    prefix = (totvs_cfg or {}).get("service_prefix", "")
    return f"{prefix}{appserver_name}"


def _service_manager(totvs_cfg):
    """Resolve o gerenciador de serviço: config 'service_manager' (auto|windows|systemd) ou pelo SO."""
    mgr = str((totvs_cfg or {}).get("service_manager", "auto")).lower()
    if mgr in ("windows", "systemd"):
        return mgr
    return "windows" if os.name == "nt" else "systemd"


def control_service(totvs_cfg, appserver_name, action):
    """
    start/stop/restart do serviço do AppServer. Retorna (ok, msg).
    - Windows: serviço via `sc` (nome = service_prefix+appserver).
    - Linux: unit systemd via `systemctl` (unit = service_prefix+appserver).
    ⚠️ Exige o AppServer instalado como serviço/unit. Precisa de privilégio (Windows: admin;
    Linux: root/sudo ou PolicyKit) — configure isto na instalação do agente.
    """
    if action not in ("start", "stop", "restart"):
        return False, f"acao invalida: {action}"
    svc = _service_name(totvs_cfg, appserver_name)
    mgr = _service_manager(totvs_cfg)

    if mgr == "windows":
        cmds = {
            "stop": [["sc", "stop", svc]],
            "start": [["sc", "start", svc]],
            "restart": [["sc", "stop", svc], ["sc", "start", svc]],
        }[action]
    else:  # systemd
        cmds = [["systemctl", action, svc]]

    try:
        for c in cmds:
            subprocess.run(c, check=True, capture_output=True, timeout=60)
        return True, f"{action} {svc} ok ({mgr})"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        return False, f"{action} {svc} falhou ({mgr}): {e}"
