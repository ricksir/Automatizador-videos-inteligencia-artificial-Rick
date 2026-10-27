# Rick 02B2E2A — Painel experimental de revisão editorial de cenas

## Objetivo

Permitir **ver, selecionar, aprovar ou rejeitar** um arquivo de vídeo por cena
a partir de uma tarefa já gerada. Nenhuma chamada à Groq, Gemini, Pixabay,
Pexels, Codex ou serviços de publicação é feita pelo painel.

**IMPORTANTE:** salvar uma revisão NÃO altera automaticamente o vídeo
final, NÃO atualiza o manifesto original `script.json` e NÃO libera
automaticamente a montagem por cenas. A integração entre uma revisão
salva e o renderer pertence a uma etapa futura, com testes específicos.

## Uso no Windows

1. Execute normalmente `.\webui.bat`.
2. Primeiro deve existir uma tarefa criada com:
   - fonte de vídeo em banco suportado (Pixabay, Pexels ou Coverr);
   - opção **Ajustar imagens à ordem do roteiro** habilitada;
   - roteiro e áudio reais, para o Rick salvar o plano de cenas em
     `storage/tasks/<task-id>/script.json`.
3. Role a página abaixo dos painéis de roteiro, vídeo, áudio e legendas.
4. Abra **Rick — Revisão editorial de cenas (experimental)** e marque
   **Abrir painel de revisão local**.
5. Selecione uma tarefa concluída que tenha prévia e vídeos ainda
   existentes no estado da tarefa. Caso os materiais tenham sido
   removidos do disco ou o estado não exista mais, o painel informa a
   indisponibilidade: não tenta novos downloads.
6. Para cada cena, confira o **trecho narrado**, a **palavra-chave** e o
   **arquivo de vídeo**. Marque *Pré-visualizar clipe* para assistir.
   Escolha um arquivo diferente, se necessário.
7. Marque **Aprovar** ou **Rejeitar**. Para aprovar, registre uma nota
   sobre a origem/licença e confirme manualmente conteúdo e direitos.
   Cenas pendentes ou rejeitadas manterão o relatório bloqueado.
8. Clique **Salvar revisão editorial local**.

## Arquivos

A revisão vai para:

```
storage/tasks/<task-id>/rick_editorial_review.json
```

O arquivo contém a seleção, as declarações do revisor, os bloqueios e
um hash da **prévia** que permite detectar se o texto do plano mudou.
Não contém autenticação automática de identidade, licença ou conteúdo.
O script original, chaves de API e vídeos existentes não são modificados.

## Segurança e limitações

- Só são selecionáveis **vídeos existentes** que constam simultaneamente
  no manifesto da tarefa e na lista de materiais baixados guardada pelo
  estado do aplicativo.
- Não é permitido informar caminhos livres ou usar IDs de tarefa com
  separadores de diretório; arquivos de mesmo nome em caminhos
  diferentes são considerados ambíguos e excluídos.
- A aprovação humana exige uma nota de origem e declarações
  explícitas de verificação editorial. O programa **não comprova** que
  o vídeo represente uma pessoa específica, nem autentica licenças.
- Em especial, o mecanismo NÃO é capaz de dizer sozinho se um retrato
  é realmente de Antonio Gramsci.
- O estado do arquivo de mídia **não é autenticado por hash do conteúdo**.
  Se a mídia for alterada depois da aprovação, o usuário deve revisá-la
  novamente; essa verificação deverá ser adicionada antes de qualquer
  integração automática à renderização.
- O painel não modifica o fluxo tradicional e está disponível somente
  quando explicitamente aberto.

## Testes locais

```powershell
uv run pytest -q --basetemp "$env:LOCALAPPDATA\Rick\pytest-editorial-ui" test/services/test_rick_editorial_workspace.py test/services/test_rick_editorial_review.py test/services/test_rick_scene_timeline.py test/services/test_rick_pipeline.py test/services/test_rick_scene_pipeline.py
```

Os testes usam arquivos fictícios como marcadores locais; não geram MP4
nem verificam a interface manualmente. Depois dos testes, abra a WebUI
e confira que o formulário existente continua funcionando.

Esta etapa não deve ser mesclada antes desses testes e da verificação
manual do painel no Windows.
