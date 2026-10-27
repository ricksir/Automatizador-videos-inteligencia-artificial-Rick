# Evolução 02B2E1 — Revisão editorial manual por cena

Nesta primeira entrega, sem novas chamadas de rede, IA, serviços de mídia ou alterações à WebUI, foi criado `app/services/rick_editorial_review.py`.

## Qual problema resolve

A correspondência atual por palavra-chave não comprova que um clipe mostre Antonio Gramsci, uma eleição específica ou o evento narrado. O novo módulo exige uma **decisão explícita para cada cena**, com:

- arquivo de vídeo escolhido entre os arquivos **já baixados**;
- nota de origem/procedência preenchida pelo revisor;
- confirmação manual de que o conteúdo foi visto;
- confirmação manual de que o direito de uso foi verificado;
- aprovação ou rejeição explícita.

A seleção pode substituir um candidato genérico por outro arquivo existente, mas nunca inventa um novo download. Sem aprovação completa de **todas** as cenas, o resultado é `blocked`.

## Como usar programaticamente (offline)

```python
from app.services.rick_editorial_review import build_editorial_review
from app.services.rick_scene_timeline import build_scene_render_preflight

review = build_editorial_review(
    candidate_preview,
    downloaded_files,
    [
        {"scene_number": 1, "decision": "approve", "selected_file": "portrait.mp4",
         "source_note": "Origem conferida manualmente: acervo e licença",
         "content_checked": True, "rights_checked": True},
        # Uma decisão deve ser fornecida para cada cena.
    ],
)
if review["status"] != "ready_human_reviewed":
    print(review["blockers"])
else:
    timeline = build_scene_render_preflight(review, downloaded_files, audio_seconds)
```

## Limitações importantes

1. **Não há reconhecimento automático de pessoas**. O campo `content_checked` representa uma declaração humana, não um modelo de visão.
2. **Não há autenticação automática de licenças**. A nota de origem e o `rights_checked` são fornecidos pelo revisor.
3. **Não há interface nesta entrega**. O módulo é independente, para receber uma futura tela com miniaturas e aprovação por cena.
4. **Não há sincronismo por palavra**. O plano de cenas ainda tem tempos estimados.
5. O renderizador existente **não consulta automaticamente** a revisão; só se pode usá-la manualmente na etapa seguinte, depois de implementar a integração segura. O status permanece bloqueado para cenas incompletas.

## Testes Windows

```powershell
uv run pytest -q --basetemp "$env:LOCALAPPDATA\Rick\pytest-editorial-v2b2e1" test/services/test_rick_editorial_review.py
```

Os testes utilizam dados fictícios e mocks, não geram MP4 nem consomem crédito de API.

## Proteção adicional antes da renderização

A aprovação editorial é **fail-closed** em duas camadas:

- `build_editorial_review` elimina `assigned_material_file` e substitui `match_status` por `editorial_review_required` sempre que a cena não estiver integralmente aprovada; candidatos antigos não permanecem selecionados.
- `build_scene_render_preflight` reconhece quando há dados de revisão editorial e impede gerar segmentos se o status geral não for `ready_human_reviewed` ou se qualquer cena não contiver aprovação e as declarações de conteúdo, licença e origem. O fluxo legado sem revisão permanece inalterado.

Os testes cobrem também essas barreiras, para evitar que um consumidor use o plano incompleto diretamente na montagem. Esse guard **não ativa** o fluxo automático de revisão; a futura WebUI precisa confirmar que houve uma decisão humana explícita antes de habilitar o render.
