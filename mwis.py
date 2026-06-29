"""
mwis.py
=======
Etapa 5B do pipeline de recomendação de matrícula — Variante B.

Constrói o grafo de conflitos de horário entre as disciplinas candidatas
e resolve o Problema do Conjunto Independente de Peso Máximo (MWIS)
com restrição de capacidade de carga horária.

Formulação:
    Maximizar:   Σ score(d) × x_d
    Sujeito a:   Σ CH(d)    × x_d ≤ capacidade_mochila
                 x_a + x_b  ≤ 1     ∀ aresta (a,b) ∈ G_conflitos
                 x_d ∈ {0, 1}

Estratégia de solução:
    |candidatas| ≤ 20  →  enumeração exata de subconjuntos independentes (2^n)
    |candidatas| >  20  →  heurística gulosa ordenada por score / CH

Formato da coluna HORARIOS no CSV:
    Slots separados por '|', cada slot no formato 'Dia HH:MM'
    Exemplo: 'Terça 10:10 | Quarta 10:10 | Terça 19:00'

Dois disciplinas têm CONFLITO se compartilham ao menos um slot (Dia + Horário).

Uso como módulo:
    from mwis import resolver_mwis, ResultadoMWIS
    resultado = resolver_mwis(candidatas, scores, capacidade, df_curriculo)

Uso como script:
    python mwis.py
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from itertools import combinations

import pandas as pd

from dag_cco import construir_dag
from filtro_disciplinas import DisciplinaDisponivel, filtrar_disponiveis
from read_historico import processar_historico
from score import calcular_scores


# ---------------------------------------------------------------------------
# Estrutura de saída
# ---------------------------------------------------------------------------

@dataclass
class ResultadoMWIS:
    """Resultado da seleção pelo MWIS com restrição de capacidade."""

    selecionadas:       list[DisciplinaDisponivel]
    scores:             dict[str, float]    # codigo → score das selecionadas
    horarios:           dict[str, list[str]]# codigo → lista de slots
    ch_total:           int
    capacidade:         int
    score_total:        float
    ch_disponivel:      int
    n_conflitos_grafo:  int                 # arestas no grafo de conflitos
    estrategia:         str                 # 'exata' ou 'gulosa'

    def __repr__(self) -> str:
        codigos = [d.codigo for d in self.selecionadas]
        return (
            f"ResultadoMWIS("
            f"selecionadas={codigos}, "
            f"ch={self.ch_total}/{self.capacidade}h, "
            f"score_total={self.score_total:.4f}, "
            f"estrategia={self.estrategia!r})"
        )


# ---------------------------------------------------------------------------
# Parsing de horários
# ---------------------------------------------------------------------------

# Dias válidos aceitos no CSV (variações de escrita)
_DIAS_VALIDOS = {
    "segunda", "terca", "terça", "quarta",
    "quinta", "sexta", "sabado", "sábado",
}

def _normalizar_slot(slot: str) -> str:
    """
    Normaliza um slot de horário para comparação.

    'Terça 10:10 '  →  'terca_10:10'
    'Quarta 19:00'  →  'quarta_19:00'

    Remove acentos do dia e converte para minúsculas para comparação robusta.
    """
    slot = slot.strip().lower()
    slot = (
        slot
        .replace("ç", "c")
        .replace("á", "a")
        .replace("é", "e")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("ô", "o")
    )
    # Garante formato 'dia_HH:MM' (substitui espaço entre dia e hora por _)
    partes = slot.split()
    if len(partes) == 2:
        return f"{partes[0]}_{partes[1]}"
    return slot   # mantém como está se formato inesperado


def _parse_horarios(valor) -> list[str]:
    """
    Converte o campo HORARIOS do CSV em lista de slots normalizados.

    'Terça 10:10 | Quarta 10:10'  →  ['terca_10:10', 'quarta_10:10']
    NaN / vazio                   →  []
    """
    if pd.isna(valor) or str(valor).strip() == "":
        return []
    return [
        _normalizar_slot(s)
        for s in str(valor).split("|")
        if s.strip()
    ]


def _extrair_horarios(
    df_curriculo: pd.DataFrame,
    candidatas: list[DisciplinaDisponivel],
) -> dict[str, list[str]]:
    """
    Extrai os slots normalizados de cada disciplina candidata a partir do CSV.

    Retorna dict { codigo → [slot1, slot2, ...] }.
    Disciplinas sem coluna HORARIOS ou com campo vazio recebem lista vazia.
    """
    if "HORARIOS" not in df_curriculo.columns:
        return {d.codigo: [] for d in candidatas}

    mapa_horarios = (
        df_curriculo
        .set_index("CODIGO")["HORARIOS"]
        .to_dict()
    )

    return {
        d.codigo: _parse_horarios(mapa_horarios.get(d.codigo))
        for d in candidatas
    }


# ---------------------------------------------------------------------------
# Grafo de conflitos
# ---------------------------------------------------------------------------

def _construir_grafo_conflitos(
    candidatas: list[DisciplinaDisponivel],
    horarios: dict[str, list[str]],
) -> dict[str, set[str]]:
    """
    Constrói o grafo de conflitos G_c = (V, E).

    V = códigos das disciplinas candidatas
    E = aresta (A, B) se A e B compartilham ao menos um slot de horário

    Retorna dict { codigo → set(codigos_em_conflito) } (lista de adjacência).
    """
    codigos = [d.codigo for d in candidatas]
    grafo: dict[str, set[str]] = {c: set() for c in codigos}

    for a, b in combinations(codigos, 2):
        slots_a = set(horarios.get(a, []))
        slots_b = set(horarios.get(b, []))
        if slots_a & slots_b:   # interseção não vazia → conflito
            grafo[a].add(b)
            grafo[b].add(a)

    return grafo


def _contar_arestas(grafo: dict[str, set[str]]) -> int:
    """Conta arestas únicas no grafo de conflitos (não dirigido)."""
    return sum(len(v) for v in grafo.values()) // 2


# ---------------------------------------------------------------------------
# Verificação de conjunto independente
# ---------------------------------------------------------------------------

def _eh_independente(
    subconjunto: list[str],
    grafo: dict[str, set[str]],
) -> bool:
    """
    Retorna True se nenhum par em `subconjunto` tem aresta no grafo.
    """
    for i, a in enumerate(subconjunto):
        for b in subconjunto[i + 1:]:
            if b in grafo.get(a, set()):
                return False
    return True


def _respeita_capacidade(
    subconjunto: list[str],
    mapa_ch: dict[str, int],
    capacidade: int,
) -> bool:
    return sum(mapa_ch.get(c, 0) for c in subconjunto) <= capacidade


# ---------------------------------------------------------------------------
# Estratégia exata — enumeração (|V| ≤ 20)
# ---------------------------------------------------------------------------

def _mwis_exato(
    codigos: list[str],
    scores: dict[str, float],
    mapa_ch: dict[str, int],
    grafo: dict[str, set[str]],
    capacidade: int,
) -> list[str]:
    """
    Encontra o MWIS ótimo por enumeração de todos os subconjuntos.
    Viável para |V| ≤ 20 (no máximo 2^20 ≈ 1M iterações).
    """
    melhor_score = -1.0
    melhor_subset: list[str] = []

    # Itera tamanhos de 1 até n para encontrar o subconjunto ótimo
    for tamanho in range(1, len(codigos) + 1):
        for subset in combinations(codigos, tamanho):
            subset_list = list(subset)
            if not _respeita_capacidade(subset_list, mapa_ch, capacidade):
                continue
            if not _eh_independente(subset_list, grafo):
                continue
            score_subset = sum(scores.get(c, 0.0) for c in subset_list)
            if score_subset > melhor_score:
                melhor_score = score_subset
                melhor_subset = subset_list

    return melhor_subset


# ---------------------------------------------------------------------------
# Estratégia gulosa — heurística (|V| > 20)
# ---------------------------------------------------------------------------

def _mwis_guloso(
    codigos: list[str],
    scores: dict[str, float],
    mapa_ch: dict[str, int],
    grafo: dict[str, set[str]],
    capacidade: int,
) -> list[str]:
    """
    Heurística gulosa: ordena por score/CH (eficiência) e vai selecionando
    disciplinas que não conflitam com as já selecionadas e cabem na mochila.
    """
    # Ordena por score / CH decrescente (maior eficiência primeiro)
    ordenados = sorted(
        codigos,
        key=lambda c: scores.get(c, 0.0) / max(mapa_ch.get(c, 1), 1),
        reverse=True,
    )

    selecionados: list[str] = []
    ch_usado = 0
    em_conflito: set[str] = set()   # códigos já bloqueados por conflito

    for c in ordenados:
        if c in em_conflito:
            continue
        ch_c = mapa_ch.get(c, 0)
        if ch_usado + ch_c > capacidade:
            continue

        # Seleciona
        selecionados.append(c)
        ch_usado += ch_c

        # Marca vizinhos como bloqueados
        em_conflito.update(grafo.get(c, set()))

    return selecionados


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def resolver_mwis(
    candidatas: list[DisciplinaDisponivel],
    scores: dict[str, float],
    capacidade: int,
    df_curriculo: pd.DataFrame,
    limiar_exato: int = 20,
) -> ResultadoMWIS:
    """
    Resolve o MWIS com restrição de capacidade para as disciplinas candidatas.

    Parâmetros
    ----------
    candidatas    : lista de DisciplinaDisponivel (saída do filtro_disciplinas)
    scores        : dict { codigo → score }        (saída do score.py)
    capacidade    : capacidade máxima em horas     (saída do read_historico)
    df_curriculo  : DataFrame do CSV com a coluna HORARIOS
    limiar_exato  : tamanho máximo de |V| para usar enumeração exata (padrão 20)

    Retorno
    -------
    ResultadoMWIS com o conjunto selecionado e métricas da solução.
    """
    if not candidatas or capacidade <= 0:
        return ResultadoMWIS(
            selecionadas      = [],
            scores            = {},
            horarios          = {},
            ch_total          = 0,
            capacidade        = capacidade,
            score_total       = 0.0,
            ch_disponivel     = capacidade,
            n_conflitos_grafo = 0,
            estrategia        = "exata",
        )

    # ── Filtra apenas candidatas com score definido ──────────────────────────
    candidatas = [d for d in candidatas if d.codigo in scores]
    codigos    = [d.codigo for d in candidatas]
    mapa_ch    = {d.codigo: d.ch for d in candidatas}

    # ── Extrai horários e constrói grafo de conflitos ────────────────────────
    horarios = _extrair_horarios(df_curriculo, candidatas)
    grafo    = _construir_grafo_conflitos(candidatas, horarios)
    n_arestas = _contar_arestas(grafo)

    # ── Escolhe estratégia ───────────────────────────────────────────────────
    if len(codigos) <= limiar_exato:
        codigos_sel = _mwis_exato(codigos, scores, mapa_ch, grafo, capacidade)
        estrategia  = "exata"
    else:
        codigos_sel = _mwis_guloso(codigos, scores, mapa_ch, grafo, capacidade)
        estrategia  = "gulosa"

    # ── Monta resultado ───────────────────────────────────────────────────────
    mapa_disc   = {d.codigo: d for d in candidatas}
    selecionadas = [mapa_disc[c] for c in codigos_sel if c in mapa_disc]
    selecionadas.sort(key=lambda d: scores.get(d.codigo, 0.0), reverse=True)

    ch_total    = sum(d.ch for d in selecionadas)
    score_total = sum(scores[d.codigo] for d in selecionadas)

    # Horários originais (não normalizados) para exibição
    horarios_exib = _extrair_horarios_originais(df_curriculo, selecionadas)

    return ResultadoMWIS(
        selecionadas      = selecionadas,
        scores            = {d.codigo: scores[d.codigo] for d in selecionadas},
        horarios          = horarios_exib,
        ch_total          = ch_total,
        capacidade        = capacidade,
        score_total       = round(score_total, 6),
        ch_disponivel     = capacidade - ch_total,
        n_conflitos_grafo = n_arestas,
        estrategia        = estrategia,
    )


def _extrair_horarios_originais(
    df_curriculo: pd.DataFrame,
    candidatas: list[DisciplinaDisponivel],
) -> dict[str, list[str]]:
    """
    Extrai os slots no formato original (sem normalização) para exibição.
    """
    if "HORARIOS" not in df_curriculo.columns:
        return {d.codigo: [] for d in candidatas}

    mapa = df_curriculo.set_index("CODIGO")["HORARIOS"].to_dict()

    resultado = {}
    for d in candidatas:
        valor = mapa.get(d.codigo)
        if pd.isna(valor) or str(valor).strip() == "":
            resultado[d.codigo] = []
        else:
            resultado[d.codigo] = [s.strip() for s in str(valor).split("|") if s.strip()]

    return resultado


# ---------------------------------------------------------------------------
# Ponto de entrada — demonstração
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    BASE = os.path.dirname(__file__)

    # CSV com a coluna HORARIOS
    df_curr = pd.read_csv(os.path.join(BASE, "curriculo_CCO_HORARIOS.csv"))
    df_hist = pd.read_csv(os.path.join(BASE, "historico_CCO-3.csv"))

    SEMESTRE = "2025.2"

    dag        = construir_dag(df_curr)
    aluno      = processar_historico(df_hist, df_curr)
    candidatas = filtrar_disponiveis(dag, aluno, SEMESTRE)
    scores     = calcular_scores(dag, aluno, candidatas)

    resultado = resolver_mwis(candidatas, scores, aluno.capacidade_mochila, df_curr)

    # ── Exibe resultado ───────────────────────────────────────────────────────
    print("=" * 72)
    print(f"RECOMENDAÇÃO DE MATRÍCULA — {SEMESTRE}  [Variante B — MWIS]")
    print("=" * 72)
    print(
        f"Estratégia : {resultado.estrategia}  "
        f"({'≤ 20 candidatas' if resultado.estrategia == 'exata' else '> 20 candidatas'})"
    )
    print(f"Conflitos no grafo: {resultado.n_conflitos_grafo} aresta(s)\n")

    if not resultado.selecionadas:
        print("Nenhuma disciplina selecionada.")
    else:
        for rank, d in enumerate(resultado.selecionadas, start=1):
            slots = " / ".join(resultado.horarios.get(d.codigo, []))
            print(
                f"{rank:>2}. {d.codigo:<10}  {d.nome[:38]:<38}"
                f"  score: {scores[d.codigo]:>7.4f}  CH: {d.ch}h"
            )
            if slots:
                print(f"    Horários: {slots}")

    print()
    print(f"Capacidade utilizada : {resultado.ch_total}h / {resultado.capacidade}h")
    print(f"CH disponível        : {resultado.ch_disponivel}h")
    print(f"Score total          : {resultado.score_total:.4f}")
    print(f"Disciplinas          : {len(resultado.selecionadas)}")
    print(
        "\nConflitos resolvidos: nenhum par selecionado tem horário "
        "sobreposto ✓" if resultado.selecionadas else ""
    )
