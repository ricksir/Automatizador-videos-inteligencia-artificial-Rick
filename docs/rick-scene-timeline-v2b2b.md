# Rick — Evolução 02B2B (etapa 1): pré-validação da linha do tempo

O repositório já possui `rick_scene_plan.py` (02B1) e
`rick_scene_assignment.py` (02B2A). O projeto ainda usa
`video.combine_videos` sem um contrato de tempo por cena. Esta etapa
prepara esse contrato **sem acionar renderização**.

## API

`build_scene_render_preflight(candidate_preview, downloaded_files, audio_seconds, max_clip_seconds=4.0)`

Retorna `status=ready_metadata_only` quando:
- As cenas formam uma linha do tempo contígua cobrindo a duração do áudio;
- Cada cena tem material atribuído por consulta compatível;
- O nome de cada arquivo existe de forma não ambígua na lista recebida;
- Segmentos gerados não excedem a duração configurada para cada clipe.

Retorna `status=blocked` e `segments=[]` quando uma ou mais cenas
não têm candidatos (não cria um vídeo silenciosamente com imagens genéricas).
O relatório `blockers` lista números de cenas problemáticas.

**Importante:** `ready_metadata_only` não atesta que um clipe é
decodificável, tem duração suficiente, tem licença válida ou retrata o
objeto citado no roteiro. Os timestamps continuam estimados; não são
alinhamento real da voz.

## Testes (locais, sem rede nem API)

```powershell
uv run pytest -q --basetemp "$env:LOCALAPPDATA\Rick\pytest-timeline" test/services/test_rick_scene_timeline.py
```

## Integração futura no renderizador

A etapa seguinte deverá:
1. Introduzir controle opt-in explícito para montagem por cenas;
2. Validar cada arquivo com FFprobe/FFmpeg e sua duração real;
3. Fazer cortes e repetições controladas dentro de cada janela de cena,
   preservando a duração do áudio e compatibilidade com legendas;
4. Registrar se a renderização respeitou o plano, além do relatório
   aproximado de seleção;
5. Bloquear ou oferecer revisão de cenas faltantes, **sem fallback
   silencioso** para imagens fora do tema;
6. Manter os fluxos antigos inalterados quando a opção estiver desativada.

A etapa atual não muda a WebUI, downloads, chamadas pagas, publicação
ou `video.combine_videos`. Os testes são de metadados, não de qualidade
visual ou renderização final.
