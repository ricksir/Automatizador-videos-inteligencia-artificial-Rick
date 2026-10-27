# Rick 02B2F — Curadoria visual assistida (MVP seguro)

## Objetivo

Reduzir o trabalho editorial de 24–25 cenas em vídeos verticais, especialmente
roteiros sobre pessoas históricas. Este módulo **não é reconhecimento de imagem
por IA**: é uma triagem transparente por palavras e metadados antes da decisão
humana, sem chamadas de API, custos de LLM, downloads ou publicação.

## O que está implementado

- **Análise de riscos por cena:** indica ausências de candidatos, repetições
  de origem e conflitos observáveis nos termos de busca relacionados a pessoas.
- **Contexto de pessoa citada:** quando o título usa construções como
  "o filósofo Gramsci", apresenta uma busca de retratos e fotografias
  históricas no Wikimedia Commons, sem executar a busca por conta própria.
- **Ordenação assistida:** o menu de vídeos exibe o termo de busca registrado
  junto ao nome do arquivo e prioriza as coincidências de consulta e termos
  da narração. **Nunca seleciona automaticamente** nenhum clipe.
- **Painel compacto:** tabela das cenas e seus alertas, alternância entre
  "Uma cena por vez" e "Todas as cenas". As decisões já salvas sobre outras
  cenas são preservadas e revalidadas durante a revisão individual.
- **Separação de responsabilidades:** a revisão permanece em
  `rick_editorial_review.json`; o script e os MP4 não são modificados
  pela triagem.

## Como usar

1. Abra `.\webui.bat` e expanda **Rick — Revisão editorial de cenas**.
2. Selecione Gramsci ou Céu azul no menu de tarefas.
3. Expanda **Rick — Triagem visual e buscas históricas**. Leia avisos por cena.
4. Caso seja um tema histórico, siga o link do Wikimedia Commons e confira
   individualmente a página de cada fotografia, autor, licença e requisitos
   de atribuição. **O fato de uma mídia estar em Commons não significa
   automaticamente que ela é livre de todas as obrigações.**
5. Revise uma cena por vez. Escolha o clipe visualmente, assista, valide as
   condições de uso e salve; outras decisões já registradas são preservadas.
   O vídeo antigo não será regenerado.

## Fotografias estáticas no vídeo final

O MoneyPrinterTurbo **já tem** uma fonte de material **Local** na tela
de geração, com upload de JPG, JPEG, PNG ou BMP e conversão de imagens em
clipes pelo fluxo existente (`app/services/material_upload.py`,
`video.render_image_zoom_video`). Para experimentar fotografias
históricas, obtenha-as legalmente, mantenha os créditos, escolha **Local**
e faça upload manual antes de gerar **uma nova tarefa**, com aprovação
explícita dos custos envolvidos. A pesquisa no Wikimedia Commons aqui é
apenas um link; não automatiza download nem injeta imagens na tarefa antiga.

**Limite importante:** o relatório editorial não controla ainda uma
remontagem automática das tarefas históricas. Também não existe verificação
semântica visual real: a palavra "Gramsci" num termo não prova que a pessoa
esteja no clipe. O modo compacto organiza o trabalho, mas não garante
que o tema do vídeo será representado corretamente sem curadoria.

## Testes no Windows

Esta branch depende de `main` com os PRs #13 e #14 integrados.

```powershell
git switch main
git pull --ff-only origin main
git fetch origin
git switch -c feature/rick-curadoria-visual-v2b2f --track origin/feature/rick-curadoria-visual-v2b2f
powershell -ExecutionPolicy Bypass -File .\scripts\rick_validar_curadoria.ps1
```

Depois, abra `.\webui.bat` e confirme que o painel funciona nos dois
vídeos de exemplo e que salvar a revisão de **uma** cena não apaga as decisões
de outra. Até essa homologação local, manter o PR aberto, sem merge.
