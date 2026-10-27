# Rick — Evolução 02B2C: montagem experimental por cenas

A entrega introduz uma rota **opt-in**, que usa o plano de cenas para
selecionar, cortar e concatenar os vídeos nas janelas definidas pelo roteiro.
O fluxo atual do MoneyPrinterTurbo continua sendo o padrão.

## Como funciona

1. A opção `rick_scene_render_enabled` foi adicionada ao esquema
   `VideoParams`, com valor inicial `false`. Não está na WebUI nesta
   entrega: serve para testes controlados pela API/CLI.
2. Exige **Ajustar imagens à ordem do roteiro** ligado,
   `video_count=1` e fonte de banco de vídeos
   `pixabay`, `pexels` ou `coverr`.
3. Depois do download, lê `rick_scene_candidate_preview` do
   `script.json` e aplica `rick_scene_timeline.build_scene_render_preflight`.
   Se faltar material de uma consulta, a geração falha **antes** da
   renderização, sem preencher a lacuna com mídia genérica.
4. No `video.combine_videos`, abre somente arquivos originados
   da lista de downloads e verifica sua duração e suas dimensões reais.
   O módulo `rick_scene_render.plan_source_slices` calcula os trechos
   de cada vídeo; se um for curto, ele só repete **dentro da cena que lhe
   foi atribuída**.
5. Passa essas fatias para o codificador atual e as concatena em ordem,
   mantendo áudio e legendas na etapa posterior do pipeline.
   A duração extra de segurança é um clipe separado que será aparado
   pelo FFmpeg até a duração da narração.
6. Se uma fatia não codificar, o modo experimental cancela a montagem
   sem utilizar outros materiais como substituição silenciosa.

## Limitações e ressalvas

- A segmentação temporal ainda é **estimada** pelo texto e duração total,
  não sincronizada palavra por palavra ao áudio. A próxima etapa deverá
  usar timestamps confiáveis de legendas e validar o MP4 em cenário real.
- A associação é por consulta de busca, não por compreensão do conteúdo.
  **Não comprova** que a pessoa, evento ou objeto estejam na mídia.
  Especialmente retratos históricos exigem verificação de procedência (02C).
- Se não há correspondência para todas as cenas, o modo experimental
  falha de forma explícita. Pode exigir revisão de termos e fontes.
- Ainda não disponível como caixa de seleção na interface; habilitar
  gradualmente **após aprovação dos testes**, mantendo `false` como padrão.
- Quando o modo está ligado, não se aplica o planejador de antirrepetição
  ao final, pois ele poderia destruir a sequência; a associação anterior
  já tenta preferir origens diferentes.
- `ready_metadata_only` não atesta codecs, duração reproduzível nem
  licenciamento. A inspeção real ocorre ao ler/codificar os vídeos, e
  validação final por FFprobe ainda é uma etapa posterior.

## Testes offline (PowerShell)

```powershell
uv run pytest -q --basetemp "$env:LOCALAPPDATA\Rick\pytest-scene-render" test/services/test_rick_scene_render.py test/services/test_rick_scene_render_task.py test/services/test_rick_scene_video_mock.py
```

Depois rode a regressão:

```powershell
uv run pytest -q --basetemp "$env:LOCALAPPDATA\Rick\pytest-reg-render" test/services/test_rick_scene_timeline.py test/services/test_rick_scene_plan.py test/services/test_rick_scene_assignment.py test/services/test_rick_scene_pipeline.py test/services/test_rick_pipeline.py test/services/test_media_diversity.py test/services/test_media_diversity_flow.py test/services/test_rick_startup_preset.py
```

Os testes usam mídias simuladas; **não geram vídeo real**, não fazem chamadas
a APIs e não publicam nada. Não mesclar antes da aprovação local no Windows.

## Etapa seguinte após os testes

Criar uma opção WebUI com texto claro *Montagem por cenas (experimental)*,
introduzir diagnóstico visual por cena, validar um MP4 real com FFprobe e
revisar a relevância da mídia antes de automatizar qualquer publicação.
