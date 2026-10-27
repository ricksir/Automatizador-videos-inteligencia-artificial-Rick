# Rick 02B2E2B — Recuperação offline de prévias para tarefas antigas

## Problema

A interface "Rick — Revisão editorial de cenas" pode mostrar "Tarefa sem prévia por cena"
para vídeos criados antes de `rick_scene_candidate_preview` ou sem a opção
"Ajustar imagens à ordem do roteiro". Isso **não significa** que a WebUI falhou.

## Recuperação sem novas chamadas externas

Ao abrir uma tarefa que não tenha prévia, o painel tenta reconstruí-la **em memória**
usando apenas o que já foi registrado no próprio computador:

- `script.json` com roteiro (`script`), configurações (`params`) e termos da busca (`search_terms`);
- `material_sources` com procedência dos clipes efetivamente baixados;
- lista de caminhos existentes registrados no estado da tarefa;
- duração numérica positiva do áudio registrada no estado da tarefa, ou
  `rick_quality.audio_duration.seconds` no manifesto.

A recuperação aceita somente fontes Pixabay, Pexels e Coverr e não faz downloads,
transcrições, TTS, chamadas à Groq/Gemini ou publicações. O plano é **estimado**
e a correspondência entre consulta e clipe **não comprova o assunto nem a identidade
de pessoas**, exigindo revisão editorial humana.

A prévia recuperada não altera `script.json`. A escolha/aprovação do revisor
é armazenada no artefato separado `rick_editorial_review.json`.
A revisão não muda o vídeo existente e não habilita a renderização automaticamente.

Se faltarem metadados, registros de origem, arquivos físicos, duração do áudio ou
roteiro, o painel informa exatamente qual dado está ausente. Não busca materiais
substitutos nem inventa uma ligação entre o áudio e os clipes.

## Validação no Windows

Esta branch depende da revisão editorial 02B2E2A (PR #13);
validar antes de qualquer merge:

```powershell
git fetch origin
git switch -c feature/rick-legacy-review-recovery-v2b2e2b --track origin/feature/rick-legacy-review-recovery-v2b2e2b
uv run pytest -q --basetemp "$env:LOCALAPPDATA\Rick\pytest-legacy-review" test/services/test_rick_editorial_workspace.py test/services/test_rick_editorial_review.py test/services/test_rick_scene_timeline.py test/services/test_rick_pipeline.py test/services/test_rick_scene_pipeline.py
```

Abrir `.\webui.bat`, expandir "Rick — Revisão editorial de cenas (experimental)",
ativar "Abrir painel de revisão local" e escolher Gramsci ou "Por que o céu é azul?".
Se os metadados da tarefa estiverem completos, o painel exibirá um aviso azul de
prévia reconstruída e os controles de revisão. Se os dados não existirem, será
necessário gerar nova tarefa **somente quando o usuário decidir**, selecionando
"Ajustar imagens à ordem do roteiro" antes de gerar.

Apenas os testes offline foram escritos até agora: execução real depende do Windows.

## Complemento: recuperação do cache local

A inspeção real das tarefas antigas identificou **10** registros de mídia no
vídeo Gramsci, **19** no vídeo céu azul, e **29** clipes no cache local
`storage/cache_videos`. As duas tarefas tinham `script.json` e vídeos
exportados, mas não apresentavam candidatos no painel.

As tarefas antigas podem perder o campo de estado `materials` ou ter nele
caminhos provenientes de outro computador. A WebUI agora passa a pasta
`storage/cache_videos` obtida pelo próprio aplicativo; quando o caminho
registrado no estado não resolve, a recuperação aceita **somente nomes exatos
já cadastrados em `material_sources[].local_file`** e arquivos existentes,
não vazios e não simbólicos **dentro** dessa pasta confiável. Os demais
arquivos do cache não são oferecidos para seleção. Caminhos ambíguos
continuam excluídos. Não há busca na internet ou no sistema de arquivos
inteiro, nem permissão para informar diretórios arbitrários.

Contagem total do cache não comprova coincidência dos nomes; a conferência
final depende da WebUI no computador do usuário. Foi adicionada cobertura
para recuperação com estado vazio, conteúdo não registrado, ambiguidade,
arquivo vazio e links simbólicos.

