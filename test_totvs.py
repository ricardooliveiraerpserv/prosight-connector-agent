#!/usr/bin/env python3
"""Testes da camada TOTVS (parsing/hash/porta). Rode: python test_totvs.py"""
import os
import tempfile
import totvs


def test_parse_appserver_ini():
    ini = """
[ENVIRONMENT]
SourcePath=C:\\TOTVS\\apo
RootPath=C:\\TOTVS
[APP_PROD_01]
Type=TCP
Port=5555
Environment=ENVIRONMENT
[APP_PROD_02]
Type=TCP
Port=5556
"""
    with tempfile.NamedTemporaryFile("w", suffix=".ini", delete=False, encoding="latin-1") as f:
        f.write(ini); path = f.name
    try:
        p = totvs.parse_appserver_ini(path)
        names = {a["name"]: a["port"] for a in p["appservers"]}
        assert names.get("APP_PROD_01") == 5555, names
        assert names.get("APP_PROD_02") == 5556, names
        assert p["source_path"] == "C:\\TOTVS\\apo", p["source_path"]
        print("ok parse_appserver_ini")
    finally:
        os.unlink(path)


def test_rpo_hash_and_discover():
    d = tempfile.mkdtemp()
    rpo = os.path.join(d, "custom.rpo")
    with open(rpo, "wb") as f:
        f.write(b"RPO-BYTES" * 100)
    ini = os.path.join(d, "appserver.ini")
    with open(ini, "w", encoding="latin-1") as f:
        f.write("[A1]\nType=TCP\nPort=7001\n[A2]\nType=TCP\nPort=7002\n")
    try:
        h = totvs.rpo_hash(rpo)
        assert h and len(h) == 64, h
        found = totvs.discover({"appserver_ini": ini, "rpo_glob": os.path.join(d, "*.rpo")})
        assert len(found) == 2, found
        # membros compartilham o MESMO rpo_hash (consistência do target)
        assert found[0]["rpo_hash"] == found[1]["rpo_hash"] == h, found
        assert found[0]["up"] is False  # nada ouvindo na porta
        print("ok rpo_hash + discover (hash consistente por publish unit)")
    finally:
        os.unlink(rpo); os.unlink(ini); os.rmdir(d)


def test_port_up_false():
    assert totvs.port_is_up("127.0.0.1", 65534, 0.2) is False
    print("ok port_is_up (fechada = False)")


def test_service_resolution():
    cfg = {"service_prefix": "protheus_"}
    assert totvs._service_name(cfg, "APP01") == "protheus_APP01"
    # override explícito vence o SO
    assert totvs._service_manager({"service_manager": "systemd"}) == "systemd"
    assert totvs._service_manager({"service_manager": "windows"}) == "windows"
    # auto = pelo SO corrente
    expected = "windows" if os.name == "nt" else "systemd"
    assert totvs._service_manager({"service_manager": "auto"}) == expected
    assert totvs._service_manager({}) == expected
    print(f"ok service resolution (auto -> {expected})")


if __name__ == "__main__":
    test_parse_appserver_ini()
    test_rpo_hash_and_discover()
    test_port_up_false()
    test_service_resolution()
    print("TODOS OS TESTES PASSARAM")
