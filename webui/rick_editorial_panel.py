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
    if (
        not isinstance(proposal, str) or proposal not in choices
        or saved_approved is not None
        or state.get(manual_key) is True
        or state.get(other_key) is not None
    ):
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
        st.success(st.session_state.pop(notice_key))
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
                    st.session_state[notice_key] = (
                        f"Pré-curadoria pronta: {report['proposed_count']}/"
                        f"{report['scene_count']} propostas; "
                        f"{report['unresolved_count']} cenas ainda pendentes. "
                        "Nada foi aprovado automaticamente."
                    )
                    st.rerun()
        st.dataframe([
            {
                "Cena": row["scene_number"],
                "Trecho": row["text"][:75],
                "Intenção": row["intent"]["kind"],
                "Consulta específica": row["intent"]["query"][:90],
                "Proposta": row["primary"] or "SEM CANDIDATO",
                "Score metadados": row["metadata_score"],
                "Estado": row["status"],
            }
            for row in precure["scenes"]
        ], hide_index=True, use_container_width=True)
        if isinstance(precure.get("discovery"), dict):
            discovery = precure["discovery"]
            st.caption(
                f"Última busca: {discovery['imported_count']} arquivos adicionados "
                "com registro de origem. Conteúdo e licença seguem sem homologação."
            )
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
