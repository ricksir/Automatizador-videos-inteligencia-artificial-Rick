# Rick 02U — Checklist de aceitação operacional do vídeo Gramsci (Windows)

Este guia usa a versão de trabalho da PR #43 (CI de 05/11/2026, 6/6 jobs aprovados). A análise foi validada por testes automatizados, **não** por execução dos arquivos reais do documentário. Nenhuma etapa pressupõe aprovação editorial ou publicação automática.

## 1. Preparar uma instalação sem perder o vídeo original

1. No computador onde o vídeo foi gerado, faça cópia privada de `config.toml` e do diretório `storage/tasks` (especialmente a tarefa Gramsci). Não copie credenciais para o GitHub nem envie `config.toml` em tickets.
2. Abra PowerShell na pasta do repositório GitHub **ricksir/Automatizador-videos-inteligencia-artificial-Rick** e confira `git status --short`. Se houver mudanças locais, preserve-as antes de trocar de branch.
3. Execute:

   ```powershell
   git fetch origin
   git switch -c rick-validacao-02u origin/feature/rick-02t-safe-color-hydration
   uv python install 3.11
   uv sync --frozen
   .\webui.bat
   ```

   Se a branch `rick-validacao-02u` já existir, use `git switch rick-validacao-02u` e verifique se aponta para a versão correta. **Não** use `git reset --hard` ou `git clean -fdx` na instalação com vídeos locais.

4. Acesse o endereço **exibido pelo `webui.bat`**, normalmente `http://127.0.0.1:8501` (a porta pode mudar para 8502–8599 se estiver ocupada).
5. Confirme que a tarefa original ainda aparece. Uma cópia limpa do repositório **não inclui os arquivos `storage/tasks` do outro computador**; mantenha-os no mesmo diretório de armazenamento da aplicação.

> O programa usa o checkout experimental desta PR, não a `main` estável. Não execute botões gerais de geração/publicação para fazer esta aceitação.

## 2. Abrir a tarefa e observar a curadoria inicial

1. Expanda **Rick — Revisão editorial de cenas (experimental)**.
2. Ative **Abrir painel de revisão local** e, em **Tarefa para revisar**, selecione o projeto **Antonio Gramsci**.
3. Confira a pré-curadoria e a lista das seis cenas. Relacione a **fala exata** de cada cena com o clipe que aparece; metadados, nomes de arquivos ou `score` não comprovam correspondência visual.
4. Se a tarefa não aparecer, confirme que o vídeo foi concluído e que o diretório local da tarefa está presente. Não gere um novo vídeo só para substituir o material original.

## 3. Reavaliar visualmente as cenas sem desperdiçar cota

1. Expanda **Rick — Avaliação semântica por IA (opcional, envio externo)**.
2. Em **Configurar IA visual — sem alterar o provedor de roteiros**, informe a chave Gemini **somente se ainda não estiver configurada**; escolha o modelo visual e clique **Salvar configuração da IA visual**. Isso não altera o provedor usado nos roteiros (Groq).
3. Em **Lote de cenas para analisar**, selecione **Cenas 1–6**.
4. **Antes de clicar para analisar**, observe se aparece o aviso **Avaliação e histórico restaurados do armazenamento local da tarefa, sem novas chamadas Gemini**. Se o lote e o modelo forem os mesmos e os dados estiverem corretos, reutilize o histórico. Reanalisar o lote substitui a base e descarta as recuperações anteriores.
5. Se não houver avaliação válida, marque **Autorizo o envio externo dos quadros e dos trechos da narração deste lote à API Gemini** e clique **Analisar este lote com IA visual**. Pode consumir cota ou gerar cobrança; a interface limita a até seis cenas por execução. Sem consentimento, não clique.
6. Anote quantas cenas foram `plausible + direct`, contextuais, metafóricas, incertas ou falharam. O caso histórico observado foi **6/6 avaliações, 0 diretas, 5 contextuais e 1 metafórica**, mas não trate esse resultado como nova execução.

## 4. Recuperar alternativas em dois grupos, sem repetir chamadas

1. Se houver cenas problemáticas, abra **Rick — Encontrar e testar alternativas**.
2. Em **Máximo de alternativas por cena**, selecione **2**. A segunda só é analisada caso a primeira não tenha correspondência direta plausível.
3. Em **Próximo grupo de cenas a recuperar**, confira as **cenas 1, 2, 3** (quando todas as seis estiverem sinalizadas). Com consentimento ativo, clique **Buscar alternativas e reavaliar até 3 cenas com IA**. Limite do aplicativo por grupo: até seis invocações ao SDK Gemini, além de downloads possíveis; o SDK pode efetuar novas tentativas HTTP internas.
4. Confira o diagnóstico e não aprove nada só com base na sugestão da IA. A resposta só deve recomendar arquivo se houver relação **direta, plausível e sustentada por evidência visual**.
5. Observe **Grupos processados: 1/2**. No mesmo lote, selecione o grupo **cenas 4, 5, 6** e faça a segunda execução explícita.
6. Confirme **Grupos processados: 2/2** e a presença dos dois resultados. A recuperação pode terminar com cenas ainda pendentes: isso é um resultado válido, não sucesso editorial.
7. Se ocorrer falha do provedor, use o mecanismo específico de retentativa de falhas; **não** reanalise todo o lote ou reinicie a primeira busca sem necessidade.

