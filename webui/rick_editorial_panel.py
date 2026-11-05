"""Streamlit scene review and opt-in automatic Commons-based video export.

Manual approvals remain explicit. The separate automatic workflow uses
machine-screened Commons metadata and never claims human review or publishes.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import streamlit as st

from app.utils import utils

from app.services.rick_editorial_workspace import (
    load_review_workspace,
    save_editorial_workspace_review,
)
from app.services.rick_editorial_assets import (
    excluded_editorial_materials,
    exclude_editorial_material,
    import_editorial_material,
    restore_editorial_material,
)
from app.services.rick_visual_curation import (
    inspect_visual_scenes,
    retained_human_decisions,
    order_review_materials,
    classify_review_materials,
)
from app.services.rick_scene_precuration import build_precuration
from app.services.rick_precuration_workspace import (
    load_precuration, run_scene_precuration,
)


def _clear_scene_evidence(task_id: str, scene_number: int) -> None:
    """Changing a clip requires fresh human verification before approval."""
    st.session_state[f"rick_editorial_decision_{task_id}_{scene_number}"] = "Pendente"
    st.session_state[f"rick_editorial_source_{task_id}_{scene_number}"] = ""
    st.session_state[f"rick_editorial_content_{task_id}_{scene_number}"] = False
    st.session_state[f"rick_editorial_rights_{task_id}_{scene_number}"] = False


def _select_scene_material(task_id: str, scene_number: int, group: str) -> None:
    """Only one material picker is active; all evidence must be reconfirmed."""
    suffix = f"{task_id}_{scene_number}"
    if group == "suggested":
        st.session_state[f"rick_editorial_other_v1_{suffix}"] = None
    elif group == "other":
        st.session_state[f"rick_editorial_material_v4_{suffix}"] = None
    else:
        raise ValueError("Invalid editorial picker group")
    st.session_state[f"rick_editorial_manually_selected_v1_{suffix}"] = True
    _clear_scene_evidence(task_id, scene_number)


def _hydrate_precuration_choice(
    task_id: str,
    scene_number: int,
    proposal: str | None,
    choices: Sequence[str | None],
    *,
    saved_approved: str | None = None,
) -> None:
    """Set a Streamlit widget key BEFORE creation, unlike selectbox index.

    A pre-existing widget value (including None) overrides the `index`
    parameter. Fill it only while the reviewer has never manipulated the
    picker, and never replace an explicit or saved human selection.
    """
    suffix = f"{task_id}_{scene_number}"
    key = f"rick_editorial_material_v4_{suffix}"
    other_key = f"rick_editorial_other_v1_{suffix}"
    manual_key = f"rick_editorial_manually_selected_v1_{suffix}"
    state = st.session_state
    if state.get(manual_key) is True or state.get(other_key) is not None:
        return
    # An existing human approval takes precedence over the new proposal.
    # Restore its selected clip if the old widget session value is empty.
    if saved_approved is not None:
        if saved_approved in choices and state.get(key) is None:
            state[key] = saved_approved
        return
    if not isinstance(proposal, str) or proposal not in choices:
        return
    # Nonempty existing values are either a reviewer choice or a prior
    # proposal. Preserve them. A stale None from the old review UI is
    # specifically the bug this migration fixes.
    if state.get(key) is None or state.get(key) not in choices:
        state[key] = proposal


def _go_to_scene(key: str, number: int) -> None:
    st.session_state[key] = number


def _review_progress(saved_scenes: Sequence[dict[str, Any]], total: int) -> tuple[int, int]:
    """Progress reflects saved human decisions only, never unsaved UI choices."""
    approved = sum(
        scene.get("editorial_review") == "approved_by_human"
        and scene.get("editorial_content_checked") is True
        and scene.get("editorial_rights_checked") is True
        and bool(str(scene.get("editorial_source_note") or "").strip())
        for scene in saved_scenes[:total]
        if isinstance(scene, dict)
    )
    rejected = sum(
        scene.get("editorial_review") == "rejected"
        for scene in saved_scenes[:total]
        if isinstance(scene, dict)
    )
    return approved, rejected


def _priority_scene_numbers(proposals: dict, total: int, *, threshold: int = 60) -> list[int]:
    """List unresolved/low-metadata-evidence scenes, without approving others."""
    return [
        number for number in range(1, total + 1)
        if not proposals.get(number, {}).get("primary")
        or proposals.get(number, {}).get("metadata_score", 0) < threshold
    ]



def _semantic_scene_display(row: dict) -> dict:
    """Do not present an API failure's placeholder as a Gemini judgment."""
    valid = row.get("status") == "ai_assessment_for_human_review"
    status_labels = {
        "provider_or_response_failure": "Falha técnica (API/resposta)",
        "frames_unavailable": "Quadros indisponíveis",
        "invalid_local_media": "Mídia local inválida",
        "not_evaluated": "Não avaliada",
    }
    return {
        "Cena": row["scene_number"],
        "Arquivo": row["file"],
        "Estado": "Avaliada" if valid else status_labels.get(
            row.get("status"), "Avaliação não concluída"
        ),
        "Veredito IA": row["verdict"] if valid else "— (sem veredito)",
        "Relação": row.get("visual_relation", "insufficient") if valid else "—",
        "Próximo passo": (
            row.get("recommended_action", "") if valid
            else "Resolver pendência técnica e reavaliar"
        ),
        "Evidência": row.get("visible_evidence", "") if valid else "",
        "Motivo": row.get("reason", "") if valid else "",
    }


