from __future__ import annotations


def build_summary_text(overall_status: str, facts: list[str], context_notes: list[str]) -> str:
    if overall_status == "correct":
        lead = "Sesion cumplida correctamente."
    elif overall_status == "partial":
        lead = "Sesion cumplida de forma parcial."
    elif overall_status == "not_completed":
        lead = "Sesion por debajo de lo esperado."
    else:
        lead = "Sesion con analisis parcial o en revision."

    prioritized_facts = sorted(facts, key=lambda fact: ("intensidad" not in fact.lower(), facts.index(fact)))
    details = ", ".join(prioritized_facts[:3]) if prioritized_facts else "No hubo suficientes metricas globales para un resumen fuerte."
    context = f" Contexto: {'; '.join(context_notes[:2])}." if context_notes else ""
    return f"{lead} {details.capitalize()}.{context}"


def build_recommendation_text(overall_status: str, context_notes: list[str], has_step_failures: bool) -> str:
    if overall_status == "correct":
        recommendation = "Mantener la estructura del plan."
    elif overall_status == "partial":
        recommendation = "Mantener la estructura, pero revisar los bloques con mayor desvio."
    elif overall_status == "not_completed":
        recommendation = "Revisar la carga real y el control de intensidad antes de repetir una sesion similar."
    else:
        recommendation = "Revisar manualmente la sesion porque faltan datos para una conclusion mas firme."

    if has_step_failures:
        recommendation += " Poner foco en los bloques principales."
    if any("intensidad" in note.lower() for note in context_notes):
        recommendation += " Revisar tambien la lectura de intensidad."
    if context_notes:
        recommendation += f" Tener en cuenta el contexto del dia: {context_notes[0].lower()}"
    return recommendation
