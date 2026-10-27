# Rick — teste real offline da montagem por cenas (02B2D)

Esta etapa valida o pipeline real de vídeo no Windows com **FFmpeg 9.x /
FFprobe**, a biblioteca MoviePy usada pelo MoneyPrinterTurbo e a função
\`video.combine_videos\`. Não é um teste de tema, pessoas ou narração.

## Pré-requisitos

- Abrir o PowerShell na raiz do repositório;
- \`uv sync --frozen --python 3.11\` já concluído;
- \`ffmpeg -version\` e \`ffprobe -version\` devem funcionar no terminal.

## Executar

\`\`\`powershell
uv run python scripts/rick_scene_smoke.py
\`\`\`

O teste cria, sem acesso à rede:
- \`red.mp4\`: clipe vermelho sintético, 540×960, 2,7 s;
- \`green.mp4\`: clipe verde sintético, 540×960, 2,7 s;
- \`tone.wav\`: tom de 440 Hz, com 4 s, **não é voz real**;
- uma linha do tempo estimada com vermelho de 0 a 2 s e verde de 2 a 4 s.

O script valida o plano com \`build_scene_render_preflight\`, exige
que uma cena sem candidato seja bloqueada, chama **o montador de
cenas real** de \`app/services/video.py\`, e depois chama
\`video.generate_video\` para incluir áudio, sem legendas nem BGM.

Por último usa FFprobe e FFmpeg para comprovar:

1. \`rick_scene_final.mp4\` contém **áudio e vídeo**;
2. Tem resolução **1080×1920** (vertical 9:16);
3. Duração aproximadamente **4 segundos** (tolerância de 0,35 s);
4. Um frame do início é **vermelho**, um frame depois de 2 s é
   **verde**: ordem de cenas comprovada sem depender apenas dos metadados;
5. A lista de materiais que entrou na montagem é
   \`red.mp4\` seguida de \`green.mp4\`.

## Onde ficam os resultados

Os arquivos são guardados em \`storage/rick_smoke/\`, que já está
excluída do Git pelo \`.gitignore\`. O teste não substitui
\`config.toml\`, não publica vídeos, não chama Groq/Gemini/TTS,
não utiliza créditos pagos e não altera a base de dados.

Abra \`storage/rick_smoke/rick_scene_final.mp4\` para assistir ao resultado.
O relatório técnico fica em \`storage/rick_smoke/report.json\`.

Em caso de falha, o script exibe **TESTE E2E FALHOU**, sinaliza erro e
retorna código de saída 1. Nesse caso **não mesclar o PR**; enviar
os últimos registros do PowerShell (sem chaves ou tokens) para correção.

## Limitações

Este teste comprova funcionamento com mídias sintéticas e áudio em forma de
tom. Não valida fidelidade de retratos, licenças de materiais reais, buscas
por Gramsci, alinhamento palavra a palavra da fala, nem publicação.
A geração de vídeos com matéria real e revisão editorial é uma etapa
posterior. O parâmetro \`rick_scene_render_enabled\` continua desligado
por padrão; este script testa diretamente o montador de cenas.
