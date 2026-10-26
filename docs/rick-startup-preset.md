# Inicialização do Rick — preset de produção (Issue #3)

Ao abrir a WebUI após instalar esta evolução, o Rick aplica **uma vez** um
conjunto de preferências de produção: perfil Curiosidades, pt-BR, Pixabay,
antirrepetição, correspondência à ordem do roteiro, vídeo 9:16 com clipes de
4 segundos, Gemini TTS Charon, ausência de música, legenda branca inferior de
tamanho 55 e publicação automática desativada.

O preset altera somente preferências nas seções locais `[ui]` e `[app]`.
**Não** modifica chaves Groq/Gemini/Pixabay, senhas, URLs ou credenciais,
não gera conteúdo automaticamente e não liga publicação automática.
A fonte de voz só funcionará se o usuário tiver sua própria chave Gemini.

## Uma vez, depois persistência normal

Na primeira abertura com esta evolução, o programa grava
`rick_startup_preset_version = 3` na seção `[ui]` de seu arquivo local
`config.toml`. A configuração de vídeo anterior poderá ser substituída
**somente nessa primeira aplicação**. Depois disso, alterações efetuadas
na interface são persistidas normalmente e não serão reaplicadas na próxima
abertura. Desmarcar Rick — Curiosidades ou Evitar repetição de materiais deve
continuar desmarcado após reiniciar.

A geração de tema, roteiro e palavras-chave continua manual; os campos
são iniciados vazios numa sessão nova. Não são importados projetos ou
tarefas anteriores automaticamente.

## Testar

1. Finalize a geração atual, se houver, e encerre a WebUI.
2. Faça backup seguro do `config.toml` **fora do repositório** caso deseje
   preservar preferências anteriores. Nunca publique esse arquivo.
3. Reabra a WebUI e confira os padrões iniciais.
4. Desmarque os dois controles Rick, mude a duração de 4 para 5 segundos e
   feche/reabra a WebUI. Essas escolhas devem ser preservadas.
5. Confirme que Groq, Gemini e Pixabay continuam configurados, que o tema está
   vazio e que nenhum vídeo/publicação começou automaticamente.
6. Verifique sem APIs reais:
   `uv run pytest -q test/services/test_rick_startup_preset.py`.

Se a fonte `BeVietnamPro-Bold.ttf` não estiver disponível, o seletor atual
escolhe uma alternativa instalada sem impedir o carregamento.

O preset **não resolve** correspondência semântica, fotografias históricas ou
suficiência de materiais. Essas são atividades separadas da Issue #2.

## Correção da persistência (versão 3)

A versão inicial gravava os valores no arquivo mas não zerava os valores antigos
que o navegador podia restaurar para os controles do Streamlit. Na abertura,
esses controles voltavam a gravar opções antigas, mesmo quando o preset tinha
sido aplicado. A versão 3 sincroniza o estado dos controles **em cada nova sessão de navegador**, mesmo após o preset global ter sido marcado como aplicado. Essa sincronização ocorre antes da renderização e respeita preferências já alteradas e salvas.

Quem testou as versões 1 e 2 receberá **uma aplicação corretiva única** do perfil na
primeira abertura da versão 3. Depois, a preferência de cada controle deverá
persistir, inclusive quando Rick ou antirrepetição estiverem desmarcados.
Para evitar uma tela antiga, feche a aba WebUI e abra uma nova após reiniciar
`webui.bat`. Nenhuma chave de API é alterada.

O diagnóstico da versão 2 mostrou marcador 2 já salvo junto com valores antigos (`rick_profile_enabled=false`, `video_clip_duration=2`, `tts_server=azure-tts-v1`, etc.). O problema era que apenas a primeira sessão reaplicava os controles, enquanto novas sessões podiam sobrescrever o arquivo a partir de estados antigos do Streamlit. A versão 3 sincroniza cada sessão nova com os valores persistidos, evitando esse retorno silencioso ao padrão antigo.
