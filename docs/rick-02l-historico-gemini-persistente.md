# Rick 02L — Histórico Gemini persistente por lote

## Objetivo

Eliminar repetição de chamadas Gemini e buscas de mídia após reiniciar o
Streamlit durante a curadoria de um vídeo já produzido. Os resultados
continuam sendo **opiniões de IA**, sem qualquer aprovação editorial ou
autorização para publicar vídeos.

## Funcionamento

- O recurso grava o resumo das análises das cenas e os grupos de
  alternativas avaliadas em `storage/tasks/<task_id>/rick_semantic_batch_01.json`,
  `..._07.json`, etc. Os arquivos são criados apenas ao concluir uma
  ação solicitada pelo usuário e não contêm chaves API nem quadros de vídeo.
- Cada lote está associado ao fingerprint da prévia original, número/texto/
  mídia principal de cada cena e modelo Gemini usado. Mudança de qualquer
  desses elementos invalida a restauração e não dispara busca nova.
- Ao abrir o mesmo lote, a interface carrega o arquivo local sem abrir
  conexão ao Gemini, restaura o histórico de até três cenas por grupo e
  apresenta apenas os grupos ainda não processados.
- Reavaliar o lote ou repetir somente falhas na API substitui a avaliação
  original e zera os grupos de recuperação daquele lote, para não misturar
  evidências diferentes.
- Se um arquivo de alternativa for removido, a respectiva recuperação
  é desconsiderada e aparece novamente como grupo pendente. Se o clipe
  original não existe mais, a avaliação original não é restaurada.
- Não são persistidos: credenciais, quadros em JPEG, dados brutos,
  mensagens de solicitação ao provedor, caminhos privados, contas de
  publicação ou arquivos de vídeo.
- O histórico local é limitado a 512 KiB por lote, ignorando arquivos
  corrompidos e recusando links simbólicos; a gravação usa `os.replace`
  para evitar registros parcialmente escritos.

## Limites

- O controle reduz chamadas repetidas do fluxo normal após reinícios,
  mas não é um bloqueio transacional de sessões simultâneas concorrentes.
- Ao atualizar da versão anterior, **consultas já realizadas em sessões
  Streamlit encerradas não podem ser recuperadas**, se não foram salvas
  pelo mecanismo anterior. O armazenamento passa a atuar a partir de
  novas análises.
- A persistência não realiza análise ou busca em segundo plano.
  Toda interação com Gemini ou os bancos de mídia continua exigindo
  consentimento e clique explícito.
- Os resultados não substituem verificação da identidade, fatos
  históricos, direitos autorais ou licenciamento de materiais.

## Testes

```powershell
uv run --no-sync python -X utf8 -m pytest -q test/services/test_rick_02l_semantic_persistence.py
```

### Exercício de aceitação

1. Na tarefa Gramsci, executar análise semântica das cenas 1–6.
2. Executar recuperação das cenas 1–3.
3. Encerrar e reiniciar o Streamlit, abrir a mesma tarefa/lote/modelo.
4. Confirmar que a análise e a recuperação 1–3 estão disponíveis sem
   chamada externa. O próximo grupo deverá ser as cenas 4–6.
5. Recuperar 4–6, reiniciar e confirmar os dois grupos visíveis.
6. Modificar texto/mídia principal do roteiro de teste: o histórico antigo
   não deve ser reutilizado.
7. Verificar que nenhum vídeo foi publicado e nenhuma aprovação humana foi
   inferida pela persistência.

Este recurso pertence ao PR #35, empilhado sobre o PR #34; `main` permanece
inalterada até revisão e integração explícitas.
