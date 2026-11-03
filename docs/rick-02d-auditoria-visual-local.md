# Rick 02D/1 — Inspeção de quadros reais por FFmpeg (sem IA)

## Evidência no teste de Gramsci
Com o fallback Wikimedia, a tarefa passou de 14/24 para 24/24 propostas por metadados,
com 42 mídias disponíveis e 16 arquivos principais distintos. **24/24 propostas
não significa 24/24 vídeos semanticamente corretos**.

## O que é verificado
- Após a ação explícita de pré-curadoria, o Rick lê até dois quadros por
  arquivo principal selecionado, limitando a 20 arquivos diferentes.
- Extração exclusivamente local, usando FFmpeg distribuído com a aplicação.
- Detecta candidatos visualmente muito escuros, muito claros, com conteúdo
  quase estático ou com impressão visual próxima a outra mídia.
- Cada aviso é um indicador técnico, não uma reprovação automática.
- Registra número de arquivos lidos, falhas de extração e possíveis repetições.
- Nenhum arquivo é enviado a terceiros, alterado, aprovado ou publicado.
- A interface corrige o título enganoso 'pré-curadoria parcial 24/24' para
  'propostas completas por metadados', ainda sem homologação.

## O que não é verificado
- A verificação não reconhece Gramsci, pessoas, épocas, objetos, símbolos
  nem conceitos da narração. Também não confirma licenças ou fontes.
- A comparação de quadros pode indicar coincidência entre cenas distintas,
  e fotografias históricas estáticas são esperadas em várias cenas.
- A sincronia dos cortes com as palavras continua estimada nas tarefas antigas.
- Os controles de revisão e aprovação humana permanecem inalterados.

## Execução
Na tarefa de Gramsci use o botão já existente:
'Buscar novas fotos e vídeos e pré-curar todas as cenas'.
Depois abra 'Inspeção local de quadros — indicadores técnicos' no resultado.

## Testes
    uv run --no-sync python -X utf8 -m pytest -q test/services/test_rick_02d_visual_media_audit.py

## Próximo incremento
Acrescentar avaliação semântica real dos quadros, via provedor de visão
multimodal configurado e explicitamente autorizado. Preferir análise local
quando disponível. Não enviar mídias locais nem habilitar APIs cobradas
sem habilitação expressa e política de privacidade. O processo não pode
atribuir aprovação jurídica ou editorial a uma descrição de IA.