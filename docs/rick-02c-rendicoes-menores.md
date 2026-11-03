# Rick 02C/2 — recuperação de MP4s maiores que 64 MiB

## Problema confirmado no Windows

Na tarefa Gramsci, o painel relatou na cena 2:
`intent=demonstrations; provider=pixabay; stage=download; code=video_too_large`.
Foram 14/24 propostas com 35 arquivos na tarefa e 16 candidatos já vistos
no catálogo. Portanto, aumentar a biblioteca não é garantia de correspondência.

## Solução implementada

- A busca de Pexels e Pixabay agora informa, em metadados internos, até quatro
  rendições alternativas verticais fornecidas pelo próprio provedor.
- O serviço de geração de vídeo existente **continua escolhendo sua
  resolução original**; as alternativas se aplicam somente ao fluxo opt-in
  da pré-curadoria.
- O Rick primeiro tenta a URL original. Se ela estourar **64 MiB**, tenta as
  variantes da mesma mídia, da maior para a menor resolução, com mínimo de
  360 × 640 e mantendo o formato vertical.
- Reaplica a lista estrita de hosts HTTPS permitidos, rejeita URLs com
  credenciais ou redirecionamentos e valida os bytes recebidos.
- Não repete a mesma URL em erro permanente; não altera o limite de
  download/importação. O identificador de origem é preservado na importação.
- O painel mostra quantos vídeos passaram a usar rendição menor e quantos
  originais excediam o limite.
- Falha persistente continua sendo documentada, sem correspondência
  inventada. Não autoriza aprovação humana nem publicação automática.

## O que isso NÃO resolve

- Não corrige outros erros de download ou falta de respostas com resultados.
- Não confirma que o conteúdo visual corresponda à narração.
- Não garante que as 10 cenas pendentes receberão mídia; isso exige
  busca de novas fotos/vídeos e análise visual.
- Não usa o aumento irrestrito do limite para processar vídeos pesados.

## Testes

```powershell
uv run --no-sync python -X utf8 -m pytest -q test/services/test_rick_02c_fallback_renditions.py test/services/test_rick_02c_stock_diagnostics.py test/services/test_rick_scene_precuration.py
```
