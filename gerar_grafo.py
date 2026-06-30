"""
gerar_grafo.py
==============
Etapa de visualização do pipeline de recomendação de matrícula.

Gera um PNG do grafo de pré-requisitos do currículo, em camadas por período,
colorindo cada disciplina conforme o estado do aluno:

    CONCLUIDA   → já aprovada (situação 'APR' ou 'CUMP' no histórico)
    REPROVADA   → reprovada e ainda não aprovada em nenhuma tentativa posterior
    DISPONIVEL  → liberada para matrícula no semestre informado (saída do
                  filtro_disciplinas)
    NAO_CURSADA → ainda bloqueada por pré-requisito não satisfeito

Dentro de cada coluna de período, as disciplinas OBRIGATÓRIAS (e TCC) ficam
centralizadas na parte de cima (desenhadas como círculo), e as OPTATIVAS
daquele mesmo período ficam abaixo delas, separadas por um espaço, desenhadas
como quadrado — assim a sequência principal da grade fica visualmente isolada
das eletivas, sem precisar de uma faixa lateral separada.

As disciplinas selecionadas pelo MWIS (resultado final da recomendação)
recebem um contorno dourado para se destacarem das demais disponíveis.

Uso como módulo:
    from gerar_grafo import gerar_grafo_curriculo
    gerar_grafo_curriculo(
        dag=dag,
        aluno=aluno,
        df_historico=df_historico,
        candidatas=candidatas,
        resultado=resultado,
        nome_curso=nome_curso,
        semestre=semestre,
        caminho_saida="grafo_CCO_2025.1.png",
    )
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # backend não interativo — necessário em scripts/pipelines
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

import networkx as nx
import pandas as pd

from dag_cco import DAG, Disciplina
from read_historico import HistoricoAluno
from filtro_disciplinas import DisciplinaDisponivel


# ---------------------------------------------------------------------------
# Cores por estado
# ---------------------------------------------------------------------------

_COR_ESTADO = {
    "CONCLUIDA":   "#4CAF50",
    "REPROVADA":   "#F44336",
    "DISPONIVEL":  "#2196F3",
    "NAO_CURSADA": "#B0BEC5",
}

_COR_CONTORNO_PADRAO    = "#37474F"
_COR_CONTORNO_SELECIONADA = "#FFC107"


# ---------------------------------------------------------------------------
# Classificação de estado
# ---------------------------------------------------------------------------

def _classificar_estados(
    dag: DAG,
    aluno: HistoricoAluno,
    df_historico: Optional[pd.DataFrame],
    candidatas: list[DisciplinaDisponivel],
) -> dict[str, str]:
    """
    Retorna { codigo → estado } para todos os vértices do DAG.
    """
    aprovadas = aluno.aprovadas
    codigos_disponiveis = {d.codigo for d in candidatas}

    # Reprovadas: aparecem no histórico com situação iniciada por 'REP' e
    # que NÃO constam entre as aprovadas (cobre o caso de reprovar e depois
    # passar em uma segunda tentativa, que não deve marcar REPROVADA).
    reprovadas: set[str] = set()
    if df_historico is not None and not df_historico.empty and "situacao" in df_historico.columns:
        mask_rep = df_historico["situacao"].astype(str).str.startswith("REP")
        reprovadas = set(
            df_historico.loc[mask_rep, "codigo"].astype(str).str.strip()
        ) - aprovadas

    estados: dict[str, str] = {}
    for codigo in dag.vertices:
        if codigo in aprovadas:
            estados[codigo] = "CONCLUIDA"
        elif codigo in codigos_disponiveis:
            estados[codigo] = "DISPONIVEL"
        elif codigo in reprovadas:
            estados[codigo] = "REPROVADA"
        else:
            estados[codigo] = "NAO_CURSADA"

    return estados


# ---------------------------------------------------------------------------
# Classificação por tipo (obrigatória/TCC vs. optativa) — define a forma
# ---------------------------------------------------------------------------

def _eh_obrigatoria(disc: Disciplina) -> bool:
    """
    True para OBRIGATORIA e TCC (ficam na parte de cima da coluna, círculo).
    False para qualquer outro tipo (ex.: OPTATIVA, ELETIVA — ficam embaixo,
    desenhadas como quadrado).
    """
    return disc.tipo.upper().strip() in {"OBRIGATORIA", "TCC"}


# ---------------------------------------------------------------------------
# Layout em camadas por período da grade
# ---------------------------------------------------------------------------

_GAP_OPTATIVAS = 1.4   # espaço vertical entre o bloco de obrigatórias e o de optativas


def _layout_por_periodo(
    dag: DAG,
) -> tuple[dict[str, tuple[float, float]], dict[int, list[str]], dict[int, int]]:
    """
    Posiciona cada disciplina em (x, y), onde x = período sugerido na grade
    (campo `periodo` de Disciplina).

    Dentro de cada coluna (mesmo x):
        - Disciplinas OBRIGATORIA/TCC ficam centralizadas em torno de y=0,
          na parte de cima.
        - Disciplinas OPTATIVA ficam empilhadas abaixo do bloco de
          obrigatórias daquele mesmo período, separadas por um espaço fixo.

    Retorna (pos, por_periodo, alturas_obrig):
        pos          : { codigo → (x, y) }
        por_periodo  : { periodo → [codigos] }, usado para os rótulos no topo
        alturas_obrig: { periodo → nº de obrigatórias }, usado para alinhar
                        o rótulo "Nº Período" sempre acima do bloco de
                        obrigatórias, independente de quantas optativas tem
                        embaixo.
    """
    por_periodo: dict[int, list[str]] = defaultdict(list)
    for codigo, disc in dag.vertices.items():
        por_periodo[disc.periodo].append(codigo)

    pos: dict[str, tuple[float, float]] = {}
    alturas_obrig: dict[int, int] = {}

    for periodo, codigos in por_periodo.items():
        obrig = sorted(c for c in codigos if _eh_obrigatoria(dag.vertices[c]))
        optat = sorted(c for c in codigos if not _eh_obrigatoria(dag.vertices[c]))

        x = float(periodo - 1)

        # Bloco de obrigatórias: centralizado em y=0
        n_o = len(obrig)
        for i, codigo in enumerate(obrig):
            y = (n_o - 1) / 2 - i
            pos[codigo] = (x, float(y))

        # Bloco de optativas: empilhado abaixo do menor y das obrigatórias
        y_min_obrig = -(n_o - 1) / 2 if n_o else 0.0
        y_cursor = y_min_obrig - _GAP_OPTATIVAS
        for codigo in optat:
            pos[codigo] = (x, float(y_cursor))
            y_cursor -= 1.0

        alturas_obrig[periodo] = n_o

    return pos, dict(sorted(por_periodo.items())), alturas_obrig


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def gerar_grafo_curriculo(
    dag: DAG,
    aluno: HistoricoAluno,
    df_historico: Optional[pd.DataFrame],
    candidatas: list[DisciplinaDisponivel],
    resultado,  # ResultadoMWIS — não importado diretamente para evitar import circular com mwis.py
    nome_curso: str,
    semestre: str,
    caminho_saida: str,
) -> str:
    """
    Gera e salva o PNG do grafo de pré-requisitos com o estado do aluno.

    Parâmetros
    ----------
    dag            : DAG construído por dag_cco.construir_dag
    aluno          : HistoricoAluno (read_historico.processar_historico)
    df_historico   : DataFrame bruto do histórico (parse_historico), usado
                     apenas para identificar disciplinas reprovadas. Pode
                     ser None — nesse caso REPROVADA nunca é atribuída.
    candidatas     : lista de DisciplinaDisponivel (filtro_disciplinas)
    resultado      : ResultadoMWIS (mwis.resolver_mwis) — usado para destacar
                     com contorno dourado as disciplinas selecionadas
    nome_curso     : nome completo do curso, usado no título
    semestre       : semestre consultado (ex: '2025.1'), usado no título
    caminho_saida  : caminho do arquivo .png a ser salvo

    Retorno
    -------
    O próprio `caminho_saida`, para facilitar o encadeamento no pipeline.
    """

    # ── 1. Monta o grafo networkx a partir do DAG já construído ──────────────
    G = nx.DiGraph()
    G.add_nodes_from(dag.vertices.keys())
    for origem, destinos in dag.adj.items():
        for destino in destinos:
            G.add_edge(origem, destino)

    # ── 2. Estado de cada disciplina + destaque de seleção ───────────────────
    estados = _classificar_estados(dag, aluno, df_historico, candidatas)
    codigos_selecionados = (
        {d.codigo for d in resultado.selecionadas} if resultado is not None else set()
    )

    # ── 3. Layout em camadas (obrigatórias acima, optativas embaixo) ─────────
    pos, por_periodo, alturas_obrig = _layout_por_periodo(dag)

    obrig_nodes = [c for c in G.nodes if _eh_obrigatoria(dag.vertices[c])]
    optat_nodes = [c for c in G.nodes if not _eh_obrigatoria(dag.vertices[c])]

    def _cores_do_grupo(grupo: list[str]) -> tuple[list[str], list[str], list[float]]:
        cores, contornos, larguras = [], [], []
        for codigo in grupo:
            cores.append(_COR_ESTADO[estados.get(codigo, "NAO_CURSADA")])
            if codigo in codigos_selecionados:
                contornos.append(_COR_CONTORNO_SELECIONADA)
                larguras.append(3.5)
            else:
                contornos.append(_COR_CONTORNO_PADRAO)
                larguras.append(1.0)
        return cores, contornos, larguras

    cores_obrig, contornos_obrig, larguras_obrig = _cores_do_grupo(obrig_nodes)
    cores_optat, contornos_optat, larguras_optat = _cores_do_grupo(optat_nodes)

    # ── 4. Plot ────────────────────────────────────────────────────────────────
    largura = max(20, 2.6 * len(por_periodo))

    ys = [y for _, y in pos.values()]
    altura = max(11.0, (max(ys) - min(ys)) * 0.85 + 4) if ys else 11.0
    plt.figure(figsize=(largura, altura))
    ax = plt.gca()

    nx.draw_networkx_edges(
        G, pos,
        edge_color="#90A4AE",
        width=1.2,
        arrows=True,
        arrowsize=14,
        ax=ax,
    )

    if obrig_nodes:
        nx.draw_networkx_nodes(
            G, pos,
            nodelist=obrig_nodes,
            node_shape="o",
            node_size=3600,
            node_color=cores_obrig,
            edgecolors=contornos_obrig,
            linewidths=larguras_obrig,
            ax=ax,
        )

    if optat_nodes:
        nx.draw_networkx_nodes(
            G, pos,
            nodelist=optat_nodes,
            node_shape="s",
            node_size=3600,
            node_color=cores_optat,
            edgecolors=contornos_optat,
            linewidths=larguras_optat,
            ax=ax,
        )

    labels = {c: f"{c}\n{dag.vertices[c].nome}" for c in G.nodes}
    nx.draw_networkx_labels(
        G, pos,
        labels=labels,
        font_size=6.5,
        font_weight="bold",
        ax=ax,
    )

    for periodo in por_periodo:
        n_o = alturas_obrig.get(periodo, 0)
        topo_obrig = (n_o - 1) / 2 if n_o else 0.0
        ax.text(
            periodo - 1, topo_obrig + 0.8,
            f"{periodo}º Período",
            ha="center", va="bottom", fontsize=13, fontweight="bold", color="#37474F",
        )

    legenda = [Patch(facecolor=c, label=s) for s, c in _COR_ESTADO.items()]
    legenda.append(
        Patch(
            facecolor="white", edgecolor=_COR_CONTORNO_SELECIONADA, linewidth=3,
            label="SELECIONADA (MWIS)",
        )
    )
    # Entradas de forma (círculo x quadrado) — usam marcadores em vez de cor
    legenda.append(
        Line2D([0], [0], marker="o", linestyle="None", markersize=11,
               markerfacecolor="#CFD8DC", markeredgecolor=_COR_CONTORNO_PADRAO,
               label="Obrigatória / TCC")
    )
    legenda.append(
        Line2D([0], [0], marker="s", linestyle="None", markersize=10,
               markerfacecolor="#CFD8DC", markeredgecolor=_COR_CONTORNO_PADRAO,
               label="Optativa / Eletiva")
    )
    plt.legend(handles=legenda, loc="lower right", fontsize=11)

    plt.title(
        f"Grade Curricular — {nome_curso} ({semestre})",
        fontsize=15, fontweight="bold",
    )
    plt.axis("off")
    plt.savefig(caminho_saida, dpi=150, bbox_inches="tight")
    plt.close()

    return caminho_saida
