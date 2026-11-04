# Rick 02G — Tratamento de falhas Gemini sem repetir cenas já avaliadas

## Evidência real — tarefa Gramsci, 04/11/2026

Após adoção do PR #28, a primeira análise de 6 cenas devolveu
**5 avaliações em 6 chamadas**: nenhuma relação direta plausível e
uma metáfora identificada na cena 4. A cena 2 tinha resultado técnico
`provider_or_response_failure`, veredito-padrão `uncertain` e
evidência vazia. Esse estado **não** comprova que a imagem foi analisada.

## Correção

- Distinguir falha de chamada à API (`failure_stage=api_request`) de
  resposta ausente/JSON inválido (`failure_stage=invalid_model_response`).
  Nunca exibir a exceção crua nem expor a chave privada.
- A interface informa quantas cenas ficaram **sem avaliação** por falha.
- Abaixo do relatório de um lote, botão **Reexecutar apenas cenas sem
  avaliação válida**. Requer checkbox de consentimento ativo e clique
  específico; cada cena elegível consome até **uma nova chamada**.
- Os números das cenas para nova tentativa são uma lista restrita de
  no máximo seis; o restante do lote não é enviado novamente.
- Respostas corretas anteriores não são sobrescritas. Só uma cena cuja
  avaliação anterior tinha falha, com o mesmo identificador e arquivo,
  pode ser atualizada.
- Após reexecutar, invalidar os resultados antigos de buscas de
  alternativas daquele lote; evita mostrar dados fora de sincronia.
- Se o erro persistir, a cena segue sem avaliação válida, com indicação
  técnica; não é classificada como material visual adequado.
- Nenhum arquivo original, seleção editorial, aprovação ou publicação
  é alterado; nenhuma nova busca de imagens é feita por este botão.

## Diagnóstico

Um `provider_or_response_failure` pode decorrer de quota, rede, erro
da API, indisponibilidade transitória, ausência de JSON ou resposta
não estruturada. Sem resposta detalhada da API não há como atribuir a
causa específica da falha observada nas capturas. O diagnóstico local
registra apenas a etapa, evitando expor dados sensíveis.

## Testes

```powershell
uv run --no-sync python -X utf8 -m pytest -q test/services/test_rick_02g_semantic_retry.py
```

CI editorial Windows/Linux e exportação nativa independente. Não
promover para `main` com CI regressivo sem auditoria separada.
