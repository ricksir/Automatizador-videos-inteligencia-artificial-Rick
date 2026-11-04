# Rick 02D/3 — Configurar IA visual sem alterar o Groq

## Problema observado

O painel de revisão mostrava "Configure a chave Gemini e um modelo multimodal"
enquanto, na janela principal, o provedor LLM estava selecionado como
**Groq** com o modelo `openai/gpt-oss-120b`. O módulo de visão do PR #26
usa Gemini, e a interface anterior só expunha os campos da chave/modelo
Gemini quando ele era selecionado como **LLM principal**. Isso
convidava o usuário a mudar o provedor dos roteiros sem necessidade.

## Correção

1. Abra **Rick — Pré-curadoria automática por cena** e a seção
   **Rick — Avaliação semântica por IA (opcional, envio externo)**.
2. Clique em **Configurar IA visual — sem alterar o provedor de roteiros**.
3. Insira uma chave Gemini do Google AI Studio. A chave não precisa ser
   informada novamente se já existir no aplicativo.
4. Escolha o modelo multimodal:
   - `gemini-3.5-flash-lite` — menor custo/latência para teste.
   - `gemini-3.8-flash` — maior capacidade de análise.
5. Clique em **Salvar configuração da IA visual**.
6. O Groq permanece como o provedor de roteiros; a operação só modifica
   `gemini_api_key` (quando fornecida) e `gemini_model_name`.
7. A autorização de compartilhamento dos quadros continua sendo **separada**
   do cadastro da chave. Só o botão **Analisar este lote com IA visual**
   pode realizar chamadas externas.

A chave é armazenada pelo mecanismo de configuração existente do
MoneyPrinterTurbo, não em novos arquivos nem em texto no painel.
A tela não faz chamada à API no momento em que o formulário é salvo.

## Limitações

- Não consegue inferir ou criar uma chave Gemini sem a conta do usuário.
- A API Gemini pode consumir cotas e gerar cobranças, mesmo quando o
  modelo de roteiros continua configurado no Groq.
- A compatibilidade de cada modelo depende das permissões e da cota
  disponíveis na chave configurada.
- O resultado não confere licença, identidade histórica, contexto de
  todas as cenas nem autorização de publicação.

## Testes

```powershell
uv run --no-sync python -X utf8 -m pytest -q test/services/test_rick_visual_settings.py test/services/test_rick_02d_semantic_frame_review.py
```

A `main` não é alterada e este incremento não publica vídeos.
