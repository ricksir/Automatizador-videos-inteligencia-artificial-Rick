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
2. Escolha a tarefa. O painel mostra o progresso **salvo** (aprovadas,
   rejeitadas e pendentes); comece com **Uma cena por vez**.
3. No seletor **Escolha o vídeo para assistir**, escolha um arquivo:
   a prévia é atualizada imediatamente, sem precisar salvar primeiro.
4. Assista ao vídeo, confira a relação com a narração e a licença. Registre
   a fonte/condições verificadas, marque as duas conferências e escolha
   **Aprovar** somente quando realmente adequado. Caso contrário, marque
   **Rejeitar** ou deixe **Pendente**; não há preenchimento automático.
5. Clique **Salvar esta cena**. O progresso é atualizado e as decisões humanas
   de outras cenas são preservadas e revalidadas. Use **Próxima cena** e repita.
   Ao trocar o arquivo, o painel limpa as antigas confirmações para exigir
   nova conferência.
6. Com todas as cenas aprovadas e salvas, abra **Rick — Exportar vídeo
   revisado**, confirme a exportação e pressione **Gerar novo MP4 revisado**.
7. Confira o MP4 e o relatório no disco. A exportação considera somente
   as aprovações salvas, não as escolhas ainda em edição.

Se o vídeo original utilizava legendas mas o arquivo subtitle.srt não existe,
a exportação é bloqueada. Para permitir a saída sem legendas, marque
**Permitir exportar sem legendas** explicitamente.


## Quando um clipe mostra conteúdo errado (exemplo: cachoeira para Gramsci)

Os nomes dos arquivos e termos de busca dos bancos de vídeo **não provam**
o conteúdo das imagens. O Rick não reconhece visualmente pessoas ou fatos,
e jamais atribui aprovação automática a clipes ordenados por metadados.

Na revisão de uma cena:

1. Se um vídeo não serve (como uma cachoeira para uma narração sobre Gramsci),
   clique em **Descartar este clipe de toda a tarefa**. Ele deixa de aparecer
   nas opções das outras cenas daquela tarefa, mas o arquivo de cache não é apagado.
   Há uma seção **Clipes descartados nesta tarefa** para restaurar um descarte.
2. Para usar seu próprio material, abra **Adicionar vídeo ou fotografia adequada
   (local)**. Escolha MP4 (máximo 64 MB) ou uma foto JPG/PNG (máximo 12 MB e
   20 megapixels), informe a origem e as condições de uso conhecidas e clique
   em **Adicionar à biblioteca desta tarefa**. JPG e PNG são convertidos por
   FFmpeg local em MP4 vertical silencioso de quatro segundos; a renderização
   pode repetir o trecho de origem para cobrir a cena aprovada.
3. Após importar, escolha a nova mídia no seletor, assista e confira
   correspondência com a narração, autoria e licença. **A importação não
   marca conteúdo nem direitos como conferidos e nunca aprova a cena.**
4. Quando faltar material adequado, mantenha a cena pendente ou rejeitada.
   A exportação permanece bloqueada; não substitua por mídia genérica.

Os novos arquivos ficam somente na subpasta de materiais editoriais da
tarefa; seu catálogo e seus hashes SHA-256 são registrados à parte do
`script.json`. A exportação usa o cache confiável original e, quando
houver, apenas as mídias adicionais registradas e intactas, validando
todos os clipes novamente. Nenhum upload é uma certificação automática
de adequação histórica, direitos autorais ou autenticidade.

Para fotos históricas, consulte fontes com informações verificáveis sobre
autoria, data e condições de licença; páginas e metadados não substituem
essa conferência. A busca de fontes é ação humana separada: importar não
faz download remoto nem aciona IA.

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
