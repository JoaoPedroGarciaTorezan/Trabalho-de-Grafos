"""
score.py
========
Etapa 4 do pipeline de recomendação de matrícula.

Calcula o score de cada disciplina candidata combinando quatro fatores:

    score(d) = (score_bfs(d) + score_base(d))
               × afinidade(area(d))
               × F_oferta(d)
               × (1 + F_critico(d))

Onde:
    score_bfs(d)  = Σ [ C(d,x) × P(x) × F(x) ]  para x ∈ descendentes BFS de d
    score_base(d) = P(d) × F(d)
                    — valor intrínseco da disciplina, independente dos descendentes.
                    Garante score > 0 mesmo para disciplinas sem descendentes,
                    diferenciando-as por tipo e profundidade topológica.
    afinidade     = média das notas APR na área / 10  (escala 0–1)
    F_oferta      = 1.0 se ANUAL | 2.0 se SEMESTRAL
    F_critico(d)  = caminho_critico(d) / max_caminho_critico_global  (0–1)

Componentes do score_bfs:
    C(d, x) = (prereqs_satisfeitos(x) + 1) / total_prereqs(x)
              — contribuição fracional de d para desbloquear x
    P(x)    = 2.0 (TCC) | 1.0 (OBRIGATORIA) | 0.5 (OPTATIVA)
    F(x)    = 1 / layer(x)  — fator de profundidade topológica

Uso como módulo:
    from score import calcular_scores
    scores = calcular_scores(dag, aluno, disponiveis)
    # scores: dict[str, float]  →  { codigo: score }

Uso como script:
    python score.py
"""

from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass, field

import pandas as pd

from dag_cco import DAG, Disciplina, construir_dag
from filtro_disciplinas import DisciplinaDisponivel, filtrar_disponiveis
from read_historico import HistoricoAluno, processar_historico


# ---------------------------------------------------------------------------
# Estrutura de saída detalhada (útil para debug e para o main.py)
# ---------------------------------------------------------------------------

@dataclass
class ScoreDetalhado:
    """Breakdown completo do score de uma disciplina candidata."""

    codigo:          str
    nome:            str
    score_bfs:       float
    score_base:      float        # P(d) x F(d) — valor intrínseco da disciplina
    afinidade:       float
    f_oferta:        float
    f_critico:       float        # valor normalizado 0-1
    caminho_critico: int          # comprimento absoluto (n de disciplinas)
    score_final:     float

    # Componentes BFS individuais (codigo_descendente -> contribuicao parcial)
    contribuicoes: dict[str, float] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"ScoreDetalhado({self.codigo!r}, "
            f"score={self.score_final:.4f}, "
            f"bfs={self.score_bfs:.4f}, "
            f"base={self.score_base:.4f}, "
            f"afinidade={self.afinidade:.3f}, "
            f"f_oferta={self.f_oferta:.1f}, "
            f"f_critico={self.f_critico:.3f})"
        )


# ---------------------------------------------------------------------------
# Funções auxiliares — componentes individuais do score
# ---------------------------------------------------------------------------

def _peso_tipo(tipo: str) -> float:
    """
    P(x): peso por tipo de disciplina.
        TCC          → 2.0
        OBRIGATORIA  → 1.0
        OPTATIVA     → 0.5
    """
    t = tipo.upper().strip()
    if t == "TCC":
        return 2.0
    if t == "OBRIGATORIA":
        return 1.0
    return 0.5   # OPTATIVA ou qualquer outro tipo


def _fator_profundidade(layer: int) -> float:
    """
    F(x) = 1 / layer(x).
    layer == 0 → disciplinas sem pré-requisitos (raízes).
    Para evitar divisão por zero, camada 0 usa F = 1.0
    (já que são as disciplinas mais acessíveis, profundidade mínima).
    """
    return 1.0 / (layer + 1)


def _fator_oferta(oferta: str) -> float:
    """
    F_oferta(d):
        ANUAL      → 1.0  (ofertada 2x por ano: em ambos os semestres --> menor urgencia)
        SEMESTRAL  → 2.0
    """
    oferta_norm = (
        oferta.upper().strip()
        .replace("°", "")
        .replace("º", "")
    )
    if oferta_norm == "ANUAL":
        return 1.0
    return 2.0


def _score_base(disc: Disciplina) -> float:
    """
    score_base(d) = P(d) x F(d)

    Valor intrínseco da disciplina, independente dos descendentes.
    Garante que disciplinas sem descendentes (score_bfs = 0) ainda
    recebam um score proporcional ao seu tipo e profundidade topológica:
        - Uma obrigatória rasa vale mais que uma optativa rasa.
        - Uma disciplina profunda (layer alto) vale menos que uma rasa,
          pois ela própria já exigiu muito do aluno para ser desbloqueada.
    """
    return _peso_tipo(disc.tipo) * _fator_profundidade(disc.layer)


