# Rick V2 — Evolução 02B2A: associação preliminar de mídia às cenas

Esta entrega conecta o plano de cenas da 02B1 ao manifesto das mídias
**já baixadas** por Pixabay, Pexels ou Coverr.

## Quando funciona

Após a etapa de downloads e somente quando "Ajustar imagens à ordem do roteiro"
estiver ativado, o orquestrador:

1. Usa roteiro, duração de áudio e termos ordenados para criar
   `rick_scene_plan` (janelas **estimadas**, sem alinhamento fonético);
2. Lê a lista de `material_sources` que já contém `local_file` e
   `search_term`, excluindo arquivos não presentes no download;
3. Para cada cena, associa **candidatos com a mesma consulta de busca**
   (com normalização de maiúsculas/espaços);
4. Prefere outra origem antes de repetir e registra cenas sem resultado;
5. Salva `rick_scene_plan` e `rick_scene_candidate_preview` no
   `storage/tasks/<id>/script.json`, sem incluir URL assinada ou segredo.

Nenhuma nova chamada de IA, de banco de imagens ou de serviço de geração
ocorre aqui. Ausência de manifesto ou erro nesse diagnóstico não interrompe
o fluxo normal de produção.

## Limites (importante)

- **Prévia somente:** `status: preview_only_not_rendered`. A montagem final
  `video.combine_videos` ainda não recebe esse mapeamento.
- `match_status: term_match_unverified` representa associação por termo
  **e não** verificação do que aparece na imagem ou vídeo.
- Nenhuma pessoa, local ou acontecimento histórico é identificado; por exemplo,
  a palavra-chave "Gramsci portrait" não significa que o Pixabay forneceu um
  retrato autêntico de Antonio Gramsci.
- O fallback não inventa correspondência: uma cena sem material de sua
  consulta permanece com `assigned_material_file: null` e gera aviso.
- O módulo está condicionado à opção de ordenar imagens pelo roteiro e a
  bancos de mídia gratuitos existentes. Outros provedores e geração paga
  continuam seguindo o caminho anterior.
- A antirrepetição (02A) ainda governa a renderização antiga.

## Testes Windows (sem APIs)

```powershell
uv run pytest -q test/services/test_rick_scene_plan.py test/services/test_rick_scene_assignment.py test/services/test_rick_scene_pipeline.py
```

Depois execute os testes de regressão de `test/services/test_rick_pipeline.py`,
`test/services/test_media_diversity.py` e
`test/services/test_media_diversity_flow.py`.

## Próxima etapa 02B2B

Inserir uma política opcional de montagem que **respeite as janelas por cena**
e escolha materiais somente dentre as opções relacionadas à consulta da cena.
Tratar cobertura insuficiente explicitamente, preservar a sincronização do
áudio, não fazer downloads pagos adicionais, manter `main` estável e
exigir testes reais com mídias antes de afirmar alinhamento visual.
