from __future__ import annotations


def build_summary_text(overall_status: str, facts: list[str], context_notes: list[str]) -> str:
    normalized_facts = [fact.strip() for fact in facts if fact and fact.strip()]
    if overall_status == "correct":
        lead = "La sesion se cumplio correctamente."
    elif overall_status == "partial":
        lead = "La sesion quedo parcial."
    elif overall_status == "not_completed":
        lead = "La sesion quedo por debajo de lo esperado."
    else:
        lead = "La sesion quedo en revision por datos insuficientes o ambiguos."

    prioritized_facts = sorted(
        normalized_facts,
        key=lambda fact: ("duracion" not in fact.lower(), "distancia" not in fact.lower(), "intensidad" not in fact.lower(), normalized_facts.index(fact)),
    )
    details = ", ".join(prioritized_facts[:3]) if prioritized_facts else "No hubo suficientes metricas para explicar el score."
    context = f" Contexto: {'; '.join(context_notes[:2])}." if context_notes else ""
    return f"{lead} Factores principales: {details}.{context}"


def build_recommendation_text(overall_status: str, context_notes: list[str], has_step_failures: bool) -> str:
    if overall_status == "correct":
        recommendation = "No hace falta ajustar el plan por esta sesion; mantener la estructura actual."
    elif overall_status == "partial":
        recommendation = "No hace falta cambiar el plan por una sola sesion parcial, pero conviene revisar los componentes que quedaron mas lejos de lo esperado."
    elif overall_status == "not_completed":
        recommendation = "Conviene revisar la carga real y el control de intensidad antes de repetir una sesion similar."
    else:
        recommendation = "Revisar el match, las zonas y los datos disponibles para mejorar la calidad del analisis."

    if has_step_failures:
        recommendation += " Poner foco en los bloques principales y en los pasos con score bajo."
    if any("intensidad" in note.lower() for note in context_notes):
        recommendation += " Revisar tambien la lectura de intensidad."
    if context_notes:
        recommendation += f" Tener en cuenta el contexto del dia: {context_notes[0].lower()}."
    return recommendation
