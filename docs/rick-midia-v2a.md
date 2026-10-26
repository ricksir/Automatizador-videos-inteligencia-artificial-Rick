# Rick — Evolução 02A: antirrepetição de mídia

Escopo: identificação de materiais e diversidade na montagem, conforme a
[Issue #2](https://github.com/ricksir/Automatizador-videos-inteligencia-artificial-Rick/issues/2).
Não implementa plano de cenas, reconhecimento de pessoas ou busca histórica.

## Fluxo existente examinado

- `app/services/material.py`: busca por termos nas fontes existentes, filtro de
  orientação/duração/resolução e eliminação de URLs exatamente iguais. O modo
  narrativo percorre grupos de termos. Os downloads podem ocorrer em paralelo.
- `app/services/material_cache.py`: cache de resultados de busca com validade de
  24 horas. Os registros preservam metadados públicos da origem.
- `material.save_video`: reutiliza o arquivo já baixado quando existe. O nome
  `vid-<MD5>.mp4` deriva da URL completa sem fragmento; a query identifica alguns
  materiais e não é descartada. Downloads novos são validados antes da publicação
  atômica do arquivo no cache.
- `app/services/task.py`: recebe caminhos locais e coordena a montagem. O
  `script.json` já registra `material_sources`, com ID, fornecedor, URL pública de
  origem, arquivo local e outros metadados disponíveis. Há alocação entre vídeos
  de um mesmo lote.
- `app/services/video.py`: divide materiais em cortes, prioriza arquivos distintos
  no modo aleatório e repete os cortes processados quando falta duração. Antes
  da 02A, versões de uma mesma origem em arquivos diferentes podiam ser tratadas
  como materiais distintos, e o ciclo de fallback podia repetir a mesma origem
  consecutivamente.

O código de busca, download e cache foi mantido. A identificação adicional ocorre
sobre materiais locais já disponíveis, sem novas chamadas a fornecedores.

## Ativação

Na área de configurações do vídeo da WebUI, marque **Evitar repetição de materiais
(Rick)**. A opção vem desativada e é independente do perfil Rick — Curiosidades.
Desmarque para manter o comportamento anterior.

O parâmetro correspondente em `VideoParams` é `avoid_repeated_materials`, com
padrão `false`. A opção fica na sessão e nos parâmetros salvos da tarefa; restaurar
uma tarefa restaura a opção. Não altera configurações de Groq, Gemini ou Pixabay.

## Identificação e seleção

O novo módulo `app/services/media_diversity.py` reúne referências equivalentes por:

1. ID público combinado com o fornecedor.
2. URL de origem normalizada, quando disponível no manifesto.
3. SHA-256 dos bytes do arquivo local, também para cópias com nomes diferentes.
4. Caminho normalizado como identificação provisória quando faltam os anteriores.

Aliases são unidos transitivamente. IDs iguais de fornecedores diferentes não
são confundidos. URLs são armazenadas no diagnóstico somente como hashes;
fragmentos não participam dessa identidade. A query é preservada no cálculo,
pois até um parâmetro chamado `token` pode identificar um material diferente.
URLs temporárias diferentes ainda podem ser unidas por ID de origem ou pelos
bytes do arquivo, sem presumir que apontam para a mesma mídia.
Arquivos com o mesmo nome em diretórios distintos não recebem automaticamente
os metadados de uma única entrada ambígua do manifesto.

Após as verificações existentes de leitura do vídeo, a montagem escolhe uma
versão por origem e intercala seus cortes. A linha de montagem usa cada origem
disponível antes de reutilizá-la e alterna origens quando precisa preencher a
narração. Os cortes já processados são reutilizados por referência, sem solicitar
novo download ou nova codificação para cada repetição do fallback.

Com apenas uma origem utilizável, repetições consecutivas são inevitáveis e
recebem aviso explícito. Sem nenhum material utilizável, a montagem falha com
diagnóstico, sem criar substitutos. Falhas de download, leitura e processamento
continuam excluindo os itens inválidos.

## Diagnóstico

O campo `media_diversity` do `script.json` registra, por vídeo:

- Quantidade de referências baixadas, origens identificadas e duplicatas.
- Arquivos cujo hash não pôde ser verificado.
- Identidades e arquivos selecionados, sem URLs de download.
- Duração necessária e cobertura em uma passagem por origens distintas.
- Número de reutilizações de origem e de repetições consecutivas.
- Avisos de insuficiência ou de ausência de alternativas.

Os avisos também entram no resultado da tarefa e são mostrados em linguagem
clara na WebUI. Um manifesto de diagnóstico pode existir mesmo se a montagem
falhar; a falta de materiais não é apresentada como sucesso visual.

Exemplo de aceite simulado: **45 s, cinco materiais e cortes de 4 s** resultam em
20 s de cobertura sem reutilizar uma origem. O fallback alterna as cinco origens,
sem repetições consecutivas, e informa que foi necessário reutilizar materiais.
A margem técnica de montagem não gera aviso falso quando a parte visível do
vídeo já está coberta.

## Testes locais isolados

Na raiz do projeto, com as dependências já instaladas:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest test.services.test_media_diversity test.services.test_media_diversity_flow -v
```

Os testes usam bytes de referência, clipes fictícios e mocks de downloads,
codificação e concatenação. As funções de montagem e tarefa são executadas sem
inicializar a aplicação, usando o isolamento já empregado nos testes do Rick.
Não abrem configuração real, não acessam APIs e não geram áudio ou vídeo.

## Limites da entrega

- Não mede similaridade visual/perceptual. Versões recomprimidas sem uma origem
  comum verificável podem escapar à comparação por bytes.
- O hash exige leitura dos arquivos locais, apenas quando a opção está ativa.
- A identificação após o download não evita todos os downloads redundantes já
  realizados pela busca. O cache existente continua sendo aproveitado.
- A alternância pode mudar a ordenação dos materiais. Ordem não comprova
  sincronização com uma frase; essa associação pertence à 02B.
- Não verifica que uma imagem representa Gramsci ou qualquer outra pessoa.
- Não garante diversidade entre tarefas independentes. A alocação existente por
  lote permanece disponível, mas não há histórico global de mídia nesta etapa.
- A revisão de um MP4 real permanece pendente, conforme a restrição de não gerar
  vídeos nesta entrega. Não há aprovação de qualidade visual real.

Groq, Gemini TTS, publicação automática, Português (Brasil), perfil Rick e o
backup existente foram preservados. Nenhum novo provedor ou dependência foi
integrado. Não houve commit, push ou merge.