def _contribuicao_fracional(
    candidata: str,
    descendente: str,
    dag: DAG,
    aprovadas: set[str],
) -> float:
    """
    C(d, x) = (prereqs_satisfeitos(x) + 1) / total_prereqs(x)

    Conta quantos pré-requisitos de `descendente` já estão em `aprovadas`,
    soma 1 para representar a contribuição de `candidata` (que estamos
    considerando cursar), e divide pelo total de pré-requisitos.

    Se `descendente` não tiver pré-requisitos, C = 1.0 (contribuição máxima,
    pois `candidata` é o único desbloqueador possível).
    """
    disc_x = dag.vertices.get(descendente)
    if disc_x is None:
        return 0.0

    total_prereqs = len(disc_x.prereqs)
    if total_prereqs == 0:
        return 1.0

    # Conta pré-reqs já satisfeitos (excluindo a própria candidata, que ainda
    # não foi cursada — mas incluímos +1 para representar sua contribuição)
    ja_satisfeitos = sum(
        1 for p in disc_x.prereqs
        if p in aprovadas or p == candidata
    )

    # +1 garante que cursando `candidata` o numerador cresce
    # Mas evita dupla contagem caso `candidata` já esteja em `aprovadas`
    if candidata in aprovadas:
        contribuicao = ja_satisfeitos
    else:
        # candidata ainda não cursada; +1 representa que ela será cursada
        prereqs_sem_candidata = sum(
            1 for p in disc_x.prereqs
            if p in aprovadas
        )
        contribuicao = prereqs_sem_candidata + 1

    return min(contribuicao / total_prereqs, 1.0)


# ---------------------------------------------------------------------------
# Caminho Crítico — maior caminho ponderado no DAG a partir de d
# ---------------------------------------------------------------------------

def _calcular_caminho_critico(dag: DAG, codigo_inicio: str) -> int:
    """
    Retorna o comprimento do maior caminho (em número de disciplinas)
    partindo de `codigo_inicio` e seguindo as arestas do DAG.

    Usa programação dinâmica sobre a ordem topológica dos descendentes,
    restrita ao subgrafo alcançável a partir de `codigo_inicio`.

    Retorna 0 se a disciplina não tiver descendentes.
    """
    # Obtém todos os descendentes (inclusive o próprio nó de início)
    descendentes = dag.descendentes_bfs(codigo_inicio)
    subgrafo = descendentes | {codigo_inicio}

    # Ordem topológica restrita ao subgrafo (usa o layer já calculado pelo Kahn)
    topo_local = sorted(
        subgrafo,
        key=lambda c: dag.vertices[c].layer
    )

    # dp[v] = comprimento do maior caminho de `codigo_inicio` até v
    dp: dict[str, int] = {v: 0 for v in subgrafo}
    dp[codigo_inicio] = 0

    maior = 0
    for u in topo_local:
        for v in dag.adj.get(u, []):
            if v in subgrafo:
                novo = dp[u] + 1
                if novo > dp[v]:
                    dp[v] = novo
                    if novo > maior:
                        maior = novo

    return maior


def _calcular_todos_caminhos_criticos(
    dag: DAG,
    candidatas: list[DisciplinaDisponivel],
) -> dict[str, int]:
    """
    Calcula o caminho crítico para cada disciplina candidata.
    Retorna dict { codigo → comprimento_do_caminho_critico }.
    """
    return {
        d.codigo: _calcular_caminho_critico(dag, d.codigo)
        for d in candidatas
    }


# ---------------------------------------------------------------------------
# Score BFS
# ---------------------------------------------------------------------------

def _calcular_score_bfs(
    candidata: str,
    dag: DAG,
    aprovadas: set[str],
) -> tuple[float, dict[str, float]]:
    """
    Calcula o score_bfs da disciplina candidata.

    Retorna:
        (score_bfs: float, contribuicoes: dict[codigo_desc → contribuicao_parcial])

    score_bfs(d) = Σ [ C(d,x) × P(x) × F(x) ]
                   x ∈ BFS(d)
    """
    descendentes = dag.descendentes_bfs(candidata)

    if not descendentes:
        return 0.0, {}

    contribuicoes: dict[str, float] = {}
    total = 0.0

    for x in descendentes:
        disc_x = dag.vertices.get(x)
        if disc_x is None:
            continue

        c = _contribuicao_fracional(candidata, x, dag, aprovadas)
        p = _peso_tipo(disc_x.tipo)
        f = _fator_profundidade(disc_x.layer)

        parcial = c * p * f
        contribuicoes[x] = parcial
        total += parcial

    return total, contribuicoes


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def calcular_scores(
    dag: DAG,
    aluno: HistoricoAluno,
    candidatas: list[DisciplinaDisponivel],
) -> dict[str, float]:
    """
    Calcula o score final de cada disciplina candidata.

    Parâmetros
    ----------
    dag        : DAG construído pelo dag_cco.
    aluno      : HistoricoAluno processado pelo read_historico.
    candidatas : Lista de DisciplinaDisponivel (saída do filtro_disciplinas).

    Retorno
    -------
    Dicionário { codigo → score_final } ordenado do maior para o menor score.
    """
    detalhados = calcular_scores_detalhados(dag, aluno, candidatas)
    return {
        codigo: s.score_final
        for codigo, s in detalhados.items()
    }


