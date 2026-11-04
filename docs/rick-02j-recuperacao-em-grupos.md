# Rick 02J — Recuperação de todos os grupos sem repetir as mesmas três cenas

## Problema observado — Gramsci (04/11/2026)

O painel retornou 6/6 avaliações Gemini válidas, 0 correspondências
diretas, 5 relações contextuais e 1 metafórica. Todas as 6 cenas precisam
de nova mídia.

A rotina anterior `run_semantic_remediation` selecionava automaticamente
somente as três primeiras cenas problemáticas. Repetir o botão na mesma
tarefa iniciava outra busca nas cenas 1–3 em vez de progredir para 4–6,
com potencial de novas requisições e custos, apesar de as cenas restantes
continuarem sem alternativas.

## Alteração

- A função agora aceita `target_scene_numbers=[4,5,6]`, respeitando
  o máximo de 3 cenas por execução.
- Valida rigidamente o pedido: números únicos, inteiros 1–60, não mais
  do que o limite configurado, presentes na avaliação Gemini do **mesmo
  modelo**, com o mesmo vídeo original e o texto da tarefa vigente.
- Cenas já aprovadas por humano, com relação direta plausível ou cuja
  proposta original mudou são bloqueadas antes da busca e da API.
- Chamadas antigas sem essa opção mantêm o comportamento legado (3
  primeiras cenas elegíveis).
- O painel divide as cenas sinalizadas em grupos de até 3, por exemplo
  1–3 e 4–6. Exibe só os **grupos ainda não processados** na seleção.
- Ao concluir um grupo, o resultado é guardado na sessão e o próximo
  grupo aparece. As comparações anteriores são preservadas no painel.
- A reanálise inicial do lote ou nova tentativa de uma falha técnica
  invalida o histórico de grupos e exige nova recuperação, evitando
  misturar bases de avaliação.
- Cada grupo permite 1–2 alternativas por cena, no máximo 3–6
  chamadas Gemini, com confirmação e clique separados.
- Processar grupos não equivale a homologar suas mídias. Caso não haja
  alternativa, o grupo fica concluído com lacuna explícita, sem falso
  sucesso. Nenhum MP4, aprovação ou publicação é alterado.

## Roteiro de validação

1. Na tarefa Gramsci, analisar o lote 1–6 com Gemini: seis cenas
   incertas ou sem relação direta.
2. Em Rick — Encontrar e testar alternativas, manter 2 alternativas.
3. Confirmar que o primeiro grupo oferecido é `Cenas 1, 2, 3` e o
   custo máximo exibido é de seis requisições.
4. Clicar para procurar/reavaliar o primeiro grupo. Conferir os dados
   e garantir que não houve aprovação ou troca automática.
5. Sem repetir a análise inicial, confirmar que o próximo grupo agora
   é `Cenas 4, 5, 6`. Executar esse segundo grupo separadamente.
6. Confirmar que os dois resultados continuam visíveis, com contagem
   2/2 grupos processados e sem botão de repetição automática.

## Testes

```powershell
uv run --no-sync python -X utf8 -m pytest -q test/services/test_rick_02j_recovery_batches.py test/services/test_rick_02h_semantic_ranking.py
```

A atualização pertence à branch do PR e não foi aplicada à `main`.
As APIs externas e cota Gemini continuam sob autorização explícita do
usuário; não há processamento em segundo plano.
