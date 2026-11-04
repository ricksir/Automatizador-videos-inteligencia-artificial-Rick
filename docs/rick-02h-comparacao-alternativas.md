# Rick 02H — Comparar até duas alternativas por cena com análise visual

## Ponto de partida

O Rick já sabe identificar mídia sem relação direta com a narração (PR #28),
buscar alternativas para cenas sinalizadas (PR #29) e repetir falhas de API
sem reavaliar as demais cenas (PR #30). A recuperação até aqui escolhia
**um** candidato por metadados e não comparava outras opções caso a IA
retornasse apenas uma correspondência contextual/metafórica.

## Nova análise sob ação explícita

O botão de busca/reavaliação agora oferece **Máximo de alternativas por
cena: 1 ou 2** (padrão 2), sempre limitado a três cenas por execução.

1. Busca fotos e vídeos apenas para até três cenas não aprovadas e
   sinalizadas na primeira análise (a configuração de bancos mantém limites
   existentes de downloads, origem e tamanho).
2. Seleciona um primeiro candidato por metadados somente para inspeção.
3. Envia até dois quadros para Gemini com a narração e contexto vizinho.
4. Se a relação for **direta e plausível**, não usa outra chamada para
   aquela cena. Se a análise concluir relação contextual, metafórica,
   insuficiente ou incompatível, seleciona outra mídia (se houver).
5. Repete uma única vez a avaliação no segundo candidato. O total é
   **no máximo seis chamadas por clique** (3 cenas x 2 alternativas);
   no modo 1, no máximo três chamadas.
6. Se o provedor falhar, não multiplica as chamadas para aquela cena.
   Os erros continuam tratados pelo fluxo de retentativa separada.
7. Resume todas as alternativas avaliadas por cena, com evidência,
   tipo de relação, fonte de origem e indicação da IA para revisão humana.
8. Apenas uma avaliação válida **plausible + direct com evidência visual**
   poderá indicar um arquivo para inspeção editorial. Duas incertezas,
   uma metáfora ou um score de metadados elevado **não** geram indicação.

A escolha por metadados não é tratada como probabilidade de acerto. A
reutilização é limitada a no máximo duas avaliações do mesmo arquivo
ao longo da execução, favorecendo mídias distintas entre cenas.

## Segurança e limites

- Nenhuma seleção, substituição, aprovação humana ou publicação automática.
- O arquivo principal original permanece intacto.
- A análise utiliza somente a chave Gemini configurada e o consentimento
  explícito existente; há possível consumo de cota e cobrança.
- Imagens históricas, nomes reais, período histórico, direitos autorais e
  licenças **não são certificados** pelo resultado da IA.
- Um 'candidato para revisão humana' não é uma ordem de substituição.
- O botão de montagem MP4 permanece independente deste ranqueamento:
  NÃO utilizar como se estivesse aprovando as comparações.
- O resultado é apenas session state Streamlit e se invalida quando o
  lote original é reavaliado.

## Testes

```powershell
uv run --no-sync python -X utf8 -m pytest -q test/services/test_rick_02h_semantic_ranking.py test/services/test_rick_02f_semantic_remediation.py
```

O CI do PR cobre Linux e Windows no grupo editorial, além da exportação
nativa de vídeo. A suíte geral pode conter falhas fora deste escopo.