def calcular_scores_detalhados(
    dag: DAG,
    aluno: HistoricoAluno,
    candidatas: list[DisciplinaDisponivel],
) -> dict[str, ScoreDetalhado]:
    """
    Versão detalhada de calcular_scores.
    Retorna dict { codigo → ScoreDetalhado } com todos os fatores expostos.
    Útil para debug, relatórios e o main.py.
    """
    aprovadas = aluno.aprovadas

    # ── Pré-calcula caminhos críticos e normaliza ────────────────────────────
    caminhos = _calcular_todos_caminhos_criticos(dag, candidatas)
    max_caminho = max(caminhos.values(), default=1)
    if max_caminho == 0:
        max_caminho = 1   # evita divisão por zero quando todas têm caminho 0

    # ── Calcula score para cada candidata ────────────────────────────────────
    resultados: dict[str, ScoreDetalhado] = {}

    for disc in candidatas:
        codigo = disc.codigo
        disc_dag = dag.vertices.get(codigo)
        if disc_dag is None:
            continue

        # Parte 1 — BFS + base intrínseca
        score_bfs, contribuicoes = _calcular_score_bfs(codigo, dag, aprovadas)
        score_base = _score_base(disc_dag)

        # Parte 2 — Fatores multiplicativos
        afinidade   = aluno.afinidade_de(disc.area)           # 0-1, default 0.5
        f_oferta    = _fator_oferta(disc_dag.oferta)           # 1.0 ou 2.0
        caminho_abs = caminhos[codigo]                         # inteiro
        f_critico   = caminho_abs / max_caminho                # 0-1

        score_final = (score_bfs + score_base) * afinidade * f_oferta * (1 + f_critico)

        resultados[codigo] = ScoreDetalhado(
            codigo          = codigo,
            nome            = disc.nome,
            score_bfs       = round(score_bfs, 6),
            score_base      = round(score_base, 6),
            afinidade       = round(afinidade, 4),
            f_oferta        = f_oferta,
            f_critico       = round(f_critico, 4),
            caminho_critico = caminho_abs,
            score_final     = round(score_final, 6),
            contribuicoes   = {k: round(v, 6) for k, v in contribuicoes.items()},
        )

    # Ordena do maior para o menor score final
    return dict(
        sorted(resultados.items(), key=lambda item: item[1].score_final, reverse=True)
    )


# ---------------------------------------------------------------------------
# Ponto de entrada — demonstração
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    BASE = os.path.dirname(__file__)

    # ── Carrega dados ────────────────────────────────────────────────────────
    df_curr = pd.read_csv(os.path.join(BASE, "curriculo_cco.csv"))
    df_hist = pd.read_csv(os.path.join(BASE, "historico_CCO-3.csv"))

    SEMESTRE = "2025.2"

    # ── Constrói DAG e processa histórico ────────────────────────────────────
    dag   = construir_dag(df_curr)
    aluno = processar_historico(df_hist, df_curr)

    # ── Filtra candidatas ─────────────────────────────────────────────────────
    candidatas = filtrar_disponiveis(dag, aluno, SEMESTRE)

    # ── Calcula scores ────────────────────────────────────────────────────────
    detalhados = calcular_scores_detalhados(dag, aluno, candidatas)

    # ── Exibe resultado ───────────────────────────────────────────────────────
    print("=" * 72)
    print(f"SCORES DE RECOMENDAÇÃO — {SEMESTRE}")
    print("=" * 72)

    for rank, (codigo, s) in enumerate(detalhados.items(), start=1):
        print(
            f"\n{rank:>2}. {codigo:<10}  {s.nome[:40]:<40}"
            f"  score: {s.score_final:>7.4f}"
        )
        print(
            f"    bfs={s.score_bfs:.4f}  base={s.score_base:.4f}  "
            f"afinidade={s.afinidade:.3f}  "
            f"f_oferta={s.f_oferta:.1f}  "
            f"f_critico={s.f_critico:.3f} (caminho={s.caminho_critico})"
        )
        if s.contribuicoes:
            top3 = sorted(
                s.contribuicoes.items(), key=lambda x: x[1], reverse=True
            )[:3]
            desc_str = "  ".join(
                f"{cod}={val:.4f}" for cod, val in top3
            )
            print(f"    top descendentes: {desc_str}")

    print("\n" + "=" * 72)
    print(f"Total de candidatas avaliadas: {len(detalhados)}")
    print(
        f"Score máximo: {next(iter(detalhados.values())).score_final:.4f}"
        if detalhados else "Nenhuma candidata."
    )
