"""
main.py
=======
Pipeline completo do sistema de recomendação de matrícula.

Fluxo:
    1. Usuário informa o curso (CCO ou SIN)
    2. Usuário informa o caminho do PDF do histórico
    3. Usuário informa o semestre atual (ex: 2025.1)
    4. Sistema executa o pipeline e gera recomendacao.txt

Módulos utilizados:
    parse_historico  → extrai histórico do PDF para DataFrame
    dag_cco          → constrói o DAG + Kahn
    read_historico   → processa histórico (aprovadas, capacidade, afinidade)
    filtro_disciplinas → filtra disciplinas candidatas
    score            → calcula score de cada candidata
    mwis             → seleciona conjunto final (MWIS + restrição de CH)
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from parse_historico import parsear_para_dataframe
from dag_cco import construir_dag
from read_historico import processar_historico
from filtro_disciplinas import filtrar_disponiveis
from score import calcular_scores, calcular_scores_detalhados
from mwis import resolver_mwis


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

CURSOS = {
    "CCO": {
        "arquivo": "curriculo_CCO_HORARIOS.csv",
        "nome":    "Ciência da Computação",
    },
    "SIN": {
        "arquivo": "curriculo_SIN_HORARIOS.csv",
        "nome":    "Sistemas de Informação",
    },
}

SEMESTRE_RE = re.compile(r"^\d{4}\.[12]$")


# ---------------------------------------------------------------------------
# Funções de input com validação
# ---------------------------------------------------------------------------

def _input_curso() -> tuple[str, str, str]:
    """
    Solicita o curso ao usuário.
    Retorna (sigla, nome_completo, caminho_csv).
    """
    print("\nCurso disponíveis: CCO (Ciência da Computação) | SIN (Sistemas de Informação)")
    while True:
        resposta = input("Informe o curso [CCO/SIN]: ").strip().upper()
        if resposta in CURSOS:
            info = CURSOS[resposta]
            caminho = Path(__file__).parent / info["arquivo"]
            if not caminho.exists():
                print(f"  [ERRO] Arquivo '{info['arquivo']}' não encontrado no diretório do programa.")
                print(f"         Verifique se o arquivo está em: {caminho.parent}")
                continue
            return resposta, info["nome"], str(caminho)
        print("  [ERRO] Opção inválida. Digite CCO ou SIN.")


def _input_pdf() -> str:
    """
    Solicita o caminho do PDF do histórico.
    Retorna o caminho validado.
    """
    print()
    while True:
        caminho = input("Informe o caminho do PDF do histórico: ").strip().strip('"')
        if not caminho:
            print("  [ERRO] Caminho não pode ser vazio.")
            continue
        p = Path(caminho)
        if not p.exists():
            print(f"  [ERRO] Arquivo não encontrado: {caminho}")
            continue
        if p.suffix.lower() != ".pdf":
            print("  [ERRO] O arquivo deve ser um PDF (.pdf).")
            continue
        return str(p)


def _input_semestre() -> str:
    """
    Solicita o semestre atual no formato AAAA.S.
    Retorna string validada (ex: '2025.1').
    """
    print()
    while True:
        semestre = input("Informe o semestre atual [ex: 2025.1]: ").strip()
        if SEMESTRE_RE.match(semestre):
            return semestre
        print("  [ERRO] Formato inválido. Use AAAA.1 ou AAAA.2 (ex: 2025.1).")


# ---------------------------------------------------------------------------
# Geração do arquivo de saída
# ---------------------------------------------------------------------------

def _gerar_txt(
    resultado,
    scores_detalhados,
    semestre: str,
    nome_curso: str,
    caminho_saida: str,
) -> None:
    """
    Gera o arquivo recomendacao.txt com o resultado final.
    """
    linhas: list[str] = []
    sep  = "=" * 62
    sep2 = "-" * 62

    linhas.append(sep)
    linhas.append("  SISTEMA DE RECOMENDAÇÃO DE MATRÍCULA")
    linhas.append(f"  Curso   : {nome_curso}")
    linhas.append(f"  Semestre: {semestre}")
    linhas.append(f"  Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    linhas.append(sep)

    if not resultado.selecionadas:
        linhas.append("\nNenhuma disciplina disponível para recomendação.")
    else:
        linhas.append("\nDisciplinas recomendadas:\n")

        for rank, d in enumerate(resultado.selecionadas, start=1):
            score_val = resultado.scores.get(d.codigo, 0.0)
            det = scores_detalhados.get(d.codigo)

            linhas.append(f"  {rank}. {d.codigo:<10} {d.nome}")
            linhas.append(
                f"     Área   : {d.area}"
            )
            linhas.append(
                f"     CH     : {d.ch}h  |  "
                f"Tipo: {d.tipo}  |  "
                f"Score: {score_val:.4f}"
            )

            # Detalhamento do score
            if det:
                linhas.append(
                    f"     Score  : bfs={det.score_bfs:.4f}  "
                    f"base={det.score_base:.4f}  "
                    f"afinidade={det.afinidade:.3f}  "
                    f"f_oferta={det.f_oferta:.1f}  "
                    f"f_critico={det.f_critico:.3f} "
                    f"(caminho={det.caminho_critico})"
                )

            # Horários
            slots = resultado.horarios.get(d.codigo, [])
            if slots:
                linhas.append(f"     Horários: {' | '.join(slots)}")
            else:
                linhas.append("     Horários: não informados")

            linhas.append("")

    linhas.append(sep2)
    linhas.append(f"  Capacidade utilizada : {resultado.ch_total}h / {resultado.capacidade}h")
    linhas.append(f"  CH disponível        : {resultado.ch_disponivel}h")
    linhas.append(f"  Score total          : {resultado.score_total:.4f}")
    linhas.append(f"  Disciplinas          : {len(resultado.selecionadas)}")
    linhas.append(f"  Estratégia MWIS      : {resultado.estrategia}")
    linhas.append(f"  Conflitos no grafo   : {resultado.n_conflitos_grafo} aresta(s)")
    if resultado.selecionadas:
        linhas.append(
            "  Conflitos resolvidos : nenhum par selecionado tem horário sobreposto ✓"
        )
    linhas.append(sep)

    conteudo = "\n".join(linhas)

    with open(caminho_saida, "w", encoding="utf-8") as f:
        f.write(conteudo)

    print(conteudo)
    print(f"\n[OK] Resultado salvo em: {caminho_saida}")


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 62)
    print("  SISTEMA DE RECOMENDAÇÃO DE MATRÍCULA — UNIFEI")
    print("=" * 62)

    # ── 1. Inputs do usuário ─────────────────────────────────────────────────
    sigla_curso, nome_curso, caminho_csv = _input_curso()
    caminho_pdf = _input_pdf()
    semestre    = _input_semestre()

    print()
    print("─" * 62)
    print("  Processando...")
    print("─" * 62)

    # ── 2. Leitura do currículo ───────────────────────────────────────────────
    try:
        df_curriculo = pd.read_csv(caminho_csv)
        print(f"[OK] Currículo carregado: {len(df_curriculo)} disciplinas")
    except Exception as e:
        print(f"[ERRO] Falha ao ler currículo: {e}")
        sys.exit(1)

    # ── 3. Parse do histórico (PDF → DataFrame) ───────────────────────────────
    try:
        df_historico = parsear_para_dataframe(caminho_pdf)
        print(f"[OK] Histórico lido: {len(df_historico)} registros extraídos do PDF")
    except Exception as e:
        print(f"[ERRO] Falha ao processar PDF: {e}")
        sys.exit(1)

    # ── 4. Construção do DAG + Kahn ───────────────────────────────────────────
    try:
        dag = construir_dag(df_curriculo)
        print(f"[OK] DAG construído: {len(dag.vertices)} vértices")
    except Exception as e:
        print(f"[ERRO] Falha ao construir DAG: {e}")
        sys.exit(1)

    # ── 5. Processamento do histórico ─────────────────────────────────────────
    try:
        aluno = processar_historico(df_historico, df_curriculo)
        print(
            f"[OK] Histórico processado: "
            f"{len(aluno.aprovadas)} disciplinas aprovadas | "
            f"capacidade: {aluno.capacidade_mochila}h"
        )
    except Exception as e:
        print(f"[ERRO] Falha ao processar histórico: {e}")
        sys.exit(1)

    # ── 6. Filtragem de candidatas ────────────────────────────────────────────
    try:
        candidatas = filtrar_disponiveis(dag, aluno, semestre)
        print(f"[OK] Candidatas filtradas: {len(candidatas)} disciplinas disponíveis")
    except Exception as e:
        print(f"[ERRO] Falha na filtragem: {e}")
        sys.exit(1)

    if not candidatas:
        print("\n[AVISO] Nenhuma disciplina disponível para matrícula neste semestre.")
        sys.exit(0)

    # ── 7. Cálculo do score ───────────────────────────────────────────────────
    try:
        scores_detalhados = calcular_scores_detalhados(dag, aluno, candidatas)
        scores            = {cod: s.score_final for cod, s in scores_detalhados.items()}
        print(f"[OK] Scores calculados para {len(scores)} candidatas")
    except Exception as e:
        print(f"[ERRO] Falha no cálculo de scores: {e}")
        sys.exit(1)

    # ── 8. MWIS — seleção final ───────────────────────────────────────────────
    try:
        resultado = resolver_mwis(
            candidatas         = candidatas,
            scores             = scores,
            capacidade         = aluno.capacidade_mochila,
            df_curriculo       = df_curriculo,
        )
        print(
            f"[OK] MWIS concluído: "
            f"{len(resultado.selecionadas)} disciplinas selecionadas | "
            f"estratégia: {resultado.estrategia}"
        )
    except Exception as e:
        print(f"[ERRO] Falha no MWIS: {e}")
        sys.exit(1)

    # ── 9. Geração do arquivo de saída ────────────────────────────────────────
    print()
    print("─" * 62)

    caminho_saida = Path(__file__).parent / f"recomendacao_{sigla_curso}_{semestre}.txt"

    try:
        _gerar_txt(
            resultado         = resultado,
            scores_detalhados = scores_detalhados,
            semestre          = semestre,
            nome_curso        = nome_curso,
            caminho_saida     = str(caminho_saida),
        )
    except Exception as e:
        print(f"[ERRO] Falha ao gerar arquivo de saída: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()