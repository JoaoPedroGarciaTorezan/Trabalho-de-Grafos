"""
Leitura do currículo CCO a partir de um DataFrame pandas
e construção do DAG de pré-requisitos via algoritmo de Kahn.

Estrutura do DAG:
    A → B  significa  "A é pré-requisito direto de B"
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# 1. Estrutura de dados
# ---------------------------------------------------------------------------

@dataclass
class Disciplina:
    codigo: str
    nome: str
    tipo: str
    area: str
    periodo: int           # menor período possível (quando há "5|7" usa 5)
    oferta: str
    ch: int
    prereqs: list[str]     = field(default_factory=list)   # arestas de entrada
    equivalentes: list[str]= field(default_factory=list)
    layer: int             = 0                              # camada topológica


class DAG:
    """
    Grafo Acíclico Dirigido de disciplinas.
    Aresta A → B  :  A é pré-requisito direto de B.
    """

    def __init__(self) -> None:
        self.vertices: dict[str, Disciplina] = {}
        # adj[u] = lista de v tal que u → v  (u é pré-req de v)
        self.adj: dict[str, list[str]] = defaultdict(list)
        # in_adj[v] = lista de u tal que u → v  (pré-reqs diretos de v)
        self.in_adj: dict[str, list[str]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Construção
    # ------------------------------------------------------------------

    def add_vertice(self, disc: Disciplina) -> None:
        self.vertices[disc.codigo] = disc

    def add_aresta(self, origem: str, destino: str) -> None:
        """origem → destino  (origem é pré-req de destino)."""
        self.adj[origem].append(destino)
        self.in_adj[destino].append(origem)

    # ------------------------------------------------------------------
    # Kahn – ordem topológica + atribuição de camadas
    # ------------------------------------------------------------------

    def kahn(self) -> tuple[list[str], set[str]]:
        """
        Executa o algoritmo de Kahn.

        Retorna:
            topo_order : lista com a ordem topológica dos vértices
            ciclos     : conjunto de vértices não alcançados (ciclos)

        Também atribui `layer` a cada Disciplina em self.vertices.
        """
        in_degree: dict[str, int] = {
            v: len(self.in_adj[v]) for v in self.vertices
        }

        # Camada 0 → vértices sem pré-requisitos (raízes)
        layer: dict[str, int] = {}
        queue: deque[str] = deque()

        for v, deg in in_degree.items():
            if deg == 0:
                layer[v] = 0
                queue.append(v)

        topo_order: list[str] = []

        while queue:
            u = queue.popleft()
            topo_order.append(u)

            for v in self.adj[u]:
                in_degree[v] -= 1
                # camada de v = max(camada atual, camada de u + 1)
                layer[v] = max(layer.get(v, 0), layer[u] + 1)
                if in_degree[v] == 0:
                    queue.append(v)

        # Propaga layers para os objetos Disciplina
        for codigo, l in layer.items():
            self.vertices[codigo].layer = l

        ciclos = set(self.vertices) - set(topo_order)
        return topo_order, ciclos

    # ------------------------------------------------------------------
    # Utilitários
    # ------------------------------------------------------------------

    def camadas(self) -> dict[int, list[str]]:
        """Agrupa vértices por camada (após kahn ter sido executado)."""
        resultado: dict[int, list[str]] = defaultdict(list)
        for codigo, disc in self.vertices.items():
            resultado[disc.layer].append(codigo)
        return dict(sorted(resultado.items()))

    def predecessores(self, codigo: str) -> list[str]:
        """Pré-requisitos diretos de uma disciplina."""
        return self.in_adj.get(codigo, [])

    def sucessores(self, codigo: str) -> list[str]:
        """Disciplinas que têm `codigo` como pré-requisito direto."""
        return self.adj.get(codigo, [])

    def descendentes_bfs(self, codigo: str) -> set[str]:
        """
        BFS a partir de `codigo` seguindo as arestas u → v.
        Retorna todos os descendentes (disciplinas desbloqueadas em cadeia).
        """
        visitados: set[str] = set()
        fila: deque[str] = deque([codigo])
        while fila:
            u = fila.popleft()
            for v in self.adj.get(u, []):
                if v not in visitados:
                    visitados.add(v)
                    fila.append(v)
        return visitados

    def __repr__(self) -> str:
        return (
            f"DAG(vértices={len(self.vertices)}, "
            f"arestas={sum(len(v) for v in self.adj.values())})"
        )


# ---------------------------------------------------------------------------
# 2. Leitura do DataFrame e construção do DAG
# ---------------------------------------------------------------------------

def _parse_periodo(valor: str) -> int:
    """'5|7' → 5   |   '3' → 3"""
    partes = str(valor).split("|")
    return min(int(p) for p in partes if p.strip().isdigit())


def _parse_lista(valor) -> list[str]:
    """'XDES01|XDES02' → ['XDES01', 'XDES02']   |   NaN → []"""
    if pd.isna(valor) or str(valor).strip() == "":
        return []
    return [c.strip() for c in str(valor).split("|") if c.strip()]


def construir_dag(df: pd.DataFrame) -> DAG:
    """
    Recebe o DataFrame do currículo CCO e devolve o DAG completo.

    Colunas esperadas:
        CODIGO, NOME, TIPO, AREA, PERIODO, OFERTA, CH,
        PREREQUISITOS, EQUIVALENTES

    Observações:
        - PERIODO pode conter valores como '5|7'; usa-se o menor.
        - PREREQUISITOS pode conter múltiplos códigos separados por '|'.
        - Ciclos detectados (ex.: TCC1 ↔ XAHC03 no CSV) são tratados:
          a aresta que fecha o ciclo é ignorada e reportada como aviso.
    """
    dag = DAG()

    # ── Passo 1: adiciona todos os vértices ──────────────────────────────────
    for _, row in df.iterrows():
        disc = Disciplina(
            codigo       = str(row["CODIGO"]).strip(),
            nome         = str(row["NOME"]).strip(),
            tipo         = str(row["TIPO"]).strip(),
            area         = str(row["AREA"]).strip(),
            periodo      = _parse_periodo(row["PERIODO"]),
            oferta       = str(row["OFERTA"]).strip(),
            ch           = int(row["CH"]),
            prereqs      = _parse_lista(row["PREREQUISITOS"]),
            equivalentes = _parse_lista(row["EQUIVALENTES"]),
        )
        dag.add_vertice(disc)

    codigos_validos = set(dag.vertices)

    # ── Passo 2: detecta ciclos potenciais (Kahn provisório) ─────────────────
    # Construímos um in_degree temporário para identificar ciclos antes de
    # comprometer o grafo definitivo.
    _in_deg_tmp: dict[str, int] = defaultdict(int)
    _edges_tmp: list[tuple[str, str]] = []

    for codigo, disc in dag.vertices.items():
        for pre in disc.prereqs:
            if pre in codigos_validos:
                _in_deg_tmp[codigo] += 1
                _edges_tmp.append((pre, codigo))

    # Kahn provisório → descobre quais arestas pertencem a ciclos
    _deg = {v: 0 for v in dag.vertices}
    _deg.update(_in_deg_tmp)
    _adj_tmp: dict[str, list[str]] = defaultdict(list)
    for u, v in _edges_tmp:
        _adj_tmp[u].append(v)

    _q = deque(v for v, d in _deg.items() if d == 0)
    _visited: set[str] = set()
    while _q:
        u = _q.popleft()
        _visited.add(u)
        for v in _adj_tmp[u]:
            _deg[v] -= 1
            if _deg[v] == 0:
                _q.append(v)

    _nos_em_ciclo = set(dag.vertices) - _visited  # vértices não alcançados

    # ── Passo 3: adiciona arestas válidas (ignora as que fecham ciclo) ────────
    arestas_ignoradas: list[tuple[str, str]] = []

    for codigo, disc in dag.vertices.items():
        for pre in disc.prereqs:
            if pre not in codigos_validos:
                # pré-req fora do currículo (não deveria ocorrer)
                continue

            # Ignora aresta se AMBOS os nós estão no ciclo E a aresta
            # inversa já existe (heurística conservadora)
            if codigo in _nos_em_ciclo and pre in _nos_em_ciclo:
                # Verifica se a aresta inversa (codigo → pre) fecha o ciclo
                if pre in disc.prereqs and codigo in dag.vertices[pre].prereqs:
                    # Quebra o ciclo: mantém apenas a aresta do nó de menor
                    # período para o de maior período
                    per_pre    = dag.vertices[pre].periodo
                    per_codigo = dag.vertices[codigo].periodo
                    if per_pre >= per_codigo:
                        arestas_ignoradas.append((pre, codigo))
                        continue

            dag.add_aresta(pre, codigo)

    if arestas_ignoradas:
        print(f"[AVISO] {len(arestas_ignoradas)} aresta(s) ignorada(s) "
              f"por formar ciclo: {arestas_ignoradas}")

    # ── Passo 4: Kahn definitivo (camadas) ───────────────────────────────────
    topo, ciclos = dag.kahn()

    if ciclos:
        print(f"[AVISO] {len(ciclos)} vértice(s) não alcançado(s) "
              f"(possível ciclo residual): {ciclos}")
    else:
        print(f"[OK] Ordem topológica válida para todos os "
              f"{len(dag.vertices)} vértices.")

    return dag


# ---------------------------------------------------------------------------
# 3. Ponto de entrada — exemplo de uso
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # ── Carrega o CSV ────────────────────────────────────────────────────────
    CSV_PATH = "curriculo_cco.csv"   # ajuste o caminho conforme necessário
    df = pd.read_csv(CSV_PATH)

    # ── Constrói o DAG ───────────────────────────────────────────────────────
    dag = construir_dag(df)
    print(dag)
    print()

    # ── Camadas (resultado do Kahn) ──────────────────────────────────────────
    print("Camadas topológicas:")
    for camada, codigos in dag.camadas().items():
        nomes = [dag.vertices[c].nome for c in codigos]
        print(f"  Layer {camada} ({len(codigos)} disciplinas):")
        for codigo, nome in zip(codigos, nomes):
            print(f"    {codigo:10s}  {nome}")
        print()

    # ── Exemplo: predecessores e descendentes ────────────────────────────────
    exemplo = "XMAC02"
    print(f"Pré-requisitos diretos de {exemplo}:")
    for p in dag.predecessores(exemplo):
        print(f"  ← {p} ({dag.vertices[p].nome})")

    print(f"\nDisciplinas que dependem (diretamente) de {exemplo}:")
    for s in dag.sucessores(exemplo):
        print(f"  → {s} ({dag.vertices[s].nome})")

    print(f"\nTodos os descendentes de {exemplo} (BFS):")
    for d in sorted(dag.descendentes_bfs(exemplo)):
        print(f"  {d} ({dag.vertices[d].nome})")