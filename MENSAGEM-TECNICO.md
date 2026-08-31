Assunto: Instalação do Prosight Connector (agente) no servidor Protheus on-premise

Olá,

Precisamos instalar um pequeno **agente (Prosight Connector)** no servidor **on-premise onde roda o
Protheus (AppServer)**. Ele permite que a plataforma acompanhe os AppServers e o RPO e execute
operações governadas (start/stop/restart). Segue tudo o que é necessário.

── O QUE O AGENTE FAZ / SEGURANÇA ──────────────────────────────────────────────
• Conexão **somente de saída (outbound HTTPS)** — NÃO exige abrir nenhuma porta de entrada/firewall
  para dentro. Ele se conecta sozinho à nossa plataforma.
• Identidade por chave **Ed25519** gerada na própria máquina; a chave privada **nunca sai** do servidor.
• Não trafega caminho/INI/senha do Protheus para fora — o agente lê localmente e reporta só metadados.

── PRÉ-REQUISITOS ───────────────────────────────────────────────────────────────
• Saída HTTPS liberada para: https://minutor-backend-homolog.onrender.com
• Windows Server (onde está o AppServer). Python 3.8+ OU o executável prosight-connector.exe.
• Caminho do appserver.ini e da pasta do RPO (.rpo); nome do serviço Windows do AppServer.
• Permissão para parar/iniciar o serviço do AppServer (apenas para o teste final de restart).

── PASSO A PASSO (resumido; detalhes nos anexos) ───────────────────────────────
1) Copie a pasta do agente para o servidor (ex.: C:\Prosight\) e crie o config.json a partir do
   config.example.json, preenchendo a seção "totvs" com o caminho real do appserver.ini, o rpo_glob
   (ex.: D:\TOTVS\...\apo\*.rpo) e o service_prefix (prefixo do serviço Windows do AppServer).

2) Rode o diagnóstico (NÃO conecta nada ainda):
       prosight-connector.exe discover
   → Deve listar os AppServers REAIS (nomes e portas) e um hash do RPO.
   → Se aparecer algo que não é AppServer (ex.: seção [TCP] do listener) ou o RPO não for encontrado,
     nos avise com a saída — ajustamos.

3) Geramos um TOKEN de conexão e enviamos a você. Então:
       prosight-connector.exe enroll --token <TOKEN>
       prosight-connector.exe run
   → Na nossa plataforma o ambiente fica "online" e os AppServers aparecem.

4) Instale como serviço do Windows para ficar sempre no ar (NSSM ou Agendador de Tarefas —
   passo a passo no arquivo INSTALL-ONPREM.md).

── O QUE PRECISAMOS DE VOLTA ────────────────────────────────────────────────────
• A saída do comando "discover".
• O caminho real da pasta do RPO (.rpo), se o hash não for encontrado.
• O nome real do **serviço Windows** do AppServer (para o restart).
• Qualquer mensagem de erro exibida pelo agente (linha completa).

Anexos: prosight_connector.py, totvs.py, config.example.json, requirements.txt,
INSTALL-ONPREM.md, VALIDACAO-PROMAX.md (checklist de validação passo a passo).

Qualquer dúvida, estou à disposição para acompanhar a instalação.
Obrigado!
