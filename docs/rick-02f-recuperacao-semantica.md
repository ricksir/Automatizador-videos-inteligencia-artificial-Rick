# Rick 02F — Busca e reavaliação das alternativas após alerta semântico

## Evidência
Na tarefa Gramsci, o primeiro lote de seis cenas retornou cinco análises
incertas e uma análise metafórica permissiva. O PR #28 corrigiu a leitura
de frases partidas ('sem precisar de revoluções violentas') e distinguiu
metáforas de correspondência visual direta. Mas não procurava novas mídias.

## Novo fluxo, explicitamente solicitado por clique
1. Na avaliação semântica Gemini, analisar até seis cenas com chave e
   consentimento próprios. A primeira análise não altera propostas.
2. Se houver `uncertain`, `mismatch`, `contextual`, `metaphorical` ou
   `unrelated`, aparecerá **Buscar alternativas e reavaliar até 3 cenas com IA**.
3. Ao clicar, a rotina verifica se o resultado original é da mesma versão,
   modelo e mídia ainda proposta para a cena; ignora cenas já aprovadas
   por uma pessoa ou as que já têm plausibilidade direta.
4. Pesquisa **somente** até três cenas sinalizadas, usando Pexels/Pixabay
   e Wikimedia Commons: até três vídeos novos e quatro fotos históricas/
   documentais; URLs, tamanho e filtros de licença originais continuam ativos.
5. Atualiza apenas o inventário local de candidatos, sem reescrever o
   manifesto, a pré-curadoria gravada ou qualquer aprovação editorial.
6. Seleciona um candidato alternativo com pontuação de metadados mínima
   de 40, excluindo o MP4 principal já avaliado e limitando repetições.
7. Submete até um candidato por cena ao Gemini, com até duas amostras JPEG
   por candidato e o contexto narrativo das cenas vizinhas. Até três
   chamadas Gemini extras por clique.
8. Exibe veredito de IA, relação visual, fonte, evidência e ação recomendada.
   Se não houver alternativa, registra a lacuna sem inventar cobertura.

## Limites e não objetivos
- Nova mídia é apenas **candidata**: nada é selecionado, aprovado, exportado
  ou publicado automaticamente. Decisão humana e direitos permanecem à parte.
- A avaliação semântica ainda pode errar, principalmente em imagens de
  fatos históricos ou conceitos abstratos. O algoritmo de busca não deve
  transformar um assunto amplo em prova de correspondência.
- O clique autoriza novo acesso a bancos gratuitos e até três requisições
  Gemini com cota/custo. Não ocorre ao abrir painel ou ao executar o programa.
- O histórico de 24/24 propostas por metadados não representa 24/24 cenas
  semanticamente corretas. Nenhuma cena é marcada como aprovada pela IA.
- Cenas já aprovadas por humano não participam desta nova busca.

## Testes offline
    uv run --no-sync python -X utf8 -m pytest -q test/services/test_rick_02f_semantic_remediation.py test/services/test_rick_02e_semantic_rigor.py

## Homologação
Na tarefa Gramsci, revisar o resultado das cenas 1–6 com a política nova,
usar o novo botão e verificar o número de novos arquivos e as avaliações.
Conferir especificamente as cenas 2–4 e não promover imagem de barco,
trem ou fogo a 'correspondência direta' sem evidência literal pertinente.
Confirmar que o vídeo original, as aprovações e a publicação permanecem iguais.