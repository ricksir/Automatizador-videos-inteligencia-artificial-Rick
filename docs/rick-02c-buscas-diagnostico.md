# Rick 02C/1 — diagnóstico e recuperação de buscas

## Objetivo

Identificar por que a pré-curadoria não encontra materiais suficientes.
O aviso anterior `Vídeo demonstrations: ValueError` não informa qual etapa
falhou e **não permite determinar a causa apenas com o print**.

## Mudanças

- Cada falha de busca/download/importação gera um diagnóstico com cena,
  categoria semântica, banco, etapa, código estável e indicador de
  transitoriedade. Dados de URL e chaves privadas não entram no relatório.
- Na busca Pexels e Coverr, respostas 401, 429, 4xx, 5xx e HTML no lugar
  de JSON agora têm diagnóstico sanitizado no log do aplicativo.
- O download de mídia de estoque só aceita HTTPS de
  `videos.pexels.com` ou `cdn.pixabay.com`; segue proibido redirecionamento.
- Falha temporária de rede, timeout, HTTP 429 ou 500/502/503/504
  pode gerar até três tentativas **sobre a mesma URL**.
- HTTP 401/403, resposta inesperada, MP4 inválido, arquivo acima de
  64 MB e falha de catálogo NÃO são repetidos automaticamente.
- Se um candidato falhar, o programa tenta os próximos arquivos e
  pesquisas/provedores previstos, mantendo os limites existentes.
- Nenhuma mídia é aprovada ou publicada automaticamente por este pacote.

## Exemplos de códigos

| Etapa | Código | Significado |
|---|---|---|
| search | search_provider_exception | exceção na busca do provedor |
| search | search_network_error | falha de rede na consulta |
| download | download_timeout | tempo limite de download |
| download | http_rate_limited | resposta HTTP 429 |
| download | http_server_error | erro HTTP 500/502/503/504 |
| download | http_access_denied | servidor negou acesso |
| download | unexpected_content_type | origem não retornou MP4 |
| download | invalid_mp4_header | bytes não parecem MP4 |
| import | invalid_mp4_import | validação da mídia rejeitou o arquivo |
| import | editorial_import_failed | importação inválida, causa ainda indeterminada |
| import | catalog_capacity_reached | catálogo local excedeu o limite de arquivos |

## Como testar na máquina Windows

1. Atualizar a branch correspondente ao PR #22, preservando alterações locais.
2. Abrir a tarefa histórica do Gramsci no painel de revisão.
3. Clicar em **Buscar novas fotos e vídeos e pré-curar todas as cenas**.
4. Conferir a tabela de falhas por cena/contexto/fonte/etapa/código.
5. Verificar se a mesma falha se repete e se houve novos candidatos válidos.

Não compartilhe configurações privadas, credenciais, links de upload assinados
ou a íntegra de logs não sanitizados. O relatório resumido do painel é
preferível para diagnóstico.

## Testes de regressão

    uv run --no-sync python -X utf8 -m pytest -q test/services/test_rick_02c_stock_diagnostics.py test/services/test_rick_scene_precuration.py

## Limitações

- Os bancos podem retornar zero vídeos adequados mesmo sem erros técnicos.
- Um candidato baixado corretamente pode não ter conteúdo visual pertinente.
- Não há análise real de pixels nem certificado automático de direitos.
- O resultado correto para uma cena sem mídia verificada é `Pendente`.
- A publicação diária continua bloqueada.
