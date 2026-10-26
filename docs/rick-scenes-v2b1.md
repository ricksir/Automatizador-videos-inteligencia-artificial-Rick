# Evolução 02B1 — Planejamento preliminar de cenas (Rick V2)

Este módulo **não** modifica a busca ou a montagem do MoneyPrinterTurbo.
É uma etapa offline e reversível de construção de um plano de cenas para
preparar a Evolução 02B2 (integração à seleção e ordenação de materiais).

## O problema
Atualmente, a função `llm.generate_terms` produz palavras-chave ordenadas.
`material._download_videos_by_script_order` percorre os candidatos por grupo.
Isso melhora a sequência geral, mas **não** prova que cada trecho narrado
corresponda à imagem exibida. No teste do vídeo sobre Antonio Gramsci,
apareceram cenas genéricas, sem fotografia documental apropriada.

## Contrato
`app.services.rick_scene_plan.build_scene_plan(script, terms, audio_seconds, target_clip_seconds=4)`

Retorna objeto JSON com `scenes`: `number`, `start_seconds`, `end_seconds`,
`text`, `search_term`, `alignment: estimated`, `media_verified: false`,
além de avisos e metadados. O texto é preservado, sem remover acentos.
As janelas são estimativas distribuídas ao longo da duração medida do áudio.
As palavras-chave respeitam a ordem informada; repetir uma consulta gera aviso.

**Limites:** sem timestamps do TTS/transcrição; divisão textual e janela temporal
são aproximações. O planejador não inspeciona imagens, não confere pessoas,
não valida licença e **não garante** que um banco de vídeos contenha um
retrato real. Não substitui a etapa histórica (02C).

## Verificação local sem APIs
`uv run pytest -q test/services/test_rick_scene_plan.py`

## Próxima etapa 02B2
Integrar este plano **somente em modo opcional**, preferencialmente com
tela de prévia e `scene_plan` em `script.json`; associar candidatos a cada
consulta e uma janela real na montagem, respeitando a antirrepetição da
Evolução 02A. Não modificar fluxos antigos quando desativado.
Depois, usar timestamps reais onde disponíveis (02B3).

Não contém chaves de API, não faz downloads, não gera mídia nem publica.
