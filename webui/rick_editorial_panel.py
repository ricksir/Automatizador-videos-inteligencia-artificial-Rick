"""Optional Streamlit human-review panel for previously generated Rick scenes.

Never starts generation, download, publication or paid API calls.
No user-entered paths are opened; clips come from recorded task material paths.
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
)


def _clear_scene_evidence(task_id: str, scene_number: int) -> None:
    """Changing a clip requires fresh human verification before approval."""
    st.session_state[f"rick_editorial_decision_{task_id}_{scene_number}"] = "Pendente"
    st.session_state[f"rick_editorial_source_{task_id}_{scene_number}"] = ""
    st.session_state[f"rick_editorial_content_{task_id}_{scene_number}"] = False
    st.session_state[f"rick_editorial_rights_{task_id}_{scene_number}"] = False


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
        "Modo de revisão", ["Uma cena por vez", "Todas as cenas"],
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
            st.caption(
                "Busca sugerida: " + str(scene.get("search_term") or "(nenhuma)")
                + " • Candidato automático: "
                + str(scene.get("assigned_material_file") or "não encontrado")
            )
            triage = curation["scenes"][idx - 1]
            if triage["issues"]:
                st.warning("Alertas para conferência: " + "; ".join(triage["issues"]))
            st.caption(
                "Buscas alternativas (não executadas automaticamente): "
                + " • ".join(triage["suggested_queries"])
            )
            selected_default = (
                old.get("assigned_material_file")
                if old.get("editorial_review") == "approved_by_human" else None
            )
            if selected_default not in paths:
                selected_default = None
            ranked = order_review_materials(
                scene, workspace["source_metadata"], choices,
            )
            review_choices = [None, *ranked]
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
                        added = import_editorial_material(
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
            chosen = st.selectbox(
                "1. Escolha o vídeo para assistir",
                review_choices,
                index=review_choices.index(selected_default),
                format_func=describe_option,
                on_change=_clear_scene_evidence,
                args=(selected_id, idx),
                key=f"rick_editorial_material_v4_{selected_id}_{idx}",
            )
            if chosen is not None:
                source_path = paths[chosen]
                provenance = workspace["source_metadata"].get(chosen, {})
                st.caption(
                    "Fonte registrada: " + str(provenance.get("provider") or "não informada")
                    + " • Página de origem: "
                    + str(provenance.get("source_page") or "não informada")
                )
                if st.checkbox(
                    "Mostrar prévia do vídeo selecionado",
                    value=mode == "Uma cena por vez",
                    key=f"rick_editorial_show_video_v4_{selected_id}_{idx}",
                ):
                    try:
                        st.video(source_path)
                    except (OSError, ValueError):
                        st.warning("Não foi possível reproduzir esse vídeo no navegador.")
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
