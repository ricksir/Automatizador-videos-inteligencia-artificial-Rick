# Rick — Pré-curadoria automática por cena

## Processo

Ao abrir uma tarefa na revisão, o Rick analisa automaticamente a intenção de
cada trecho e classifica os materiais já presentes. Não há uploads, cobranças
nem downloads nessa etapa local.

O botão **Buscar novas fotos e vídeos e pré-curar todas as cenas** executa
a busca opcional de fotografias no Wikimedia Commons e vídeos contextuais
nos provedores Pexels/Pixabay, quando existirem chaves de API configuradas.
O sistema importa no máximo oito fotos e oito vídeos por execução, registra
origem/URL e prepara por cena um candidato principal e até duas alternativas.

A tabela mostra consulta específica, pontuação de METADADOS e cenas pendentes.
Não é reconhecimento de imagens nem probabilidade real de acerto visual.
A mídia proposta aparece no seletor, mas nenhuma cena é aprovada automaticamente.

## Limites e segurança

- Nunca substituir uma cena sem correspondente por vídeo genérico sem evidência.
- Limitar repetição do mesmo arquivo a duas cenas, por padrão.
- Não modificar o vídeo original nem as decisões já aprovadas pelo humano.
- Invalidar propostas quando mudar a prévia ou o inventário de arquivos.
- Download de MP4 apenas de domínios permitidos, sem redirecionamentos,
  até 64 MB por arquivo; fotografias históricas passam pelo filtro Commons.
- Não assumir autenticidade da pessoa, conteúdo efetivo nem direitos só por
  nomes de arquivos, resultados de API ou condições indicadas em metadados.
- Não sincroniza cenas ao instante real da narração: o plano histórico mantém
  intervalos estimados. Alinhamento de áudio é um incremento futuro.
- Não ativa publicação diária nem produz a auditoria que o piloto exige.

## Testes direcionados

Executar no PowerShell, na raiz do repositório:

    uv run --no-sync python -X utf8 -m pytest -q test/services/test_rick_scene_precuration.py test/services/test_rick_editorial_panel_ui.py

## Próximos passos

Análise visual real dos quadros, diferenciação entre retrato histórico e
imagem de familiar/monumento, comparação multimodal com o texto, alinhamento
de legendas e voz e avaliação de direitos por plataforma antes de publicar.