def render_editorial_panel(
    tasks: Sequence[dict[str, Any]],
    state_reader: Callable[[str], dict[str, Any] | None],
    tasks_root: str,
) -> None:
    """Display optional read/approve form. No edits to the original script."""
    st.caption(
        "Revisão local de cenas de tarefas concluídas. A aprovação NÃO altera "
        "o vídeo existente e NÃO inicia uma nova renderização."
    )
    options = [
        task for task in tasks
        if isinstance(task, dict) and isinstance(task.get("task_id"), str)
        and task.get("source") != "active"
        and task.get("state") != 4
    ]
    if not options:
        st.info("Nenhuma tarefa disponível. Gere primeiro um vídeo com plano de cenas.")
        return
    by_id = {task["task_id"]: task for task in options}
    selected_id = st.selectbox(
        "Tarefa para revisar",
        list(by_id),
        format_func=lambda key: f"{str(by_id[key].get('subject', ''))[:60]} ({key[:12]})",
        key="rick_editorial_select_task",
    )
    try:
        state = state_reader(selected_id) or {}
        media_paths = state.get("materials", [])
        if not isinstance(media_paths, list):
            media_paths = []
        workspace = load_review_workspace(
            tasks_root, selected_id, media_paths,
            audio_duration=state.get("audio_duration"),
            cache_dir=utils.storage_dir("cache_videos"),
        )
    except (ValueError, OSError) as exc:
        st.warning(str(exc))
        return

    paths = workspace["paths"]
    preview = workspace["preview"]
    scenes = preview["scenes"]
    if not paths:
        st.warning(
            "Nenhum clipe registrado está disponível. É possível adicionar "
            "material local apropriado abaixo, sem modificar o roteiro ou "
            "recuperar mídias de forma automática."
        )

    if workspace["recovered_preview"]:
        st.info(
            "Prévia reconstruída localmente a partir dos dados da tarefa antiga. "
            "Os intervalos são estimados; nenhuma consulta à IA, download ou "
            "renderização foi realizada. Confira cada cena antes de aprovar."
        )
    saved = workspace["saved_review"] or {}
    old_scenes = saved.get("scenes", []) if isinstance(saved, dict) else []
    if not isinstance(old_scenes, list):
        old_scenes = []
    # Files removed, altered or explicitly discarded cannot retain an active
    # human approval. Keep other saved decisions and do not modify disk here.
    invalidated = 0
    current_scenes = []
    for old_scene in old_scenes:
        if (
            isinstance(old_scene, dict)
            and old_scene.get("editorial_review") == "approved_by_human"
            and old_scene.get("assigned_material_file") not in paths
        ):
            current_scenes.append({
                **old_scene, "editorial_review": "unreviewed",
                "assigned_material_file": None, "editorial_source_note": None,
                "editorial_content_checked": False,
                "editorial_rights_checked": False,
            })
            invalidated += 1
        else:
            current_scenes.append(old_scene)
    old_scenes = current_scenes
    if invalidated:
        st.warning(
            f"{invalidated} aprovações anteriores perderam sua mídia disponível "
            "ou tiveram clipes descartados. Revise novamente antes de exportar."
        )
    approved_count, rejected_count = _review_progress(old_scenes, len(scenes))
    st.progress(approved_count / len(scenes))
    st.caption(
        f"Revisão SALVA: {approved_count}/{len(scenes)} cenas aprovadas • "
        f"{rejected_count} rejeitadas • "
        f"{len(scenes) - approved_count - rejected_count} pendentes. "
        f"{len(paths)} vídeos disponíveis."
    )
    st.caption(
        "Escolha um vídeo para vê-lo imediatamente. Só o botão "
        "'Salvar esta cena' registra a decisão; clipes não são aprovados automaticamente."
    )
    notice_key = f"rick_editorial_notice_v4_{selected_id}"
    if notice_key in st.session_state:
        notice = st.session_state.pop(notice_key)
        if isinstance(notice, dict):
            message = str(notice.get("message") or "")
            if notice.get("level") == "warning":
                st.warning(message)
            else:
                st.success(message)
        else:
            st.success(notice)
    curation = inspect_visual_scenes(
        str(by_id[selected_id].get("subject") or ""),
        scenes,
        [{"local_file": name, **meta}
         for name, meta in workspace["source_metadata"].items()],
    )
    with st.expander("Rick — Triagem visual e buscas históricas", expanded=False):
        st.caption(curation["disclaimer"])
        st.write(
            f"{curation['scenes_with_issues']} de {curation['scenes_total']} "
            "cenas têm alertas de metadados; "
            f"{curation['reused_source_occurrences']} reutilizações de origem "
            "nas sugestões. Isto não é análise do conteúdo visual."
        )
        if curation["subject_anchor"]:
            st.info(
                f"Assunto possivelmente relacionado a pessoa: "
                f"{curation['subject_anchor']}. Busque fotos e documentos "
                "autênticos para conferir manualmente."
            )
            st.link_button(
                "Pesquisar imagens históricas no Wikimedia Commons",
                curation["scenes"][0]["historical_image_search_url"],
            )
        st.dataframe([
            {
                "Cena": row["scene_number"],
                "Trecho": row["text"][:90],
                "Consulta": row["search_term"],
                "Avisos": "; ".join(row["issues"]) or "Verificar visualmente",
            }
            for row in curation["scenes"]
        ], hide_index=True, use_container_width=True)

    # Metadata pre-curation runs automatically for existing task materials.
    # Online media discovery is optional and explicit: never charge/use the
    # network just because a reviewer opened the Streamlit panel.
    try:
        precure = load_precuration(tasks_root, selected_id, workspace)
    except (ValueError, OSError) as exc:
        st.warning(f"Pré-curadoria salva indisponível: {exc}")
        precure = None
    if precure is None:
        precure = build_precuration(
            str(by_id[selected_id].get("subject") or ""),
            scenes, workspace["source_metadata"], list(paths),
        )
    proposals = {
        row["scene_number"]: row for row in precure["scenes"]
        if isinstance(row, dict)
    }
    with st.expander("Rick — Pré-curadoria automática por cena", expanded=True):
        st.caption(
            "O Rick analisou o texto de cada cena e comparou os metadados "
            "dos materiais disponíveis. Identifica contexto, ordena opções "
            "e evita repetições excessivas. Não reconhece pixels nem comprova "
            "se a mídia realmente corresponde à fala ou está licenciada."
        )
        st.write(
            f"{precure['proposed_count']}/{precure['scene_count']} cenas com "
            f"proposta • {precure['unresolved_count']} sem candidato suficiente • "
            f"{precure['unique_selected_files']} arquivos principais distintos."
        )
        st.caption(
            "Pontuação de metadados NÃO é probabilidade de acerto visual. "
            "Nenhuma proposta é aprovação humana e não ativa publicação."
        )
        if st.button(
            "Buscar novas fotos e vídeos e pré-curar todas as cenas",
            key=f"rick_precuration_discover_{selected_id}",
        ):
            with st.spinner(
                "Buscando materiais por contexto de cena e preparando propostas..."
            ):
                try:
                    report = run_scene_precuration(
                        tasks_root, selected_id, media_paths,
                        subject=str(by_id[selected_id].get("subject") or ""),
                        audio_duration=state.get("audio_duration"),
                        cache_dir=utils.storage_dir("cache_videos"),
                        discover=True,
                    )
                except (ValueError, OSError, RuntimeError) as exc:
                    st.error(f"Pré-curadoria bloqueada: {exc}")
                else:
                    # Pre-fill is performed immediately before each picker,
                    # after the fresh workspace is loaded on st.rerun().
                    # This avoids overwriting a human choice with an obsolete
                    # option that was absent from the old inventory.
                    st.session_state[notice_key] = {
                        "level": (
                            "warning" if report["unresolved_count"] else "success"
                        ),
                        "message": (
                            (
                                "Propostas completas por metadados: "
                                if not report["unresolved_count"]
                                else "Pré-curadoria parcial por metadados: "
                            )
                            + f"{report['proposed_count']}/"
                            f"{report['scene_count']} propostas; "
                            f"{report['unresolved_count']} cenas sem "
                            "candidato. A correspondência visual, os direitos "
                            "e a sincronização NÃO foram homologados. "
                            "Nada foi aprovado automaticamente."
                        ),
                    }
                    st.rerun()
        st.dataframe([
            {
                "Cena": row["scene_number"],
                "Trecho": row["text"][:75],
                "Intenção": row["intent"]["kind"],
                "Consulta específica": row["intent"]["query"][:90],
                "Proposta": row["primary"] or "SEM CANDIDATO",
                "Score metadados": row["metadata_score"],
                "Candidatos compatíveis": row.get("eligible_candidates", 0),
                "Situação": (
                    "Proposta para conferir"
                    if row["primary"] else
                    "Limite de reutilização" if row.get("blocker")
                    == "limite_de_repeticao_atingido"
                    else "Sem mídia com metadados suficientes"
                ),
            }
            for row in precure["scenes"]
        ], hide_index=True, use_container_width=True)
        visual = precure.get("visual_audit")
        if isinstance(visual, dict):
            st.markdown("**Inspeção local de quadros — indicadores técnicos**")
            st.caption(
                f"{visual.get('inspected', 0)}/{visual.get('attempted', 0)} "
                "arquivos inspecionados; "
                f"{visual.get('possible_duplicates', 0)} possivelmente semelhantes; "
                f"{visual.get('possible_blank', 0)} possivelmente escuros/vazios. "
                "Foram examinados até dois quadros por arquivo, sem chamada de IA."
            )
            st.warning(
                "Inspeção de pixels NÃO identifica pessoas, objetos, época "
                "histórica ou coerência semântica com a fala. "
                "Propostas continuam pendentes de avaliação editorial e direitos."
            )
            rows = visual.get("files", [])
            if rows:
                st.dataframe([
                    {
                        "Arquivo": item.get("file", ""),
                        "Quadros": item.get("frames_read", 0),
                        "Situação": item.get("status", ""),
                        "Movimento (indicador)": item.get("motion_indicator"),
                        "Possível similar": item.get("similar_to") or "",
                        "Avisos": ", ".join(item.get("flags", [])) or "Sem alertas técnicos",
                    }
                    for item in rows[:20] if isinstance(item, dict)
                ], hide_index=True, use_container_width=True)
        with st.expander(
            "Rick — Avaliação semântica por IA (opcional, envio externo)",
            expanded=False,
        ):
            from app.config import config

            st.caption(
                "Teste limitado: até 6 cenas por execução, enviando até 2 quadros "
                "por mídia e o trecho da narração para a API Gemini configurada. "
                "Pode consumir sua cota ou gerar cobranças. Nenhuma mídia é "
                "enviada sem seu consentimento e um clique explícito."
            )
            # A visual reviewer may use Gemini while scripts remain on Groq.
            # Configure the two existing Gemini-specific keys independently,
            # without touching app.llm_provider or the Groq credentials/model.
            from app.services.rick_visual_settings import (
                save_visual_gemini_settings,
                visual_gemini_snapshot,
                RECOMMENDED_MODELS,
            )
            visual_settings = visual_gemini_snapshot()
            key_ready = visual_settings["key_configured"]
            model_name = visual_settings["model"]
            available_visual_models = list(RECOMMENDED_MODELS)
            if model_name and model_name not in available_visual_models:
                available_visual_models.append(model_name)
            if not key_ready or not model_name:
                st.warning(
                    "Configure abaixo uma chave Gemini e um modelo visual. "
                    "O Groq continuará sendo usado para gerar roteiros."
                )
            with st.popover(
                "Configurar IA visual — sem alterar o provedor de roteiros",
            ):
                st.caption(
                    "A configuração é exclusiva do provedor Gemini. "
                    "Salvar credenciais não consulta a API nem envia vídeos. "
                    "A análise de quadros continua exigindo autorização e clique."
                )
                visual_key = st.text_input(
                    "Chave API Gemini (Google AI Studio)",
                    value="",
                    type="password",
                    placeholder=(
                        "Chave já configurada — deixe vazio para manter"
                        if key_ready else "Cole aqui sua chave Gemini"
                    ),
                    key=f"rick_visual_gemini_key_{selected_id}",
                )
                model_default = model_name or "gemini-3.5-flash-lite"
                visual_model = st.selectbox(
                    "Modelo para comparar imagens com a narração",
                    options=available_visual_models,
                    index=available_visual_models.index(model_default),
                    key=f"rick_visual_gemini_model_{selected_id}",
                    help=(
                        "Flash-Lite prioriza custo; Flash prioriza desempenho. "
                        "O acesso depende dos modelos disponíveis na sua conta."
                    ),
                )
                save_visual = st.button(
                    "Salvar configuração da IA visual"
                )
                if save_visual:
                    try:
                        result = save_visual_gemini_settings(
                            visual_key, visual_model,
                        )
                    except ValueError as error:
                        st.error(str(error))
                    else:
                        if result["status"] == "queued_for_save":
                            st.info(
                                "A atualização foi enfileirada e será salva "
                                "quando a tarefa atual terminar. "
                                "O provedor principal de roteiros permaneceu inalterado."
                            )
                        else:
                            st.success(
                                "Configuração visual Gemini salva. "
                                "O provedor principal de roteiros permaneceu inalterado."
                            )
                        st.rerun()
            choices = list(range(1, len(scenes) + 1, 6))
            first_scene = st.selectbox(
                "Lote de cenas para analisar", choices,
                format_func=lambda n: (
                    f"Cenas {n}–{min(n + 5, len(scenes))}"
                ),
                key=f"rick_ai_visual_batch_{selected_id}",
            )
            authorized = st.checkbox(
                "Autorizo o envio externo dos quadros e dos trechos da "
                "narração deste lote à API Gemini. Estou ciente do "
                "possível consumo de cota ou cobrança.",
                key=f"rick_ai_visual_consent_{selected_id}",
            )
            from app.services.rick_semantic_session_store import (
                load_semantic_batch,
                record_semantic_assessment,
                record_semantic_failed_retry,
                record_semantic_recovery,
            )
            visual_key = f"rick_ai_visual_result_{selected_id}_{first_scene}"
            history_key = f"rick_ai_fix_history_{selected_id}_{first_scene}"
            # Local restoration does not require permission, API credentials
            # or a network request. Model/scene fingerprints are validated.
            if model_name:
                try:
                    restored = load_semantic_batch(
                        tasks_root, selected_id, first_scene=first_scene,
                        workspace=workspace, proposals=precure, model=model_name,
                    )
                except (ValueError, OSError):
                    restored = {"assessment": None, "history": {}}
                if isinstance(restored["assessment"], dict):
                    st.session_state[visual_key] = restored["assessment"]
                    st.session_state[history_key] = restored["history"]
                    st.caption(
                        "Avaliação e histórico restaurados do armazenamento "
                        "local da tarefa, sem novas chamadas Gemini."
                    )
            if st.button(
                "Analisar este lote com IA visual",
                disabled=not (authorized and key_ready and model_name),
                key=f"rick_ai_visual_start_{selected_id}",
            ):
                from app.services.rick_semantic_frame_review import review_scene_frames

                with st.spinner("Inspecionando os quadros e comparando com a narração..."):
                    try:
                        semantic = review_scene_frames(
                            precure, paths,
                            subject=str(by_id[selected_id].get("subject") or ""),
                            api_key=str(
                                config.snapshot_config_with_pending(config.app).get(
                                    "gemini_api_key"
                                ) or ""
                            ),
                            model=model_name,
                            consent=authorized,
                            max_scenes=6,
                            first_scene=first_scene,
                        )
                    except (ValueError, OSError, RuntimeError) as exc:
                        st.error(
                            "Análise semântica indisponível: "
                            + type(exc).__name__
                        )
                    else:
                        st.session_state[visual_key] = semantic
                        # A new baseline evaluation invalidates old comparisons.
                        st.session_state.pop(
                            f"rick_ai_fix_result_{selected_id}_{first_scene}",
                            None,
                        )
                        st.session_state.pop(history_key, None)
                        try:
                            record_semantic_assessment(
                                tasks_root, selected_id, first_scene=first_scene,
                                workspace=workspace, proposals=precure,
                                model=model_name, assessment=semantic,
                            )
                        except (ValueError, OSError) as exc:
                            st.warning(
                                "A análise está visível nesta sessão, mas não "
                                "foi salva para retomada: " + type(exc).__name__
                            )
                        else:
                            st.success(
                                "Análise Gemini registrada localmente. "
                                "Reabrir o Streamlit não consome outra chamada."
                            )
            stored = st.session_state.get(visual_key)
            if isinstance(stored, dict) and (
                stored.get("model") != model_name
                or stored.get("version") != 2
            ):
                # Old, permissive assessments must never be displayed as if
                # they had passed the stronger semantic-context policy.
                stored = None
            if isinstance(stored, dict):
                st.caption(
                    f"{stored.get('assessed', 0)} avaliações retornadas "
                    f"em {stored.get('api_requests', 0)} invocações ao SDK Gemini. "
                    "O SDK pode repetir internamente requisições HTTP em falhas "
                    "transitórias; esse contador não mede cada tentativa HTTP. "
                    "A opinião da IA não equivale à validação editorial."
                )
                current = {
                    row.get("scene_number"): row.get("primary")
                    for row in precure.get("scenes", [])
                    if isinstance(row, dict)
                }
                records = [
                    row for row in stored.get("results", [])
                    if isinstance(row, dict)
                    and current.get(row.get("scene_number")) == row.get("file")
                ]
                # An API/JSON failure is NOT an editorial assessment.
                # Offer an explicit low-cost retry only for failed scenes.
                from app.services.rick_semantic_retry import (
                    failed_scene_numbers, merge_failed_scene_retry,
                )

                failed_rows = [
                    r for r in records
                    if r.get("status") == "provider_or_response_failure"
                ]
                if failed_rows:
                    api_failed = sum(
                        r.get("failure_stage") == "api_request"
                        for r in failed_rows
                    )
                    format_failed = sum(
                        r.get("failure_stage") == "invalid_model_response"
                        for r in failed_rows
                    )
                    st.warning(
                        f"{len(failed_rows)} cena(s) sem avaliação válida "
                        f"(falha na API: {api_failed}; resposta inválida: "
                        f"{format_failed}; causa não classificada: "
                        f"{len(failed_rows) - api_failed - format_failed}). "
                        "Essas cenas NÃO foram consideradas incertas por análise "
                        "de imagem: a avaliação não foi concluída."
                    )
                    # Never show raw API exception text: it may include keys,
                    # request URLs or user data. Old saved errors had no kind.
                    guidance = {
                        "quota_or_rate_limit": (
                            "Limite de taxa/cota (429)",
                            "Confira cota e limites do Gemini; tente depois da liberação.",
                        ),
                        "credential_or_permission": (
                            "Credencial/permissão (401/403)",
                            "Verifique a chave e o acesso ao modelo antes de repetir.",
                        ),
                        "model_not_found": (
                            "Modelo não encontrado (404)",
                            "Confira o modelo visual configurado e seu acesso.",
                        ),
                        "invalid_request": (
                            "Requisição rejeitada (400/422)",
                            "Verifique a configuração; repetir igual pode falhar novamente.",
                        ),
                        "timeout_or_connection": (
                            "Conexão ou timeout",
                            "Verifique a rede antes de fazer outra chamada.",
                        ),
                        "provider_unavailable": (
                            "Serviço Gemini indisponível (5xx)",
                            "Tente mais tarde; não repita em sequência.",
                        ),
                        "other_http_error": (
                            "Outro código HTTP",
                            "Confira o serviço e a configuração antes de repetir.",
                        ),
                        "invalid_response": (
                            "Resposta do Gemini inválida",
                            "A resposta não passou na validação; tente apenas esta cena.",
                        ),
                        "unclassified_api_error": (
                            "Falha não classificada/anterior à atualização",
                            "O erro original não foi salvo; uma nova tentativa "
                            "poderá registrar a categoria, sem expor credenciais.",
                        ),
                    }
                    st.dataframe([
                        {
                            "Cena": row["scene_number"],
                            "Categoria segura": guidance.get(
                                row.get("failure_kind"), guidance["unclassified_api_error"]
                            )[0],
                            "Antes de reexecutar": guidance.get(
                                row.get("failure_kind"), guidance["unclassified_api_error"]
                            )[1],
                        }
                        for row in failed_rows
                    ], hide_index=True, use_container_width=True)
                    st.caption(
                        "É possível reexecutar somente as cenas com falha. "
                        "Isso fará até uma invocação adicional do SDK por cena. "
                        "O SDK pode repetir requisições HTTP automaticamente; "
                        "há possível consumo de cota ou cobrança. "
                        "Não repita se a cota, a chave ou o modelo estiverem bloqueados."
                    )
                    if st.button(
                        "Reexecutar apenas cenas sem avaliação válida",
                        disabled=not (authorized and key_ready and model_name),
                        key=f"rick_ai_visual_retry_{selected_id}_{first_scene}",
                    ):
                        from app.services.rick_semantic_frame_review import (
                            review_scene_frames,
                        )

                        failed = failed_scene_numbers({"results": failed_rows})
                        with st.spinner("Reavaliando somente as cenas com falha..."):
                            try:
                                retried = review_scene_frames(
                                    precure, paths,
                                    subject=str(
                                        by_id[selected_id].get("subject") or ""
                                    ),
                                    api_key=str(
                                        config.snapshot_config_with_pending(
                                            config.app
                                        ).get("gemini_api_key") or ""
                                    ),
                                    model=model_name,
                                    consent=authorized,
                                    first_scene=first_scene,
                                    max_scenes=len(failed),
                                    only_scene_numbers=failed,
                                )
                                merged = merge_failed_scene_retry(
                                    stored, retried,
                                )
                            except (ValueError, OSError, RuntimeError) as exc:
                                st.error(
                                    "Nova tentativa indisponível: "
                                    + type(exc).__name__
                                )
                            else:
                                st.session_state[visual_key] = merged
                                st.session_state.pop(
                                    f"rick_ai_fix_result_{selected_id}_{first_scene}",
                                    None,
                                )
                                try:
                                    persisted = record_semantic_failed_retry(
                                        tasks_root, selected_id,
                                        first_scene=first_scene,
                                        workspace=workspace, proposals=precure,
                                        model=model_name, assessment=merged,
                                    )
                                except (ValueError, OSError) as exc:
                                    st.warning(
                                        "Reavaliação disponível nesta sessão, "
                                        "mas não foi salva: " + type(exc).__name__
                                    )
                                else:
                                    st.session_state[history_key] = persisted["history"]
                                    st.rerun()
                valid_records = [
                    r for r in records
                    if r.get("status") == "ai_assessment_for_human_review"
                ]
                pending_records = [
                    r for r in records
                    if r.get("status") != "ai_assessment_for_human_review"
                ]
                direct = sum(
                    r.get("verdict") == "plausible"
                    and r.get("visual_relation") == "direct"
                    for r in valid_records
                )
                metaphorical = sum(
                    r.get("visual_relation") == "metaphorical"
                    for r in valid_records
                )
                st.caption(
                    f"{direct} correspondência(s) direta(s) plausível(is); "
                    f"{metaphorical} associação(ões) metafórica(s). "
                    "Nenhuma classificação gera aprovação automática."
                )
                st.dataframe([
                    _semantic_scene_display(row) for row in records
                ], hide_index=True, use_container_width=True)
                if pending_records:
                    st.info(
                        f"{len(pending_records)} cena(s) ainda sem avaliação "
                        "visual válida neste lote. Não entram na busca de "
                        "alternativas nem na contagem de grupos processados. "
                        "Resolva as falhas antes de considerar o lote concluído."
                    )
                if valid_records:
                    numbers = [r["scene_number"] for r in valid_records]
                    focus = st.selectbox(
                        "Ler a análise completa da cena",
                        numbers,
                        format_func=lambda n: f"Cena {n}",
                        key=f"rick_ai_visual_detail_{selected_id}_{first_scene}",
                    )
                    detail = next(
                        (r for r in valid_records if r["scene_number"] == focus), None,
                    )
                    if detail is not None:
                        st.markdown(
                            f"**Relação:** {detail.get('visual_relation', 'insufficient')} "
                            f"— **Veredito:** {detail['verdict']}"
                        )
                        st.markdown("**Evidência observada**")
                        st.write(detail.get("visible_evidence") or "Não disponível")
                        st.markdown("**Justificativa**")
                        st.write(detail.get("reason") or "Não disponível")
                        st.caption(
                            "Encaminhamento sugerido: "
                            + detail.get(
                                "recommended_action",
                                "inspecionar_e_buscar_alternativa",
                            )
                        )
                else:
                    st.caption(
                        "Nenhuma cena do lote possui ainda uma avaliação visual "
                        "válida. Detalhes da IA aparecerão após uma resposta válida."
                    )
                if len(records) < len(stored.get("results", [])):
                    st.warning(
                        "Algumas propostas mudaram após a análise. "
                        "Os resultados antigos foram ocultados."
                    )
                st.warning(
                    "Avaliação da IA é falível e não confirma a identidade "
                    "de pessoas, precisão histórica, licença, direitos de "
                    "uso ou alinhamento temporal. Nenhuma cena foi aprovada."
                )
                problematic = [
                    r for r in records
                    if r.get("status") == "ai_assessment_for_human_review"
                    and not (
                        r.get("verdict") == "plausible"
                        and r.get("visual_relation") == "direct"
                    )
                ]
                if problematic:
                    st.markdown("**Rick — Encontrar e testar alternativas**")
                    st.caption(
                        f"{len(problematic)} cena(s) sinalizada(s) neste lote. "
                        "O Rick divide as cenas em grupos de até três, "
                        "evita repetir grupos já processados e mantém os "
                        "resultados válidos no armazenamento local da tarefa. "
                        "Pode fazer downloads e consumir chamadas Gemini."
                    )
                    alternatives_per_scene = st.selectbox(
                        "Máximo de alternativas por cena",
                        options=[1, 2],
                        index=1,
                        key=f"rick_ai_fix_depth_{selected_id}_{first_scene}",
                        help=(
                            "1 = até 3 invocações do SDK por grupo; "
                            "2 = até 6. O SDK pode repetir internamente erros "
                            "transitórios. A segunda alternativa só é testada se a "
                            "primeira não tiver relação direta plausível. "
                            "Nenhuma escolha é aplicada automaticamente."
                        ),
                    )
                    numbers_to_recover = [
                        row["scene_number"] for row in problematic
                    ]
                    stored_history = st.session_state.get(history_key)
                    history = (
                        dict(stored_history)
                        if isinstance(stored_history, dict) else {}
                    )
                    def group_id(group):
                        return ",".join(str(n) for n in group)
                    processed_groups = [
                        tuple(recovery["targets"])
                        for recovery in history.values()
                        if isinstance(recovery, dict)
                        and isinstance(recovery.get("targets"), list)
                    ]
                    processed_scenes = {
                        number for group in processed_groups for number in group
                    }
                    # A previously completed group may have 4,6 while failed
                    # scenes 1,2,3,5 are retried later. Never spend again on
                    # 4,6 simply because the freshly eligible group is 4,5,6.
                    pending_numbers = [
                        number for number in numbers_to_recover
                        if number not in processed_scenes
                    ]
                    pending_groups = [
                        tuple(pending_numbers[i:i + 3])
                        for i in range(0, len(pending_numbers), 3)
                    ]
                    recovery_groups = [*processed_groups, *pending_groups]
                    st.caption(
                        f"Grupos processados: {len(processed_groups)}"
                        f"/{len(recovery_groups)}. "
                        "Um grupo processado não é sinônimo de mídia adequada."
                    )
                    if pending_groups:
                        selected_group = st.selectbox(
                            "Próximo grupo de cenas a recuperar",
                            options=pending_groups,
                            format_func=lambda group: (
                                "Cenas " + ", ".join(map(str, group))
                            ),
                            key=(
                                f"rick_ai_fix_group_{selected_id}_"
                                f"{first_scene}_{len(history)}"
                            ),
                        )
                        max_extra_calls = (
                            len(selected_group) * alternatives_per_scene
                        )
                        st.caption(
                            f"Limite para este grupo: até {max_extra_calls} "
                            "invocações do SDK Gemini, sem contar retentativas "
                            "HTTP internas; pode consumir cota ou gerar cobrança."
                        )
                        if st.button(
                            "Buscar alternativas e reavaliar até 3 cenas com IA",
                            disabled=not (authorized and key_ready and model_name),
                            key=f"rick_ai_fix_start_{selected_id}_{first_scene}",
                        ):
                            from app.services.rick_semantic_remediation import (
                                run_semantic_remediation,
                            )

                            with st.spinner(
                                "Buscando alternativas e avaliando quadros..."
                            ):
                                try:
                                    fixed = run_semantic_remediation(
                                        tasks_root, selected_id, media_paths,
                                        original_proposals=precure,
                                        semantic_assessment=stored,
                                        subject=str(
                                            by_id[selected_id].get("subject") or ""
                                        ),
                                        api_key=str(
                                            config.snapshot_config_with_pending(
                                                config.app
                                            ).get("gemini_api_key") or ""
                                        ),
                                        model=model_name,
                                        consent=authorized,
                                        audio_duration=state.get("audio_duration"),
                                        cache_dir=utils.storage_dir("cache_videos"),
                                        max_scenes=3,
                                        max_candidates_per_scene=alternatives_per_scene,
                                        target_scene_numbers=list(selected_group),
                                    )
                                except (ValueError, OSError, RuntimeError) as exc:
                                    st.error(
                                        "Busca e reavaliação bloqueadas: "
                                        + type(exc).__name__
                                    )
                                else:
                                    # Refresh task inventory: discovery has
                                    # added files since workspace was loaded.
                                    try:
                                        fresh_workspace = load_review_workspace(
                                            tasks_root, selected_id, media_paths,
                                            audio_duration=state.get(
                                                "audio_duration"
                                            ),
                                            cache_dir=utils.storage_dir(
                                                "cache_videos"
                                            ),
                                        )
                                        persisted = record_semantic_recovery(
                                            tasks_root, selected_id,
                                            first_scene=first_scene,
                                            workspace=fresh_workspace,
                                            proposals=precure, model=model_name,
                                            recovery=fixed,
                                        )
                                    except (ValueError, OSError) as exc:
                                        history[group_id(selected_group)] = fixed
                                        st.session_state[history_key] = history
                                        st.warning(
                                            "Alternativas disponíveis somente "
                                            "na sessão atual: " + type(exc).__name__
                                            + ". Evite reiniciar antes de revisar."
                                        )
                                    else:
                                        st.session_state[history_key] = (
                                            persisted["history"]
                                        )
                                        st.session_state[
                                            f"rick_ai_fix_result_{selected_id}_{first_scene}"
                                        ] = fixed
                                        st.rerun()
                    else:
                        st.success(
                            "Todos os grupos sinalizados foram processados "
                            "no histórico local desta tarefa. Consulte abaixo; "
                            "isso NÃO significa que todas as mídias sejam adequadas."
                        )
                    for group in recovery_groups:
                        recovered = history.get(group_id(group))
                        if not isinstance(recovered, dict):
                            continue
                        st.markdown(
                            "**Resultado das cenas "
                            + ", ".join(map(str, group))
                            + "**"
                        )
                        new_files = recovered.get("discovery") or {}
                        st.caption(
                            f"Busca: {new_files.get('imported_count', 0)} arquivo(s) "
                            f"importado(s); {len(recovered.get('compared', []))} "
                            f"alternativa(s) examinada(s), "
                            f"{recovered.get('api_requests', 0)} invocações do SDK Gemini. "
                            "Nenhuma substituição ou aprovação foi realizada."
                        )
                        replacements = [
                            r for r in recovered.get("compared", [])
                            if isinstance(r, dict)
                            and current.get(r.get("scene_number")) ==
                            r.get("original_file")
                        ]
                        if replacements:
                            st.dataframe([
                                {
                                    "Cena": r["scene_number"],
                                    "Tentativa": r.get("candidate_order", 1),
                                    "Atual": r["original_file"],
                                    "Alternativa": r["file"],
                                    "Relação": r.get("visual_relation"),
                                    "Veredito IA": r["verdict"],
                                    "Evidência": r.get("visible_evidence"),
                                    "Origem": r.get("source_page"),
                                }
                                for r in replacements
                            ], hide_index=True, use_container_width=True)
                        ranking = [
                            row for row in recovered.get("ranking", [])
                            if isinstance(row, dict)
                            and row.get("scene_number") in current
                        ]
                        if ranking:
                            st.markdown(
                                "**Comparação semântica — indicação para revisão humana**"
                            )
                            st.dataframe([
                                {
                                    "Cena": row["scene_number"],
                                    "Alternativas avaliadas": row["candidates_examined"],
                                    "Correspondências diretas (IA)": row["direct_candidates"],
                                    "Indicação da IA": (
                                        row.get("suggested_file")
                                        or "Sem alternativa direta comprovada"
                                    ),
                                    "Estado": row["status"],
                                }
                                for row in ranking
                            ], hide_index=True, use_container_width=True)
                            st.caption(
                                "A sugestão somente aparece quando o Gemini "
                                "observou uma correspondência visual direta. "
                                "Não comprova identidade histórica, licença, "
                                "alinhamento temporal ou autorização de uso. "
                                "O arquivo atual continua selecionado."
                            )
                        if recovered.get("unresolved"):
                            st.warning(
                                f"{len(recovered['unresolved'])} cena(s) "
                                "continuam sem alternativa com metadados "
                                "suficientes; não foram preenchidas artificialmente."
                            )
                        if not replacements and recovered.get("compared"):
                            st.warning(
                                "As propostas principais mudaram. "
                                "Reavalie o lote antes de usar resultados anteriores."
                            )
                        st.info(
                            "As alternativas foram adicionadas apenas ao "
                            "inventário da tarefa. Para mudar uma cena, "
                            "use a seleção e revisão editorial abaixo. "
                            "Conferência de imagem e direitos continua obrigatória."
                        )
                    if history:
                        # Streamlit expanders cannot be nested. The Gemini
                        # assessment is already inside an expander.
                        with st.container(border=True):
                            st.markdown(
                                "**Rick — Montar prévia semântica em MP4 (rascunho)**"
                            )
                            st.warning(
                                "RASCUNHO NÃO HOMOLOGADO: substitui somente as "
                                "cenas com alternativa visual direta plausível "
                                "segundo o Gemini. Todas as demais mantêm o "
                                "clipe original, que pode não corresponder "
                                "à fala. Não publique esta prévia."
                            )
                            st.caption(
                                "Utiliza apenas vídeos já registrados na tarefa, "
                                "o áudio local existente e os intervalos estimados. "
                                "Nenhuma busca externa, chamada Gemini ou nova "
                                "aprovação é feita nesta exportação. "
                                "O vídeo original e a revisão humana ficam intactos."
                            )
                            skip_subtitles = st.checkbox(
                                "Gerar rascunho sem legendas (se necessário)",
                                key=(
                                    f"rick_semantic_draft_nosubs_"
                                    f"{selected_id}_{first_scene}"
                                ),
                            )
                            confirmed_draft = st.checkbox(
                                "Confirmo que esta é apenas uma prévia local "
                                "com cenas ainda não validadas",
                                key=(
                                    f"rick_semantic_draft_confirm_"
                                    f"{selected_id}_{first_scene}"
                                ),
                            )
                            if st.button(
                                "Gerar MP4 de prévia semântica",
                                disabled=not confirmed_draft,
                                key=(
                                    f"rick_semantic_draft_start_"
                                    f"{selected_id}_{first_scene}"
                                ),
                            ):
                                from app.services.rick_semantic_draft import (
                                    export_semantic_draft,
                                )

                                with st.spinner(
                                    "Montando prévia semântica em arquivo separado..."
                                ):
                                    try:
                                        draft = export_semantic_draft(
                                            tasks_root, selected_id,
                                            state_materials=media_paths,
                                            cache_dir=utils.storage_dir(
                                                "cache_videos"
                                            ),
                                            original_proposals=precure,
                                            recovery_history=history,
                                            without_subtitles=skip_subtitles,
                                        )
                                    except (ValueError, OSError, RuntimeError) as exc:
                                        st.error(
                                            "Prévia não gerada: " + str(exc)
                                        )
                                    else:
                                        st.session_state[
                                            f"rick_semantic_draft_last_"
                                            f"{selected_id}_{first_scene}"
                                        ] = draft
                            previous_draft = st.session_state.get(
                                f"rick_semantic_draft_last_"
                                f"{selected_id}_{first_scene}"
                            )
                            if isinstance(previous_draft, dict):
                                import pathlib

                                output_name = previous_draft.get("output")
                                if (
                                    isinstance(output_name, str)
                                    and pathlib.Path(output_name).is_file()
                                ):
                                    st.success(
                                        f"Prévia pronta: "
                                        f"{previous_draft['recommended_count']} "
                                        "cena(s) com indicação visual direta da IA; "
                                        f"{previous_draft['fallback_count']} "
                                        "cena(s) com mídia de metadados ainda não "
                                        "validada. Nenhum vídeo foi publicado."
                                    )
                                    st.video(output_name)
                                    st.code(output_name)
                                    st.caption(
                                        "Relatório de cenas e ressalvas: "
                                        + str(previous_draft.get("report") or "")
                                    )
        if isinstance(precure.get("discovery"), dict):
            discovery = precure["discovery"]
            st.caption(
                f"Última busca: {discovery['imported_count']} arquivos adicionados "
                "com registro de origem. Conteúdo e licença seguem sem homologação."
            )
            st.caption(
                "Consultas ao banco: "
                + str(discovery.get("search_requests", "não registrado"))
                + " • arquivos de fontes diferentes buscados: "
                + str(len(discovery.get("searched_intents", [])))
                + " • materiais importados: "
                + str(discovery.get("imported_count", 0))
                + ". O número de arquivos existentes NÃO equivale ao número "
                "de cenas semanticamente atendidas."
            )
            missed = discovery.get("skipped_candidates")
            if isinstance(missed, dict) and any(missed.values()):
                st.caption(
                    "Candidatos descartados na busca: "
                    f"{missed.get('duplicate', 0)} repetidos, "
                    f"{missed.get('invalid_source', 0)} sem origem/URL elegível, "
                    f"{missed.get('download_failed', 0)} com falha no download/importação."
                )
            recovered = discovery.get("oversized_primaries_recovered", 0)
            smaller = discovery.get("smaller_renditions_used", 0)
            if smaller:
                st.info(
                    f"{smaller} mídia(s) recuperada(s) em resolução menor, "
                    f"incluindo {recovered} originalmente acima de 64 MB. "
                    "O limite de tamanho continua ativo."
                )
            context_photos = discovery.get("context_photos")
            if isinstance(context_photos, dict):
                count = context_photos.get("imported_count", 0)
                tried = context_photos.get("searched_contexts", [])
                st.caption(
                    f"Fallback Wikimedia Commons: {count} foto(s)/documento(s) "
                    f"adicionados de {len(tried)} contextos pesquisados. "
                    "Somente arquivos com metadados CC0/domínio público elegíveis "
                    "foram importados; a imagem e os direitos não foram homologados."
                )
            diagnostics = discovery.get("diagnostics", [])
            if diagnostics:
                st.caption(
                    "Falhas classificadas: "
                    + str(discovery.get("failure_count", len(diagnostics)))
                    + ". A busca continua por outros candidatos quando possível."
                )
                st.dataframe([
                    {
                        "Cena": item["scene"],
                        "Contexto": item["intent"],
                        "Fonte": item["provider"],
                        "Etapa": item["stage"],
                        "Causa": item["code"],
                        "Transitória": "sim" if item["retryable"] else "não",
                    }
                    for item in diagnostics[:20]
                ], hide_index=True, use_container_width=True)
            if discovery.get("issues"):
                st.warning("Avisos da busca: " + "; ".join(discovery["issues"][:5]))

    with st.expander("Rick — Montagem automática com imagens históricas (experimental)", expanded=True):
        st.caption(
            "Uma ação: busca imagens no Wikimedia Commons, filtra metadados "
            "indicando CC0/domínio público, converte para MP4, distribui pelas "
            "cenas e exporta um novo vídeo local com o áudio existente. "
            "Não utiliza API paga nem substitui o vídeo original."
        )
        st.warning(
            "A seleção é baseada no nome dos arquivos e nos metadados de licença. "
            "NÃO verifica visualmente a identidade, autenticidade ou todos os "
            "direitos de uso; grava fontes e ressalvas em relatório. "
            "Não publica o resultado nem registra aprovação humana."
        )
        if not curation["subject_anchor"]:
            st.info(
                "Esta primeira automação é destinada a tarefas sobre uma "
                "pessoa histórica claramente identificada no assunto."
            )
        if st.button(
            "Buscar imagens e montar MP4 automaticamente",
            disabled=not bool(curation["subject_anchor"]),
            key=f"rick_auto_commons_start_{selected_id}",
            type="primary",
        ):
            from app.services.rick_auto_movie import export_auto_commons_video

            with st.spinner(
                "Pesquisando fontes históricas, convertendo imagens e renderizando..."
            ):
                try:
                    automatic = export_auto_commons_video(
                        tasks_root, selected_id,
                        cache_dir=utils.storage_dir("cache_videos"),
                        state_materials=media_paths,
                        subject=str(by_id[selected_id].get("subject") or ""),
                    )
                except (ValueError, OSError, RuntimeError) as exc:
                    st.error(f"Montagem automática bloqueada: {exc}")
                else:
                    st.session_state[f"rick_auto_commons_last_{selected_id}"] = automatic
                    st.success(
                        f"Novo MP4 gerado com {automatic['image_count']} "
                        f"imagens para {automatic['scene_count']} cenas."
                    )
        completed = st.session_state.get(f"rick_auto_commons_last_{selected_id}")
        if isinstance(completed, dict):
            from pathlib import Path

            output_file = completed.get("output")
            if (isinstance(output_file, str)
                    and Path(output_file).is_file()):
                st.video(output_file)
                st.code(output_file)
                st.caption(
                    "Relatório de fontes/licenças informadas: "
                    + str(completed.get("report") or "")
                )

    excluded = excluded_editorial_materials(tasks_root, selected_id)
    if excluded:
        with st.expander(f"Clipes descartados nesta tarefa ({len(excluded)})", expanded=False):
            st.caption(
                "Descarte manual: nenhuma mídia original foi apagada. "
                "Restaurar apenas devolve o clipe à lista; não o aprova."
            )
            restore_name = st.selectbox(
                "Clipe para restaurar", sorted(excluded),
                key=f"rick_editorial_restore_name_{selected_id}",
            )
            if st.button(
                "Restaurar clipe à lista", key=f"rick_editorial_restore_{selected_id}"
            ):
                restore_editorial_material(tasks_root, selected_id, restore_name)
                st.rerun()

    # Export is deliberately separate from the review form: saved human
    # approvals are revalidated immediately before a new MP4 is encoded.
    if (not invalidated and isinstance(saved, dict)
            and saved.get("status") == "ready_human_reviewed"):
        with st.expander("Rick — Exportar vídeo revisado", expanded=True):
            st.success("Todas as cenas foram aprovadas e salvas manualmente.")
            st.caption(
                "Gera um NOVO MP4 com o áudio original e os clipes aprovados. "
                "Não consulta IA, não baixa mídia, não publica e não substitui o MP4 antigo. "
                "Somente as decisões já SALVAS entram na exportação. "
                "Os intervalos entre cenas permanecem estimados."
            )
            without_subs = st.checkbox(
                "Permitir exportar sem legendas (se a tarefa antiga não possui subtitle.srt)",
                key=f"rick_review_export_no_subs_{selected_id}",
            )
            confirmed = st.checkbox(
                "Confirmo a exportação local usando os materiais que aprovei",
                key=f"rick_review_export_confirm_{selected_id}",
            )
            if st.button(
                "Gerar novo MP4 revisado", disabled=not confirmed,
                key=f"rick_review_export_button_{selected_id}", type="primary",
            ):
                from app.services.rick_review_render import export_reviewed_video

                with st.spinner("Montando cenas e áudio no FFmpeg local..."):
                    try:
                        new_video = export_reviewed_video(
                            tasks_root, selected_id,
                            cache_dir=utils.storage_dir("cache_videos"),
                            without_subtitles=without_subs,
                        )
                    except (ValueError, OSError, RuntimeError) as exc:
                        st.error(f"Exportação bloqueada: {exc}")
                    else:
                        st.success("MP4 revisado gerado sem modificar o original.")
                        st.code(new_video["output"])
                        st.caption("Relatório local: " + new_video["report"])

    mode = st.radio(
        "Modo de revisão",
        ["Uma cena por vez", "Todas as cenas", "Só cenas sem sugestão ou com score baixo"],
        horizontal=True, key=f"rick_editorial_mode_{selected_id}",
    )
    scene_key = f"rick_editorial_single_{selected_id}"
    if mode == "Uma cena por vez":
        chosen_scene = st.selectbox(
            "Cena para revisar", list(range(1, len(scenes) + 1)),
            format_func=lambda number: (
                ("✅" if number <= len(old_scenes)
                 and isinstance(old_scenes[number - 1], dict)
                 and old_scenes[number - 1].get("editorial_review") == "approved_by_human"
                 else "⛔" if number <= len(old_scenes)
                 and isinstance(old_scenes[number - 1], dict)
                 and old_scenes[number - 1].get("editorial_review") == "rejected"
                 else "○")
                + f" Cena {number} — "
                + str(scenes[number - 1].get("text") or "")[:75]
            ),
            key=scene_key,
        )
        previous, following = st.columns(2)
        with previous:
            st.button(
                "← Cena anterior", disabled=chosen_scene <= 1,
                on_click=_go_to_scene, args=(scene_key, chosen_scene - 1),
                key=f"rick_review_previous_v4_{selected_id}",
            )
        with following:
            st.button(
                "Próxima cena →", disabled=chosen_scene >= len(scenes),
                on_click=_go_to_scene, args=(scene_key, chosen_scene + 1),
                key=f"rick_review_next_v4_{selected_id}",
            )
        scene_indexes = [chosen_scene]
    elif mode == "Só cenas sem sugestão ou com score baixo":
        scene_indexes = _priority_scene_numbers(proposals, len(scenes))
        st.caption(
            f"{len(scene_indexes)} cenas prioritárias para revisão. "
            "As demais também exigem validação de conteúdo e direitos "
            "antes de qualquer aprovação ou publicação."
        )
    else:
        scene_indexes = list(range(1, len(scenes) + 1))

    choices = sorted(paths)
    for idx in scene_indexes:
        scene = scenes[idx - 1]
        if not isinstance(scene, dict):
            st.error(f"Cena {idx} inválida; não é possível revisar.")
            return
        old = old_scenes[idx - 1] if idx <= len(old_scenes) else {}
        if not isinstance(old, dict):
            old = {}
        current = old.get("editorial_review", "unreviewed")
        label = (
            "Aprovar" if current == "approved_by_human"
            else "Rejeitar" if current == "rejected"
            else "Pendente"
        )
        with st.expander(
            f"Cena {idx} — {scene.get('start_seconds')}–"
            f"{scene.get('end_seconds')} s",
            expanded=(mode == "Uma cena por vez" or idx == 1),
        ):
            st.write(str(scene.get("text") or "Sem texto")[:2000])
            proposed = proposals.get(idx) or {}
            st.caption(
                "Manifesto original — busca: "
                + str(scene.get("search_term") or "(nenhuma)")
                + " • arquivo: "
                + str(scene.get("assigned_material_file") or "não identificado")
            )
            triage = curation["scenes"][idx - 1]
            old_issues = list(triage["issues"])
            if proposed.get("primary"):
                old_issues = [
                    issue for issue in old_issues
                    if issue != "sem candidato correspondente no manifesto"
                ]
            if old_issues:
                st.warning(
                    "Alertas dos metadados originais: " + "; ".join(old_issues)
                )
            elif proposed.get("primary"):
                st.info(
                    "O manifesto antigo não tinha candidato para esta cena; "
                    "a pré-curadoria encontrou uma sugestão para inspeção."
                )
            st.caption(
                "Buscas alternativas (não executadas automaticamente): "
                + " • ".join(triage["suggested_queries"])
            )
            if triage["historical_image_search_url"]:
                st.link_button(
                    "Pesquisar retratos/documentos no Wikimedia Commons",
                    triage["historical_image_search_url"],
                )
                st.caption(
                    "Confira a autenticidade e a licença de cada arquivo no Commons; "
                    "a origem não garante autorização para seu uso."
                )
            selected_default = (
                old.get("assigned_material_file")
                if old.get("editorial_review") == "approved_by_human" else None
            )
            if selected_default not in paths:
                selected_default = None
            groups = classify_review_materials(
                scene, workspace["source_metadata"], choices,
                historical_person=curation["subject_anchor"],
            )
            proposed_primary = proposed.get("primary")
            proposed_names = [
                name for name in [
                    proposed_primary,
                    *[candidate["file"]
                      for candidate in proposed.get("alternatives", [])],
                ]
                if isinstance(name, str) and name in paths
            ]
            ranked = order_review_materials(
                scene, workspace["source_metadata"], groups["suggested"],
            )
            ranked = list(dict.fromkeys([
                *([selected_default] if selected_default in paths else []),
                *proposed_names, *ranked,
            ]))
            groups["other"] = [
                name for name in groups["other"] if name not in ranked
            ]
            review_choices = [None, *ranked]
            if proposed_primary in paths:
                st.caption(
                    f"Pré-curadoria sugere: {proposed_primary} "
                    f"(pontuação de metadados: {proposed['metadata_score']}). "
                    "Isso NÃO é grau de certeza nem validação visual."
                )
                st.caption(
                    "Motivos (metadados): "
                    + ", ".join(proposed.get("reasons", [])[:4])
                )
                alternatives = proposed.get("alternatives", [])
                if alternatives:
                    st.caption(
                        "Alternativas encontradas: "
                        + " • ".join(row["file"] for row in alternatives[:2])
                    )
            if not ranked:
                st.info("Nenhum material correspondente foi identificado para esta cena.")
            else:
                st.caption(
                    "Materiais ordenados pela pré-curadoria e pelos metadados "
                    "da tarefa. O conteúdo visual não foi verificado."
                )
            with st.expander("Adicionar vídeo ou fotografia adequada (local)", expanded=False):
                st.caption(
                    "Envie MP4 (até 64 MB) ou JPG/PNG (até 12 MB). Fotos são "
                    "transformadas em vídeo vertical de 4 segundos usando FFmpeg "
                    "local, sem IA ou download. A importação não aprova o material."
                )
                uploaded = st.file_uploader(
                    "Arquivo de vídeo ou foto", type=["mp4", "jpg", "jpeg", "png"],
                    key=f"rick_editorial_upload_v5_{selected_id}_{idx}",
                )
                origin = st.text_input(
                    "Origem e condições de uso informadas por você",
                    key=f"rick_editorial_upload_origin_v5_{selected_id}_{idx}",
                    max_chars=350,
                )
                if st.button(
                    "Adicionar à biblioteca desta tarefa",
                    disabled=uploaded is None or not origin.strip(),
                    key=f"rick_editorial_import_v5_{selected_id}_{idx}",
                ):
                    try:
                        import_editorial_material(
                            tasks_root, selected_id, uploaded.name, uploaded.getvalue(),
                            scene_number=idx, source_note=origin,
                        )
                    except (ValueError, OSError) as exc:
                        st.error(f"Importação bloqueada: {exc}")
                    else:
                        st.session_state[notice_key] = (
                            "Mídia importada, mas NÃO aprovada. "
                            "Escolha-a no seletor e confira seu conteúdo e direitos."
                        )
                        st.rerun()

            def describe_option(name: str | None) -> str:
                if name is None:
                    return "— Selecione um clipe —"
                info = workspace["source_metadata"].get(name, {})
                term = str(info.get("search_term") or "sem busca registrada")[:55]
                return f"{term} · {name}"

            # The selector and playback MUST be outside st.form. Streamlit
            # otherwise defers both until Submit, causing the user to see
            # "no clip selected" even after selecting a valid file.
            suggested_default = (
                selected_default if selected_default in review_choices
                else proposed_primary if proposed_primary in review_choices
                else None
            )
            _hydrate_precuration_choice(
                selected_id, idx, proposed_primary, review_choices,
                saved_approved=selected_default,
            )
            suggested_choice = st.selectbox(
                "1. Materiais sugeridos para esta cena (metadados)",
                review_choices,
                index=review_choices.index(suggested_default),
                format_func=describe_option,
                on_change=_select_scene_material,
                args=(selected_id, idx, "suggested"),
                key=f"rick_editorial_material_v4_{selected_id}_{idx}",
            )
            other_choice = None
            with st.expander(
                f"Outros materiais disponíveis na tarefa ({len(groups['other'])})",
                expanded=False,
            ):
                st.caption(
                    "Biblioteca opcional para inspeção humana. Estes arquivos NÃO "
                    "possuem vínculo exato de busca com a cena e não são "
                    "recomendações de adequação."
                )
                if groups["other"]:
                    other_options = [None, *groups["other"]]
                    other_default = (
                        selected_default if selected_default in other_options else None
                    )
                    other_choice = st.selectbox(
                        "Selecionar outro arquivo para inspeção",
                        other_options,
                        index=other_options.index(other_default),
                        format_func=describe_option,
                        on_change=_select_scene_material,
                        args=(selected_id, idx, "other"),
                        key=f"rick_editorial_other_v1_{selected_id}_{idx}",
                    )
                    if other_choice is not None:
                        reason = groups["reasons"][other_choice]
                        if reason == "historical_name_metadata_only":
                            st.warning(
                                "O nome histórico aparece somente nos metadados "
                                "da busca original. Isso NÃO comprova que a pessoa "
                                "esteja presente no vídeo."
                            )
                        else:
                            st.caption(
                                "Sem correspondência demonstrada por metadados "
                                "com o conteúdo desta cena."
                            )
                else:
                    st.caption("Nenhum outro arquivo está disponível nesta tarefa.")
            chosen = other_choice if other_choice is not None else suggested_choice
            if chosen is not None:
                source_path = paths[chosen]
                provenance = workspace["source_metadata"].get(chosen, {})
                st.caption(
                    "Fonte registrada: " + str(provenance.get("provider") or "não informada")
                    + " • Página de origem / nota registrada: "
                    + str(provenance.get("source_page") or "não informada")
                )
                st.caption(
                    "Condições de uso e conteúdo visual NÃO verificados automaticamente. "
                    "A confirmação depende da revisão humana e da licença aplicável."
                )
                if st.button(
                    "Descartar este clipe de toda a tarefa",
                    key=f"rick_editorial_exclude_v5_{selected_id}_{idx}",
                    help="Remove somente das opções desta tarefa; não apaga o arquivo.",
                ):
                    try:
                        exclude_editorial_material(tasks_root, selected_id, chosen)
                    except (ValueError, OSError) as exc:
                        st.error(f"Não foi possível descartar o clipe: {exc}")
                    else:
                        st.session_state[notice_key] = (
                            "Clipe descartado desta tarefa. "
                            "O arquivo original foi preservado."
                        )
                        st.rerun()
                if st.checkbox(
                    "Mostrar prévia do vídeo selecionado",
                    value=mode == "Uma cena por vez",
                    key=f"rick_editorial_show_video_v4_{selected_id}_{idx}",
                ):
                    try:
                        st.video(source_path)
                    except (OSError, ValueError):
                        st.warning("Não foi possível reproduzir esse vídeo no navegador.")

            else:
                st.info(
                    "Escolha um vídeo acima para assistir. Nenhuma sugestão "
                    "automática é considerada uma aprovação humana."
                )

            st.caption(
                "2. Assista, confira a correspondência com a fala e os direitos "
                "de uso; então registre sua decisão abaixo."
            )
            with st.form(
                key=f"rick_editorial_scene_form_v4_{selected_id}_{idx}",
                clear_on_submit=False,
            ):
                review = st.radio(
                    "Decisão editorial",
                    ["Pendente", "Aprovar", "Rejeitar"],
                    index=["Pendente", "Aprovar", "Rejeitar"].index(label),
                    horizontal=True,
                    key=f"rick_editorial_decision_{selected_id}_{idx}",
                )
                note = st.text_input(
                    "Origem/licença conferida (registro humano)",
                    value=str(old.get("editorial_source_note") or ""),
                    key=f"rick_editorial_source_{selected_id}_{idx}",
                    max_chars=800,
                )
                content_checked = st.checkbox(
                    "Eu assisti e conferi se o clipe corresponde a este trecho",
                    value=old.get("editorial_content_checked") is True,
                    key=f"rick_editorial_content_{selected_id}_{idx}",
                )
                rights_checked = st.checkbox(
                    "Eu conferi as condições de uso deste material",
                    value=old.get("editorial_rights_checked") is True,
                    key=f"rick_editorial_rights_{selected_id}_{idx}",
                )
                submitted = st.form_submit_button("Salvar esta cena", type="primary")

            if not submitted:
                continue
            if review == "Aprovar" and (
                chosen is None or not note.strip()
                or not content_checked or not rights_checked
            ):
                st.error(
                    "Para aprovar: selecione um vídeo, assista e confira seu "
                    "conteúdo e direitos, registre a origem/licença e marque "
                    "as duas verificações. Nada foi aprovado."
                )
                continue

            # A single-scene save retains other human decisions, but
            # revalidates all of them before replacing the review artifact.
            decisions = retained_human_decisions(old_scenes, exclude_scene=idx)
            if review != "Pendente":
                decisions.append({
                    "scene_number": idx,
                    "decision": "approve" if review == "Aprovar" else "reject",
                    "selected_file": chosen,
                    "source_note": note,
                    "content_checked": content_checked,
                    "rights_checked": rights_checked,
                })
            try:
                report = save_editorial_workspace_review(
                    tasks_root, selected_id, workspace["preview_sha256"],
                    list(paths.values()), decisions,
                    audio_duration=state.get("audio_duration"),
                    cache_dir=utils.storage_dir("cache_videos"),
                )
            except (ValueError, OSError) as exc:
                st.error(f"Falha ao salvar a cena: {exc}")
                continue

            st.session_state[notice_key] = (
                f"Cena {idx} salva. {report['human_approved_count']}/"
                f"{report['scene_count']} cenas aprovadas. "
                + ("Todas prontas para exportar!" if report["status"] == "ready_human_reviewed"
                   else "Continue conferindo as demais cenas.")
            )
            st.rerun()
