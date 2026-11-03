# Rick 02C/3 — Fotografias e documentos por contexto

## Objetivo
Na tarefa de Gramsci o fallback de resolução recuperou um vídeo, mas 10 de 24 cenas
continuaram sem candidato suficiente. A busca documental oferece alternativas
**sem presumir que nome de arquivo prova o conteúdo visual**.

## Fluxo
1. A busca de clipes Pexels/Pixabay permanece como primeira opção.
2. O mesmo comando de pré-curadoria pode pesquisar o Wikimedia Commons para
   cenas pendentes ou com baixa pontuação de metadados.
3. Apenas categorias controladas são aceitas: instituições, eleições,
   documentos, educação, manifestações e ideias.
4. O nome do arquivo deve conter o termo contextual como palavra inteira.
   Arquivos com logotipos, pôsteres ou temas evidentemente incompatíveis são excluídos.
5. O filtro já existente verifica metadados de CC0/domínio público, JPEG/PNG,
   URL Wikimedia permitida, arquivo de até 12 MB e integridade de pixels.
6. Importa fotografias como MP4s locais de 4 segundos, registrando a URL
   da página de origem e o metadado de licença, sem tocar no vídeo anterior.
7. A pré-curadoria é recalculada e apresenta novos candidatos apenas como
   propostas sujeitas a inspeção visual e à avaliação dos direitos.

## Limites
- Até duas imagens de pessoa histórica e seis imagens contextuais na execução,
  com no máximo seis categorias pesquisadas.
- Não é uma pesquisa de imagens para cada frase genérica; uma cena sem
  evidência pertinente continua sem candidato.
- Metadados de domínio público/CC0 não certificam autenticidade nem todos
  os direitos de uso; a imagem pode representar outro país ou período.
- O movimento e a sincronização exata da narração ainda não são validados.
- Nenhuma aprovação humana é criada e a publicação diária fica bloqueada.

## Testes direcionados
    uv run --no-sync python -X utf8 -m pytest -q test/services/test_rick_02c_context_photos.py test/services/test_rick_scene_precuration.py

Não estabelecer 24/24 propostas como critério isolado; avaliar pertinência real.