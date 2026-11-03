# Rick — piloto de execução diária (rascunho técnico)

Este serviço permite **uma execução de geração por data local** e registra cada
tentativa de publicação para YouTube Shorts, Instagram Reels e TikTok
separadamente. Não é uma promessa de publicação nem uma solução concluída
de curadoria automática.

## Estado funcional

- **Desativado por padrão**. `--execute` não habilita por si só a criação
  nem a publicação. Os campos JSON `enabled` e `publish_enabled` são
  controles independentes.
- Produz um MP4 usando o pipeline já existente do MoneyPrinterTurbo:
  geração de roteiro, narração, download de materiais e renderização.
- Aceita somente as fontes de banco `pexels`, `pixabay` ou `coverr`.
  Mesmo nessas fontes, a busca **não comprova correspondência visual à fala**.
- Só publica quando um **motor de qualidade independente** entregar receipt
  para o hash do MP4 com validações semânticas, temporal, segurança e direitos.
  **Este motor ainda não existe nesta implementação**: portanto, o serviço
  gera e bloqueia publicação com `quality_blocked`. Nunca marque uma
  aprovação automática falsamente para fazer passar esse bloqueio.
- A integração Upload-Post existente pode distribuir a mesma produção para
  `youtube`, `instagram` e `tiktok` após autorização e homologação.
- Se uma publicação foi iniciada, uma queda de rede ou do processo não
  autoriza repetir silenciosamente o mesmo POST.
- A configuração atual exige uma lista de temas distinta, esgotando-a antes
  de repeti-la; geração autônoma contínua de temas é uma etapa futura.
- O serviço é `run-once`. Não instala agendador, não altera configurações de
  contas e não publica ao criar um PR.

## Teste seguro de configuração

Copie o arquivo `config/rick_daily.example.json` para
`config/rick_daily.json`, sem versionar o arquivo privado.
Ajuste a data inicial, os temas, a voz e as configurações de mídia.

```powershell
uv sync --frozen --python 3.11
uv run --no-sync python -m app.services.rick_daily_autopilot --policy config/rick_daily.json
```

O comando acima é **apenas leitura/diagnóstico** e imprime a configuração
sem executar geração ou enviar uploads.

Um teste de execução isolada, quando expressamente habilitado na política:

```powershell
.\scripts\rick_autopilot_once.ps1
```

Esse teste **pode consumir serviços pagos de LLM/TTS/mídia** conforme o
`config.toml`. O arquivo de política não pode conter segredos: contas e
credenciais continuam em `config.toml` / conexões externas.

## Agendamento, após homologação

Para usar o Agendador de Tarefas do Windows, configure uma tarefa diária
que execute `powershell.exe` com o argumento
`-NoProfile -NonInteractive -File "C:\CAMINHO\DO\REPOSITORIO\scripts\rick_autopilot_once.ps1"`.

Uma tarefa marcada **executar apenas com o usuário conectado** exige uma
sessão aberta. Execução com o computador desligado exige um servidor/host
ligado continuamente. Um servidor de produção precisará de observabilidade,
retenção de logs, gerenciamento de credenciais, controle de custos e alertas
de falha.

**Não** habilite a publicação real antes de:
1. Implementar e validar QA automático semântico e de licenças.
2. Testar publicação em contas de homologação, com limites por plataforma.
3. Confirmar os estados incertos e a reconciliação com o serviço remoto.
4. Garantir acesso confiável à infraestrutura e respeitar as regras das
   plataformas.

## Registros e prevenção de duplicação

O histórico está em `storage/rick_autopilot/YYYY-MM-DD.json`; não remova
os registros para forçar republicações. O arquivo
`storage/rick_autopilot/.rick-daily.lock` impede concorrência entre
instâncias. Se uma execução for interrompida abruptamente, a trava ficará
preservada para investigação, em vez de disparar outra publicação por engano.

Os estados por plataforma são `not_started`, `submitting`, `published`,
`failed` e `unknown`. Apenas `published` confirma sucesso informado
pelo provedor; `submitting` e `unknown` **nunca são reenviados
automaticamente**. A reconciliação externa ainda deverá ser implementada.

## Escopo dos próximos incrementos

- Seleção independente de vídeo e imagem por trecho; análise semântica real
  da mídia (não apenas semelhança de títulos ou palavras-chave).
- Marcação de cortes a partir de TTS/SRT com tempos confiáveis, sem usar
  divisão uniforme como se fosse alinhamento palavra-a-palavra.
- Motor de QA por cena e evidência verificável de direitos.
- Renovação automática de pautas com prevenção de repetição e validação factual.
- Monitoramento de publicação e logs de sucesso/erro por plataforma.

O PR relacionado deve continuar em rascunho até esses critérios estarem
atendidos.
