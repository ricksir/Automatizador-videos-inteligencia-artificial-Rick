# Rick 02E — Curadoria visual: contexto, negação e metáforas

## Evidência real da tarefa Gramsci

A primeira chamada ao Gemini analisou seis cenas em seis requisições:
**cinco respostas `uncertain` e uma `plausible`**. O modelo descreveu
um rio com barco, um trem, uma pintura de mulher com livros e um homem
sorrindo em trechos sobre ideias e disputas políticas. A cena 4 foi
considerada `plausible` por mostrar fogo como metáfora de violência.

Há um erro particularmente importante na frase distribuída entre cenas:
- cena 3: "grupos podem mudar isso **sem**"
- cena 4: "**precisar de revoluções violentas**"

O sentido é a **ausência de necessidade de violência**. Chamas não são
evidência visual direta desse argumento e a metáfora pode dar a
impressão oposta. O teste com metadados `24/24` não mede coerência real.

## Correção

1. O pedido ao Gemini inclui até dois trechos anteriores e posteriores
   (tamanho total limitado), indicando claramente o trecho central.
   Isso ajuda a preservar negações, comparações e frases interrompidas
   pelos cortes do roteiro.
2. Nova classificação da relação visual:
   `direct`, `contextual`, `metaphorical`, `unrelated`,
   `insufficient`.
3. `plausible` somente pode ser exibido se a relação for **direta**.
   Se o Gemini declarar `plausible` mas indicar relação metafórica,
   apenas temática ou insuficiente, o Rick muda o **veredito exibido**
   para `uncertain` e recomenda procurar alternativa.
4. O resultado continua sendo opinião falível da IA, nunca aprovação.
   A classificação direta ainda exige checagem humana e de direitos.
5. O painel mostra separadamente veredito, tipo de relação, próximo
   passo e justificativas completas por cena, sem truncamento da tabela.
6. Resultados anteriores (`version=1`) não são apresentados como se
   tivessem passado pela política nova (`version=2`).

## Limites

- Não corrige automaticamente o vídeo final nem substitui imagens
  apenas por classificar uma mídia como metafórica.
- O Gemini só recebe quadros mediante consentimento explícito e clique.
  Cada lote tem até seis requisições e dois quadros por mídia.
- O prompt pode melhorar a precisão mas não garante interpretação
  correta; cenas abstratas podem permanecer `uncertain`.
- Nenhuma permissão, licença, pessoa ou fato histórico é verificado
  como verdadeiro apenas pelo modelo.
- Nenhuma aprovação humana, renderização nova ou publicação é acionada.

## Testes

```powershell
uv run --no-sync python -X utf8 -m pytest -q test/services/test_rick_02e_semantic_rigor.py test/services/test_rick_02d_semantic_frame_review.py
```

Homologação manual: analisar novamente as cenas 1–6 da tarefa
Gramsci, comparando as evidências textuais, especialmente cenas 3–4.
Não converter `uncertain` em `plausible` para melhorar cobertura.
