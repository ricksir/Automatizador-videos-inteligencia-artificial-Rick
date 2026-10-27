# Rick — Política operacional de segurança

O repositório é público: nunca adicionar dados privados, reais ou confidenciais
em commits, PRs, issues, screenshots, comentários, artefatos ou logs.

## Operação no Windows

- Mantenha a WebUI vinculada apenas ao loopback para uso pessoal.
- A API iniciada pelo launcher protege a interface de rede quando
  não existe chave de autenticação. Se não houver chave, restringe-se
  ao loopback. Execuções alternativas exigem conferência do binding.
- Não use túnel público, encaminhamento de portas ou proxy reverso
  sem autenticação, HTTPS e revisão independente de segurança.
- Nunca execute scripts fornecidos por desconhecidos sem inspecioná-los.
- Armazene configurações e credenciais somente em arquivos locais
  protegidos e excluídos do Git. Evite fotos da tela com chaves.
- Se uma credencial apareceu num commit, revogue e substitua junto
  ao fornecedor: apagar o arquivo não apaga cópias do histórico.
- Use autenticação de dois fatores e prefira tokens de menor privilégio.

## Controles preventivos no repositório

- .gitignore inclui configurações privadas, certificados, banco de
  dados local, tokens e arquivos de trabalho.
- O scanner offline percorre caminhos versionados e detecta
  padrões conhecidos de credenciais sem exibir conteúdo ou valor.
- CI utiliza token apenas de leitura e não persiste credenciais
  durante o checkout; um workflow independente executa o scanner.
- Dependabot abre PRs de atualizações uv e GitHub Actions; nenhuma
  dependência será atualizada ou mergeada automaticamente.
- O scanner NÃO é garantia de ausência de vazamento e não substitui
  GitHub secret scanning nem investigação do histórico de branches.

### Verificação local

Na raiz do projeto, antes de publicar mudanças:

~~~powershell
uv run python scripts/rick_security_guard.py
uv run pytest -q test/services/test_rick_security_guard.py test/services/test_rick_security_network.py
~~~

O comando imprime apenas contagens de alertas, sem credenciais.

## Configurações recomendadas no GitHub

No repositório, abra Settings > Advanced Security e, quando disponíveis:

1. Confirme Secret scanning e Push protection ativados.
2. Examine alertas de secret scanning, incluindo bypasses.
3. Ative Dependabot alerts, security updates e CodeQL.
4. Proteja a branch principal com PR obrigatório, revisão e checks exigidos.
5. Confira o acesso de colaboradores, GitHub Apps e tokens; remova privilégios
   que não sejam necessários.
6. Revise Actions secrets/variables, ambientes e execução de workflows
   de forks. Não use pull_request_target para executar código não confiável.

**Não publique no GitHub relatórios completos de vulnerabilidades, dados
de conta, tokens, IPs privados, logs brutos de erro ou capturas contendo
configurações pessoais.** Use o fluxo de relato privado descrito na
política de segurança.

## Observações técnicas e limites

- A checagem de chaves da API existente depende da configuração local.
  Mantenha chaves habilitadas em qualquer ambiente exposto.
- A alteração no launcher cobre o ponto de entrada python main.py.
  O comando uvicorn direto e outros meios de iniciar ASGI exigem
  configuração segura própria e firewall.
- GitHub Actions podem conter falhas de testes anteriores; o scanner
  de segurança é independente.
- O histórico completo, servidores já implantados, arquivos privados
  no computador e credenciais de fornecedores não são inspecionados
  pelo scanner offline.