**Estimativa de operações:** na pior situação do lote com seis cenas problemáticas, o aplicativo pode fazer até seis invocações ao SDK Gemini na análise inicial, seguidas de até seis para cada grupo de alternativas (até 18 invocações ao SDK no total), além dos acessos aos bancos de mídia. **Esse número não limita as tentativas HTTP reais**, pois o SDK do Google pode repetir requisições automaticamente em erros transitórios, como 429/5xx. Confira cota, credenciais e custos no Google AI Studio antes de autorizar.

## 5. Verificar persistência e retomada

1. Feche o Streamlit sem excluir `storage/tasks`; reinicie com `.\webui.bat`.
2. Selecione a **mesma tarefa, lote e modelo Gemini**.
3. Confira o aviso de restauração local, o histórico dos grupos 1–3/4–6 e a ausência de novas chamadas ao provedor na simples abertura do painel.
4. Os dados ficam em `storage/tasks/<task_id>/rick_semantic_batch_01.json` para o lote 1–6. A persistência não recupera automaticamente chamadas de sessões antigas encerradas **antes** da introdução desse recurso.
5. Se o texto, clipe original, fingerprint ou modelo mudar, o histórico antigo deve ser invalidado; não misture evidências de versões diferentes.

## 6. Gerar a prévia MP4 sem confundi-la com aprovação

1. Com pelo menos uma recuperação concluída, procure **Rick — Montar prévia semântica em MP4 (rascunho)** no painel semântico.
2. A geração é **local**, sem nova busca externa ou Gemini. Se necessário por ausência de `subtitle.srt`, marque conscientemente a opção **Gerar rascunho sem legendas (se necessário)**.
3. Marque **Confirmo que esta é apenas uma prévia local com cenas ainda não validadas** e clique **Gerar MP4 de prévia semântica**.
4. A saída esperada é um novo arquivo sob `storage/tasks/<task_id>/rick_semantic_drafts/` e um relatório JSON que discrimina cenas com indicação visual direta e cenas mantidas como *fallback* não validado.
5. **Se não houver pelo menos uma alternativa `plausible + direct`**, a exportação semântica deve ser bloqueada. Não contorne essa proteção, nem descreva o vídeo como aprovado.
6. Reproduza o MP4 e verifique cortes, duração, sincronia entre áudio e imagens, legendas, factualidade e direitos. Não publique a prévia.

## 7. Aprovar manualmente, somente após inspecionar conteúdo e licença

1. Na seção de **Modo de revisão**, selecione **Uma cena por vez**.
2. Escolha, na própria cena, a mídia correta em **Materiais sugeridos para esta cena (metadados)** ou **Outros materiais disponíveis na tarefa**, e marque **Mostrar prévia do vídeo selecionado**. Também é possível usar **Adicionar vídeo ou fotografia adequada (local)** com informação de origem/licença.
3. Para cada cena adequada, selecione **Aprovar** em **Decisão editorial**, preencha **Origem/licença conferida (registro humano)**, marque as duas verificações de conteúdo e direitos e clique **Salvar esta cena**.
4. Se não houver mídia adequada ou licença comprovada, mantenha **Pendente** ou **Rejeitar**; jamais invente uma aprovação.
5. Apenas quando **todas** as cenas estiverem aprovadas manualmente, a seção **Rick — Exportar vídeo revisado** poderá oferecer **Gerar novo MP4 revisado**, após confirmação específica. Essa saída é distinta do rascunho semântico e não substitui o original.
6. Não use comandos de upload/postagem. A revisão humana de uma mídia não é autorização automática para publicar em plataforma alguma.

## 8. Evidência mínima para encerrar a aceitação

Registre, sem credenciais:
- versão/branch testada e tarefa selecionada;
- resultado das seis cenas (direta, contextual, metafórica, incerta, não resolvida);
- contagem dos grupos completados (ex.: 2/2), propostas diretas e pendências;
- confirmação de restauração após reinício sem novas chamadas;
- caminho do MP4 de rascunho, se gerado, e do relatório JSON; ou motivo de bloqueio;
- se existe ou não aprovação humana de todas as cenas;
- confirmação de que MP4 original e publicação permanecem intactos.

### CI e integração

A PR #43 validou em GitHub Actions as matrizes Python 3.11/3.13 (2.927 testes aprovados por versão, zero falhas), smoke Windows, revisão editorial Linux/Windows e exportação MP4 nativa. **Isso não substitui a inspeção do vídeo Gramsci na estação real.**

Este guia foi acrescido em PR documental empilhada sobre #43. As PRs de recursos permanecem **em rascunho e encadeadas**; não mescle uma PR isolada diretamente na `main`. Antes de integrar, confira a cadeia inteira desde a primeira PR ainda não mesclada, todas as dependências e o impacto nas funções de geração/publicação. Uma integração com merge/squash exige decisão explícita de release.
