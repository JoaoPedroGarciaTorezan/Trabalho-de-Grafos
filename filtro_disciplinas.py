""""
======================
Passo 3 do pipeline de recomendação de matrícula.

A partir do DAG do currículo e do histórico processado do aluno, determina
quais disciplinas estão disponíveis para matrícula no próximo semestre.

Uma disciplina é considerada DISPONÍVEL se satisfaz TODAS as condições:
    1. Está na oferta do semestre corrente (SEMESTRAL sempre; ANUAL só em anos
       ímpares, i.e., semestres 1 e 7, ou pares, 2 e 8 — veja `oferta_ativa`).
    2. O aluno ainda não foi aprovado nela (código não está em `aprovadas`
       nem possui um equivalente já aprovado).
    3. Todos os pré-requisitos diretos estão satisfeitos: cada pré-req foi
       aprovado diretamente OU um de seus equivalentes foi aprovado.

Uso como módulo:
    from filtrar_disciplinas import filtrar_disponiveis
    disponiveis = filtrar_disponiveis(dag, aluno, semestre_atual="2025.1")

Uso como script:
    python filtrar_disciplinas.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

# Imports do próprio pipeline
from dag_cco import DAG, Disciplina, construir_dag
from read_historico import HistoricoAluno, processar_historico


# ---------------------------------------------------------------------------
# Tipo auxiliar
# ---------------------------------------------------------------------------

@dataclass
class DisciplinaDisponivel:
    """Disciplina que o aluno pode cursar no semestre informado."""

    codigo:  str
    nome:    str
    tipo:    str
    area:    str
    periodo: int      # período sugerido pela grade
    ch:      int
    prereqs_satisfeitos: list[str] = field(default_factory=list)
    # Como cada pré-req foi satisfeito: codigo_prereq → codigo_aprovado
    satisfacao_prereqs:  dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"DisciplinaDisponivel({self.codigo!r}, {self.nome!r}, "
            f"periodo={self.periodo}, ch={self.ch})"
        )


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def _numero_semestre(semestre_str: str) -> int:
    """
    '2025.1' → 1   |   '2025.2' → 2
    Lança ValueError se o formato for inválido.
    """
    try:
        return int(semestre_str.split(".")[1])
    except (IndexError, ValueError) as exc:
        raise ValueError(
            f"Formato de semestre inválido: {semestre_str!r}. "
            "Esperado: 'AAAA.S' (ex.: '2025.1')."
        ) from exc


def oferta_ativa(disc: Disciplina, semestre_atual: str) -> bool:
    """
    Retorna True se a disciplina está sendo ofertada no semestre informado.

    Regras:
        SEMESTRAL → sempre ofertada (todo semestre).
        ANUAL     → ofertada apenas em semestres ímpares (1º sem. do ano).
        Qualquer outro valor de `oferta` → conservadoramente, retorna False
        com aviso.
    """
    oferta = disc.oferta.upper().strip()

    if oferta == "SEMESTRAL":
        return True

    if oferta == "ANUAL":
        num = _numero_semestre(semestre_atual)
        # Ofertada apenas no 1º semestre de cada ano (semestre .1)
        return num == 1

    # Caso desconhecido — por segurança, não oferta
    print(
        f"[AVISO] Tipo de oferta desconhecido para {disc.codigo}: "
        f"'{disc.oferta}'. Disciplina excluída da filtragem."
    )
    return False


def _ja_aprovado(
    codigo: str,
    aprovadas: set[str],
    equivalentes: list[str],
) -> bool:
    """
    Retorna True se `codigo` (ou qualquer de seus equivalentes) já foi aprovado.
    """
    if codigo in aprovadas:
        return True
    return any(eq in aprovadas for eq in equivalentes)


def _prereq_satisfeito(
    codigo_prereq: str,
    dag: DAG,
    aprovadas: set[str],
) -> tuple[bool, str]:
    """
    Verifica se um pré-requisito específico está satisfeito.

    Um pré-req `P` está satisfeito se:
        • P ∈ aprovadas, OU
        • algum equivalente de P ∈ aprovadas.

    Retorna (satisfeito: bool, codigo_que_satisfez: str).
    O segundo elemento é o código que efetivamente satisfez o pré-req
    (pode ser o próprio P ou um equivalente).
    """
    if codigo_prereq in aprovadas:
        return True, codigo_prereq

    # Verifica equivalentes do pré-requisito (se ele existe no DAG)
    disc_prereq = dag.vertices.get(codigo_prereq)
    if disc_prereq:
        for eq in disc_prereq.equivalentes:
            if eq in aprovadas:
                return True, eq

    return False, ""


def _todos_prereqs_satisfeitos(
    disc: Disciplina,
    dag: DAG,
    aprovadas: set[str],
) -> tuple[bool, dict[str, str]]:
    """
    Verifica se TODOS os pré-requisitos de `disc` estão satisfeitos.

    Retorna:
        (todos_ok: bool, mapa: dict[codigo_prereq → codigo_que_satisfez])

    Se `todos_ok` for False, `mapa` contém apenas os pré-reqs já satisfeitos
    até o ponto de falha (útil para debug).
    """
    mapa: dict[str, str] = {}

    for prereq in disc.prereqs:
        ok, satisfeito_por = _prereq_satisfeito(prereq, dag, aprovadas)
        if not ok:
            return False, mapa
        mapa[prereq] = satisfeito_por

    return True, mapa


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def filtrar_disponiveis(
    dag: DAG,
    aluno: HistoricoAluno,
    semestre_atual: str,
) -> list[DisciplinaDisponivel]:
    """
    Filtra as disciplinas do DAG e retorna aquelas disponíveis para matrícula.

    Parâmetros
    ----------
    dag            : DAG construído pelo módulo dag_cco.
    aluno          : HistoricoAluno processado pelo módulo read_historico.
    semestre_atual : String no formato 'AAAA.S' (ex.: '2025.1').

    Retorno
    -------
    Lista de DisciplinaDisponivel ordenada por (periodo, codigo).
    """
    aprovadas = aluno.aprovadas
    disponiveis: list[DisciplinaDisponivel] = []

    for codigo, disc in dag.vertices.items():

        # ── Critério 1: oferta ativa no semestre corrente ──────────────────
        if not oferta_ativa(disc, semestre_atual):
            continue

        # ── Critério 2: aluno ainda não aprovado (nem por equivalência) ───
        if _ja_aprovado(codigo, aprovadas, disc.equivalentes):
            continue

        # ── Critério 3: todos os pré-requisitos satisfeitos ───────────────
        todos_ok, mapa_satisfacao = _todos_prereqs_satisfeitos(
            disc, dag, aprovadas
        )
        if not todos_ok:
            continue

        # ── Disciplina disponível ─────────────────────────────────────────
        disponiveis.append(
            DisciplinaDisponivel(
                codigo               = codigo,
                nome                 = disc.nome,
                tipo                 = disc.tipo,
                area                 = disc.area,
                periodo              = disc.periodo,
                ch                   = disc.ch,
                prereqs_satisfeitos  = list(mapa_satisfacao.keys()),
                satisfacao_prereqs   = mapa_satisfacao,
            )
        )

    # Ordena por período sugerido e, dentro do mesmo período, por código
    disponiveis.sort(key=lambda d: (d.periodo, d.codigo))
    return disponiveis


# ---------------------------------------------------------------------------
# Ponto de entrada — demonstração
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    BASE = os.path.dirname(__file__)

    # ── Carrega dados ────────────────────────────────────────────────────────
    df_curr = pd.read_csv(os.path.join(BASE, "curriculo_cco.csv"))
    df_hist = pd.read_csv(os.path.join(BASE, "historico_CCO-4.csv"))

    # ── Constrói DAG e processa histórico ────────────────────────────────────
    dag   = construir_dag(df_curr)
    aluno = processar_historico(df_hist, df_curr)

    # ── Semestre a consultar ─────────────────────────────────────────────────
    SEMESTRE = "2025.1"

    print("=" * 65)
    print(f"DISCIPLINAS DISPONÍVEIS — {SEMESTRE}")
    print("=" * 65)

    disponiveis = filtrar_disponiveis(dag, aluno, SEMESTRE)

    if not disponiveis:
        print("Nenhuma disciplina disponível para matrícula.")
    else:
        area_atual = None
        for d in disponiveis:
            if d.area != area_atual:
                area_atual = d.area
                print(f"\n── {d.area} " + "─" * max(0, 55 - len(d.area)))

            prereqs_str = ""
            if d.satisfacao_prereqs:
                partes = []
                for req, satisfeito_por in d.satisfacao_prereqs.items():
                    if satisfeito_por == req:
                        partes.append(req)
                    else:
                        partes.append(f"{req}→{satisfeito_por}")
                prereqs_str = f"  [pré-reqs: {', '.join(partes)}]"

            print(
                f"  {d.codigo:<10}  P{d.periodo}  {d.ch:>3}h  "
                f"{d.tipo:<12}  {d.nome}{prereqs_str}"
            )

    print(f"\nTotal: {len(disponiveis)} disciplina(s) disponível(is).")
    print(f"CH potencial: {sum(d.ch for d in disponiveis)} h")