# Rick — Exportar MP4 a partir das cenas aprovadas

## Resultado

O painel **Rick — Exportar vídeo revisado** aparece quando todas as cenas
receberam aprovação humana na revisão editorial. Após confirmação explícita,
o Rick usa os arquivos locais aprovados e o áudio original para criar um novo
MP4 na subpasta rick_reviewed_exports de armazenamento da tarefa.

- O vídeo antigo, script, revisão e estado da tarefa são preservados.
- Não há novas chamadas para LLM, TTS, bancos de vídeos, APIs pagas ou publicação.
- O exportador usa o mecanismo de cenas já testado com MoviePy e FFmpeg.
- Os arquivos de mídia precisam existir e estar registrados no manifesto.
- A WebUI e o CLI fornecem explicitamente a pasta confiável de cache de vídeos;
  a API `prepare_reviewed_export(..., cache_dir=...)` exige esse argumento.
  A exportação não pesquisa clipes soltos na pasta da tarefa nem aceita
  caminhos informados pelo manifesto como substitutos.
- Os tempos de cena seguem estimados, sem alinhamento por palavra.

## Utilização na WebUI

1. Abra o painel **Rick — Revisão editorial de cenas (experimental)**.
2. Escolha a tarefa e revise cada cena.
3. Selecione um clipe, visualize-o, confira direitos e correspondência,
   registre a origem e aprove a cena.
4. Salve a revisão local. Repita até que todas as cenas estejam aprovadas.
5. Reabra o painel; na seção **Rick — Exportar vídeo revisado**,
   confirme a exportação e pressione **Gerar novo MP4 revisado**.
6. Confira o caminho do MP4 e do relatório mostrado na interface.

Se o vídeo original utilizava legendas mas o arquivo subtitle.srt não existe,
a exportação é bloqueada. Para permitir a saída sem legendas, marque
**Permitir exportar sem legendas** explicitamente.

## Teste e alternativa PowerShell

Execute na pasta MoneyPrinterTurbo:

~~~powershell
uv run pytest -q --basetemp "$env:LOCALAPPDATA\Rick\pytest-export-revisado" test/services/test_rick_review_render.py
uv run python scripts/rick_exportar_revisado.py --task-id SEU_ID_COMPLETO
uv run python scripts/rick_exportar_revisado.py --task-id SEU_ID_COMPLETO --confirm
~~~

A segunda linha valida somente o plano; a terceira gera outro MP4.
Opcionalmente acrescente --sem-legendas.

## Restrições deliberadas

- Não usa mídia genérica para preencher cenas sem aprovação.
- Não renderiza tarefas parcialmente revisadas.
- Não reconhece pessoas ou verifica imagens automaticamente.
- Não certifica licenças nem veracidade de conteúdo.
- Não recupera material removido do cache.
- Não inclui músicas de fundo nesta exportação.
- Em caso de erro, os arquivos incompletos de uma nova tentativa podem ser
  examinados na subpasta de exportação, sem tocar nos vídeos anteriores.
- Dívidas preexistentes de CI permanecem registradas na Issue #16.
