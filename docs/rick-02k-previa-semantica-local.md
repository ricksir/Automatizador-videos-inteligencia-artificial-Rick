# Rick 02K — Prévia MP4 semântica local, sem homologação

## Motivo

O fluxo anterior fazia análise Gemini e busca/reavaliação de até duas
alternativas por cena, em grupos de até três, mas o resultado não era
incorporado a uma **prévia reproduzível**. O exportador existente para
revisão humana exige todas as cenas aprovadas, enquanto o exportador
histórico Commons distribui imagens por rotação de metadados.

## Novo comando experimental

O painel de revisão mostra **Rick — Montar prévia semântica em MP4
(rascunho)** quando existe pelo menos uma busca/reavaliação concluída
no lote. O usuário precisa marcar confirmação explícita e clicar em
**Gerar MP4 de prévia semântica**. A exportação é **local/offline**:
não consulta Gemini, não baixa mídia e não publica.

1. Carrega somente mídia já registrada e permitida pelo inventário
   da tarefa (cache controlado ou materiais editoriais importados).
2. Confere que pré-curadoria e resumo semântico correspondem ao mesmo
   texto, clipe original e fingerprint da prévia atual.
3. Só substitui provisoriamente um arquivo se houver evidência textual
   observada pelo Gemini e uma classificação `plausible + direct`
   coincidente com o arquivo sugerido no ranking conservador.
4. Para as outras cenas, mantém o arquivo original **explicitamente
   identificado como fallback de metadados não validado**.
5. Confere o áudio local, duração planejada, legenda se exigida,
   linhas de tempo, arquivos acessíveis e diretório de saída.
6. Exporta um novo MP4 usando o mecanismo FFmpeg existente, no caminho
   `rick_semantic_drafts/rick-draft-*-final.mp4`.
7. Emite relatório JSON com cena a cena: arquivo escolhido, motivo,
   número de alternativas direct, fontes informadas, quais ainda têm
   fallback, contagem de propostas e ressalvas.

## Proteções

- **Rascunho não homologado.** Correspondência direta segundo o Gemini
  não comprova identidade, precisão histórica, direitos autorais nem
  sincronização temporal.
- Todos os trechos não classificados como diretos permanecem
  semanticamente **não validados**. Não é permitido tratar o arquivo
  como pronto para publicação.
- Nenhum MP4 original é sobrescrito; não altera `rick_editorial_review.json`
  nem o estado de publicação. Não cria aprovação humana.
- Sem pelo menos uma alternativa diretamente plausível, o render é
  bloqueado: reproduzir a mesma montagem sem alteração não agregaria
  valor ao diagnóstico.
- Legendas existentes são preservadas; se necessárias mas ausentes, o
  usuário precisa escolher a opção explícita para rascunho sem legendas.
- O relatório traz `publishing_permitted: false`,
  `human_approved: false`, `rights_legally_verified: false`.

## Teste com Gramsci

Executar análise das cenas 1–6 e recuperação das cenas 1–3 e 4–6.
Abrir o novo expansor e confirmar a geração de rascunho. Se houver
sugestão `direct + plausible`, o MP4 deve incluir essa alternativa
somente nas respectivas cenas. Outras cenas mantêm mídia original e
são contadas no relatório como *fallback não verificado*.

Se todas as alternativas permanecerem contextuais, incertas ou
metafóricas, o botão retornará bloqueio em vez de inventar uma
substituição. Não é necessário gastar outra chamada Gemini apenas
para tentar renderizar um rascunho.

## Validação

```powershell
uv run --no-sync python -X utf8 -m pytest -q test/services/test_rick_02k_semantic_draft.py test/services/test_rick_02j_recovery_batches.py
```

O PR é experimental e empilhado no #33; não altera a branch `main`.
