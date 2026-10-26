# Rick — Curiosidades: evolução 01

O perfil é opcional e vem desativado. Quando ativo, usa português brasileiro
(`pt-BR`), orienta o LLM para curiosidades curtas e verifica se a narração real
está entre **35 e 50 segundos, inclusive**.

## Ativar e desativar na interface

1. Na área de configurações do roteiro, marque **Rick — Curiosidades**.
2. O idioma passa temporariamente a **Português (Brasil)**. Ao desmarcar, a
   seleção anterior de idioma é restaurada.
3. Digite ou cole o roteiro para ver a estimativa abaixo do campo. Ativar o
   perfil não reescreve esse texto e não dispara geração.
4. Desmarque a opção para voltar ao fluxo original, sem a validação de 35–50 s.

A ativação fica na sessão da interface e nos parâmetros da tarefa. Não altera
as configurações dos provedores. O gerador usado pelo perfil é o LLM configurado;
o seletor alternativo de geração em lote fica desabilitado enquanto o perfil
estiver ativo, sem substituir sua configuração salva.

## Estimativa e diagnóstico

- A estimativa usa **150 palavras por minuto**. É uma referência inicial,
  não uma medição da voz nem uma aprovação da duração real.
- Uma estimativa curta ou longa gera aviso e não regenera o roteiro.
- Após o TTS ou reaproveitamento de uma prévia, o processo mede novamente o
  arquivo de áudio, usando os segundos fracionários, sem arredondar para cima.
- `35.0` e `50.0` são aprovados. `34.9999` e `50.0001` são reprovados.
- Em caso de reprovação, o processo termina em `rick_audio_quality` antes das
  legendas, dos downloads de clipes, da renderização e da publicação.
- O áudio permanece disponível para ouvir na tarefa reprovada. O roteiro, os
  parâmetros, os termos já disponíveis e os diagnósticos ficam no `script.json`
  do diretório da tarefa. O estado também registra o caminho do áudio.
- Não há regeneração automática para corrigir duração. Revise manualmente o
  roteiro antes de solicitar outra narração.
- A aprovação se refere à duração. Não certifica correção factual, qualidade
  editorial, sincronização das legendas ou adequação visual.

## Verificação local isolada

Na raiz do projeto, com o ambiente já instalado:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest test.services.test_rick_quality test.services.test_rick_scripts test.services.test_rick_pipeline test.services.test_webui_rick -v
```

Esses testes usam configuração fictícia, bloqueiam conexões de rede e substituem
as chamadas a provedores por mocks. Não iniciam a WebUI real, não abrem a
configuração local e não sintetizam áudio nem renderizam vídeo.

Os testes da Parte C executam as funções reais selecionadas do código por AST,
sem executar a inicialização da aplicação. Verificam a persistência do manifesto
em diretórios temporários dentro do projeto, removidos ao fim de cada caso.
O arquivo chamado `audio.mp3` nesses testes contém apenas bytes de referência;
nenhum áudio real é gerado ou decodificado.

## Conferência visual manual

A WebUI real não foi iniciada pelo agente. Para inspecioná-la no ambiente normal,
o usuário pode usar seu procedimento habitual ou executar, na raiz:

```powershell
.\.venv\Scripts\python.exe -m streamlit run webui/Main.py --server.address=127.0.0.1
```

Essa inicialização normal usa a configuração existente da aplicação. Para
conferir apenas o formulário, marque o perfil, cole um roteiro e observe a
estimativa; depois desmarque e confira o idioma anterior. Não é necessário clicar
em gerar, ouvir prévia, testar conexão ou publicar. A validação após o TTS pode
ser conferida sem custos pelos testes isolados acima; geração real não faz parte
da validação executada nesta entrega.

## Arquivos da Parte C

- `app/services/task.py`: persistência do diagnóstico e bloqueio por áudio medido.
- `webui/Main.py`: controle de ativação, idioma temporário, estimativa e resultados.
- `test/services/test_rick_pipeline.py`: testes isolados do fluxo e dos artefatos.
- `test/services/test_webui_rick.py`: testes da interface com Streamlit simulado.
- `docs/rick-curiosidades.md`: funcionamento e instruções de verificação.

As alterações anteriores das Partes A e B permanecem no módulo de qualidade,
no LLM, nos modelos, no controlador e nos testes já criados. A publicação
automática, os adaptadores de provedores e o backup `webui/Main.py.bak-ptbr`
não foram modificados pela Parte C.

## Desativação e reversão

Para suspender o perfil, basta desmarcar **Rick — Curiosidades**.

Para remover somente a Parte C após revisar o diff, reverta seus trechos em
`app/services/task.py` e `webui/Main.py`, mantendo a integração de roteiro da
Parte B em `task.py`. Remova apenas os dois arquivos de teste da Parte C e este
documento. A seleção interativa `git restore -p` permite revisar cada trecho;
restaurar `task.py` inteiro também removeria a integração anterior da Parte B.

Nenhuma reversão, commit ou push foi executado automaticamente.
