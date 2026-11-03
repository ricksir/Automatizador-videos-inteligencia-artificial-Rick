# Rick 02D/2 — Avaliação visual semântica assistida por Gemini

## Evidência que motivou o incremento

Na tarefa Gramsci, 48 mídias estavam disponíveis, 24/24 cenas tinham
**proposta por metadados** e 19 arquivos principais foram inspecionados
por dois quadros. Nenhum alerta de duplicação/quadros vazios apareceu,
mas vários clipes eram estáticos, o que é esperado para fotos históricas.

Inspeção de pixels não mede correspondência do conteúdo com a fala.

## Operação

1. Abra **Rick — Avaliação semântica por IA (opcional, envio externo)**,
   no painel de revisão.
2. Configure **gemini_api_key** e **gemini_model_name** para um modelo
   multimodal com suporte a entrada de imagens nas configurações existentes.
3. Selecione um lote de seis cenas, leia e marque a autorização expressa
   para envio de quadros e trechos à API do Google.
4. Clique em **Analisar este lote com IA visual**.
5. O Rick envia à Gemini até dois JPEGs pequenos (320 px de lado maior)
   por proposta e o texto de uma cena. São no máximo seis requisições
   por clique. O serviço pode consumir cota e gerar custos da API.
6. O resultado de cada cena é **plausible**, **mismatch** ou **uncertain**,
   acompanhado de evidência declarada pela IA e justificativa.
7. As respostas são exibidas apenas na sessão Streamlit e não alteram as
   mídias propostas nem as decisões humanas salvas. Se o candidato for
   alterado, o resultado antigo deixa de ser exibido.

## Salvaguardas e limites

- Sem checkbox e clique, **nenhum quadro é enviado** externamente.
- Abrir a página, buscar vídeo, renderizar ou gerar um vídeo diário não
  dispara a avaliação remota nem consome cota.
- Sem chave e nome de modelo compatível configurados, a função é bloqueada.
- Cenas que não constam no inventário ou cujos arquivos são inválidos ou
  symlinks não são enviadas.
- Uma falha do serviço ou resposta malformada vira **uncertain**; nunca
  é interpretada como correspondência comprovada.
- O modelo pode confundir épocas, pessoas e objetos; a análise é só uma
  proposta de julgamento editorial e **não verifica a identidade de Gramsci**.
- Direitos autorais/licenças, precisão histórica e sincronização temporal
  permanecem fora desse teste.
- Nenhuma cena é aprovada, publicada ou automaticamente substituída.
- Não existe envio de vídeo completo: apenas quadros de baixa resolução.
- Os textos e imagens enviados à API ficam sujeitos às condições do Google;
  avalie a política de privacidade e o preço da chave antes de autorizar.

## Testes

```powershell
uv run --no-sync python -X utf8 -m pytest -q test/services/test_rick_02d_semantic_frame_review.py
```

## Próxima etapa

Depois de validar qualitativamente a resposta visual da IA e a adequação
da política de dados, implementar a correção automática de propostas
**somente com evidência forte**, preservando o veto a publicação e a
necessidade de avaliação de licenças. Realizar alinhamento temporal com
a narração antes de considerar a automação diária.
