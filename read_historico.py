"""
historico_aluno.py
==================
Passo 2 do pipeline de recomendação de matrícula.

A partir do DataFrame do histórico do aluno, extrai:
    1. Conjunto de disciplinas aprovadas  (situacao == 'APR' ou 'CUMP')
  2. Capacidade da mochila              (média de CH aprovada por semestre real)
  3. Afinidade por área                 (média de notas / 10, escala 0-1)

Regras adotadas (conforme decisão de projeto):
  - Transferências (semestre == 'TRANSFERENCIA') são ignoradas na capacidade.
    - 'APR' e 'CUMP' contam como aprovação para o conjunto de disciplinas cursadas.
  - CUMP/DISP sem nota são ignorados no cálculo de afinidade.
  - Normalização de afinidade: média_da_área / 10  →  0 a 1 linear.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


# ---------------------------------------------------------------------------
# Estrutura de saída
# ---------------------------------------------------------------------------

@dataclass
class HistoricoAluno:
    """Resultado do processamento do histórico de um aluno."""

    # Conjunto de códigos aprovados (situacao == 'APR' ou 'CUMP')
    aprovadas: set[str] = field(default_factory=set)

    # Capacidade da mochila: média de CH aprovada por semestre real (arredondada)
    capacidade_mochila: int = 0

    # Afinidade por área: { nome_area -> float 0-1 }
    afinidade: dict[str, float] = field(default_factory=dict)

    # Detalhes intermediários (úteis para debug / score)
    ch_por_semestre: dict[str, int]   = field(default_factory=dict)
    notas_por_area:  dict[str, list[float]] = field(default_factory=dict)

    def afinidade_de(self, area: str, default: float = 0.5) -> float:
        """
        Retorna a afinidade para uma área.
        Se a área não tiver histórico, devolve `default` (0.5 = neutro).
        """
        return self.afinidade.get(area, default)

    def __repr__(self) -> str:
        areas = ", ".join(
            f"{a}={v:.2f}" for a, v in self.afinidade.items()
        )
        return (
            f"HistoricoAluno("
            f"aprovadas={len(self.aprovadas)}, "
            f"capacidade={self.capacidade_mochila}h, "
            f"afinidade=[{areas}])"
        )


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def processar_historico(
    df_historico: pd.DataFrame,
    df_curriculo: pd.DataFrame,
) -> HistoricoAluno:
    """
    Processa o histórico do aluno e devolve um HistoricoAluno.

    Parâmetros
    ----------
    df_historico : DataFrame com colunas
        semestre, codigo, nome, ch, situacao, media

    df_curriculo : DataFrame com colunas
        CODIGO, AREA  (usado para mapear disciplina → área)

    Retorno
    -------
    HistoricoAluno com aprovadas, capacidade_mochila e afinidade preenchidos.
    """

    resultado = HistoricoAluno()

    # ── Mapa codigo → área  (do currículo) ──────────────────────────────────
    area_map: dict[str, str] = (
        df_curriculo.set_index("CODIGO")["AREA"].to_dict()
    )

    # ── Filtra APR e CUMP ───────────────────────────────────────────────────
    mask_apr = df_historico["situacao"].isin(["APR", "CUMP"])
    df_apr   = df_historico[mask_apr].copy()

    # ── 1. Conjunto de aprovadas ─────────────────────────────────────────────
    resultado.aprovadas = set(df_apr["codigo"].str.strip())

    # ── 2. Capacidade da mochila ─────────────────────────────────────────────
    # Considera apenas semestres reais (exclui 'TRANSFERENCIA')
    mask_semestre_real = df_apr["semestre"] != "TRANSFERENCIA"
    df_semestres_reais = df_apr[mask_semestre_real]

    # Garante que ch é numérico — o parse_historico lê tudo como string
    df_semestres_reais = df_semestres_reais.copy()
    df_semestres_reais["ch"] = pd.to_numeric(df_semestres_reais["ch"], errors="coerce").fillna(0)

    ch_por_semestre: dict[str, int] = (
        df_semestres_reais
        .groupby("semestre")["ch"]
        .sum()
        .astype(int)
        .to_dict()
    )
    resultado.ch_por_semestre = ch_por_semestre

    if ch_por_semestre:
        media_ch = sum(ch_por_semestre.values()) / len(ch_por_semestre)
        # Arredonda para múltiplo de 16 mais próximo (granularidade de CH)
        resultado.capacidade_mochila = _arredondar_ch(media_ch)
    else:
        resultado.capacidade_mochila = 0

    # ── 3. Afinidade por área ────────────────────────────────────────────────
    # Usa apenas APR com nota real (media não-nula) e área conhecida no currículo.
    # CUMP/DISP sem nota → ignorados (conforme decisão de projeto).

    notas_por_area: dict[str, list[float]] = {}

    for _, row in df_apr.iterrows():
        codigo = str(row["codigo"]).strip()
        nota   = row.get("media")

        # Ignora disciplinas sem nota
        if pd.isna(nota):
            continue

        area = area_map.get(codigo)

        # Disciplinas fora do currículo (optativas externas) não têm área mapeada
        if area is None:
            continue

        notas_por_area.setdefault(area, []).append(float(nota))

    resultado.notas_por_area = notas_por_area

    resultado.afinidade = {
        area: round(sum(notas) / len(notas) / 10.0, 4)
        for area, notas in notas_por_area.items()
    }

    return resultado


# ---------------------------------------------------------------------------
# Utilitário interno
# ---------------------------------------------------------------------------

def _arredondar_ch(valor: float) -> int:
    """
    Arredonda a média de CH para o múltiplo de 16 mais próximo.
    Disciplinas têm CH em múltiplos de 16 (32, 48, 64...),
    então a capacidade faz sentido nessa granularidade.

    Exemplos:
        124.8  →  128   (2 × 64)
        192.0  →  192   (3 × 64)
         96.0  →   96   (1.5 × 64)
    """
    return int(round(valor / 16) * 16)


# ---------------------------------------------------------------------------
# Ponto de entrada — demonstração
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    BASE = os.path.dirname(__file__)

    df_hist = pd.read_csv(os.path.join(BASE, "historico_CCO-3.csv"))
    df_curr = pd.read_csv(os.path.join(BASE, "curriculo_cco.csv"))

    aluno = processar_historico(df_hist, df_curr)

    # ── Resumo ───────────────────────────────────────────────────────────────
    print("=" * 60)
    print("HISTÓRICO PROCESSADO")
    print("=" * 60)

    print(f"\n{'Disciplinas aprovadas':.<35} {len(aluno.aprovadas)}")
    print(f"{'Capacidade da mochila':.<35} {aluno.capacidade_mochila} h")

    print("\n── CH aprovada por semestre ─────────────────────────────")
    for sem, ch in sorted(aluno.ch_por_semestre.items()):
        print(f"  {sem:<12}  {ch:>4} h")

    total = sum(aluno.ch_por_semestre.values())
    n     = len(aluno.ch_por_semestre)
    print(f"  {'Média':.<12}  {total/n:>7.1f} h  →  arredondado: {aluno.capacidade_mochila} h")

    print("\n── Afinidade por área (0 = nenhuma, 1 = máxima) ────────")
    for area, af in sorted(aluno.afinidade.items(), key=lambda x: -x[1]):
        notas = aluno.notas_por_area[area]
        barra = "█" * int(af * 20)
        print(f"  {area:<42}  {af:.3f}  {barra}")
        print(f"  {'':42}  notas: {[round(n, 1) for n in notas]}")

    print("\n── Conjunto de aprovadas ────────────────────────────────")
    print(f"  {sorted(aluno.aprovadas)}")