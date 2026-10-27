"""Optional Streamlit human-review panel for previously generated Rick scenes.

Never starts generation, download, publication or paid API calls.
No user-entered paths are opened; clips come from recorded task material paths.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import streamlit as st

from app.utils import utils

from app.services.rick_editorial_workspace import (
    load_review_workspace,
    save_editorial_workspace_review,
)


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
            "Nenhum material de vídeo local está disponível no histórico desta tarefa. "
            "A revisão de mídia exige arquivos existentes registrados pela tarefa; "
            "não será usado um caminho digitado manualmente."
        )
        return

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
    st.caption(
        f"{len(scenes)} cenas • {len(paths)} vídeos disponíveis • "
        "Tempos são estimados e a presença de um vídeo não comprova o assunto."
    )
    choices = sorted(paths)
    decisions: list[dict[str, Any]] = []
    with st.form(key=f"rick_editorial_form_{selected_id}", clear_on_submit=False):
        for idx, scene in enumerate(scenes, 1):
            if not isinstance(scene, dict):
                st.error(f"Cena {idx} inválida; não será possível aprovar.")
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
                f"{scene.get('end_seconds')} s", expanded=(idx == 1),
            ):
                st.write(str(scene.get("text") or "Sem texto")[:2000])
                st.caption(
                    "Busca sugerida: " + str(scene.get("search_term") or "(nenhuma)")
                    + " • Candidato automático: "
                    + str(scene.get("assigned_material_file") or "não encontrado")
                )
                selected_default = old.get("assigned_material_file")
                if selected_default not in paths:
                    selected_default = scene.get("assigned_material_file")
                index = choices.index(selected_default) if selected_default in paths else 0
                chosen = st.selectbox(
                    "Arquivo de vídeo (existente)",
                    choices, index=index,
                    key=f"rick_editorial_material_{selected_id}_{idx}",
                )
                source_path = paths[chosen]
                provenance = workspace["source_metadata"].get(chosen, {})
                st.caption(
                    "Fonte registrada: " + str(provenance.get("provider") or "não informada")
                    + " • Página de origem: "
                    + str(provenance.get("source_page") or "não informada")
                )
                if st.checkbox(
                    "Pré-visualizar clipe",
                    value=(idx == 1),
                    key=f"rick_editorial_show_video_{selected_id}_{idx}",
                ):
                    try:
                        st.video(source_path)
                    except (OSError, ValueError):
                        st.warning("Não foi possível reproduzir esse clipe no navegador.")
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
                if review != "Pendente":
                    decisions.append({
                        "scene_number": idx,
                        "decision": "approve" if review == "Aprovar" else "reject",
                        "selected_file": chosen,
                        "source_note": note,
                        "content_checked": content_checked,
                        "rights_checked": rights_checked,
                    })
        submitted = st.form_submit_button(
            "Salvar revisão editorial local", type="primary"
        )
    if not submitted:
        return
    try:
        report = save_editorial_workspace_review(
            tasks_root, selected_id, workspace["preview_sha256"],
            list(paths.values()), decisions,
            audio_duration=state.get("audio_duration"),
            cache_dir=utils.storage_dir("cache_videos"),
        )
    except (ValueError, OSError) as exc:
        st.error(f"Falha ao salvar revisão: {exc}")
        return
    if report["status"] == "ready_human_reviewed":
        st.success(
            f"{report['human_approved_count']} cenas aprovadas; "
            "relatório salvo. Nenhum vídeo foi renderizado."
        )
    else:
        st.warning(
            f"Revisão salva como rascunho: "
            f"{len(report['blockers'])} pendências/bloqueios. "
            "Nenhuma montagem foi autorizada."
        )
    st.caption(
        "Relatório: " + str(Path(workspace["task_dir"]) / "rick_editorial_review.json")
    )
