"""
Lê o histórico escolar (arquivo PDF) do aluno e extrai a tabela de
Componentes Curriculares Cursados/Cursando para um arquivo CSV.

Uso:
    python parse_historico.py <caminho_do_pdf> [saida.csv]

Exemplo:
    python parse_historico.py historico_CCO-2.pdf historico.csv
"""

import re
import sys
import csv
import pandas as pd
import subprocess
from pathlib import Path

# ── Configuração ──────────────────────────────────────────────────────────────

STATUS_VALIDOS = {
    "APR", "APRN", "REP", "REPF", "REPMF", "REPN", "REPNF",
    "MATR", "TRANC", "CANC", "DISP", "TRANS", "INCORP", "CUMP",
    "REC", "---"
}

# Padrão da linha de dados da disciplina:
# (semestre) (flag opcional: * ou e) (código) ... (h_aula) (CH) (turma) (freq) (nota_min) (media) (situacao)
# O pdftotext -layout alinha tudo em colunas fixas, então usamos regex posicional.
# Nota: semestre pode ser "--" em disciplinas de transferência (CUMP, DISP, TRANS).

LINHA_RE = re.compile(
    r'^\s*'
    r'(\d{4}\.\d|--)'       # grupo 1: semestre ex: 2022.1 ou -- (transferência)
    r'\s+'
    r'([*e&#@§%]\s+)?'      # grupo 2: flag opcional  ex: * ou e ou & ou #
    r'([A-Z0-9\-]{4,12})'   # grupo 3: código         ex: CTCO01
    r'\s+'
    r'(\d+|--)'             # grupo 4: hora_aula
    r'\s+'
    r'(\d+|0)'              # grupo 5: CH
    r'\s+'
    r'(\d+|--)'             # grupo 6: turma
    r'\s+'
    r'([\d,]+|--)'          # grupo 7: frequencia %
    r'\s+'
    r'([\d.]+|--)'          # grupo 8: nota_min
    r'\s+'
    r'([\d.]+|--|---)'      # grupo 9: media
    r'\s+'
    r'(APR|APRN|REP[MFN]*|REPNF|MATR|TRANC|CANC|DISP|TRANS|INCORP|CUMP|REC|---)'  # grupo 10: situacao
)

# Padrão para capturar o nome da disciplina (linha acima do código)
NOME_RE = re.compile(r'^\s{20,}([A-ZÁÉÍÓÚÃÕÇÀÂÊÎÔÛ][A-ZÁÉÍÓÚÃÕÇÀÂÊÎÔÛa-záéíóúãõçàâêîôû0-9 /\-–:,]+)\s*$')


def extrair_texto_pdf(caminho_pdf: str) -> list[str]:
    """Usa pdftotext -layout para preservar alinhamento das colunas."""
    resultado = subprocess.run(
        ["pdftotext", "-layout", caminho_pdf, "-"],
        capture_output=True, text=True, encoding="utf-8"
    )
    if resultado.returncode != 0:
        raise RuntimeError(f"pdftotext falhou: {resultado.stderr}")
    return resultado.stdout.splitlines()


def parse_historico(linhas: list[str]) -> list[dict]:
    """
    Percorre as linhas do PDF extraído e monta lista de registros.
    Estratégia:
      - Identifica linhas de dados pela regex LINHA_RE
      - Olha para as 5 linhas anteriores para encontrar o nome da disciplina
    """
    registros = []
    linhas_vistas = set()  # evita duplicatas exatas (mesmo semestre+código+situação)

    for i, linha in enumerate(linhas):
        m = LINHA_RE.search(linha)
        if not m:
            continue

        semestre   = m.group(1)
        flag       = (m.group(2) or "").strip()
        codigo     = m.group(3).strip()
        hora_aula  = m.group(4)
        ch         = m.group(5)
        turma      = m.group(6)
        freq       = m.group(7).replace(",", ".")
        nota_min   = m.group(8)
        media      = m.group(9)
        situacao   = m.group(10)

        # Ignora linha ENADE (código especial sem nota real)
        if codigo == "ENADE" and situacao == "---":
            continue

        # Converte "--" para vazio para facilitar pandas
        nota_min = "" if nota_min in ("--", "---") else nota_min
        media    = "" if media    in ("--", "---") else media
        freq     = "" if freq     == "--"          else freq

        # Busca nome da disciplina nas linhas anteriores
        nome = ""
        for j in range(i - 1, max(i - 8, -1), -1):
            m_nome = NOME_RE.match(linhas[j])
            if m_nome:
                candidato = m_nome.group(1).strip()
                # Filtra falsos positivos (cabeçalhos de página, etc.)
                if candidato not in {
                    "Componentes Curriculares Cursados/Cursando",
                    "Componente Curricular",
                    "Dados Pessoais",
                    "Dados do Vínculo do Discente",
                    "Legenda",
                }:
                    nome = candidato
                    break

        # Semestre "--" ocorre em disciplinas de transferência/aproveitamento (CUMP, DISP, TRANS)
        if semestre == "--":
            semestre = "TRANSFERENCIA"

        # Tipo: optativa, equivalente, eletiva, etc.
        tipo_flag = ""
        if "*" in flag:
            tipo_flag = "OPTATIVA"
        elif "e" in flag:
            tipo_flag = "EQUIVALENTE_OBRIGATORIO"
        elif "&" in flag:
            tipo_flag = "EQUIVALENTE_OPTATIVA"
        elif "#" in flag:
            tipo_flag = "ELETIVA"
        
        chave = (semestre, codigo, situacao)
        if chave in linhas_vistas:
            continue
        linhas_vistas.add(chave)

        registros.append({
            "semestre":   semestre,
            "codigo":     codigo,
            "nome":       nome,
            "tipo_flag":  tipo_flag,
            "ch":         ch,
            "turma":      turma,
            "frequencia": freq,
            "nota_min":   nota_min,
            "media":      media,
            "situacao":   situacao,
        })

    return registros


def salvar_csv(registros: list[dict], caminho_saida: str):
    campos = ["semestre", "codigo", "nome", "tipo_flag",
              "ch", "turma", "frequencia", "nota_min", "media", "situacao"]
    with open(caminho_saida, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        writer.writerows(registros)
    print(f"✓ CSV salvo em: {caminho_saida}  ({len(registros)} registros)")

def parsear_para_dataframe(caminho_pdf: str) -> pd.DataFrame:
    """
    Lê o PDF do histórico e retorna um DataFrame diretamente em memória.
    Não salva nenhum arquivo em disco.
    """
    linhas = extrair_texto_pdf(caminho_pdf)
    registros = parse_historico(linhas)
    return pd.DataFrame(registros)


def main():
    if len(sys.argv) < 2:
        print("Uso: python parse_historico.py <historico.pdf> [saida.csv]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    csv_path = sys.argv[2] if len(sys.argv) > 2 else Path(pdf_path).stem + ".csv"

    print(f"Lendo: {pdf_path}")
    linhas = extrair_texto_pdf(pdf_path)
    print(f"  {len(linhas)} linhas extraídas do PDF")

    registros = parse_historico(linhas)
    print(f"  {len(registros)} componentes encontrados")

    salvar_csv(registros, csv_path)

    '''
    # Preview no terminal
    print("\nPreview dos primeiros registros:")
    print(f"{'semestre':<10} {'codigo':<12} {'situacao':<8} {'media':<6} {'nome'}")
    print("-" * 75)
    for r in registros[:10]:
        print(f"{r['semestre']:<10} {r['codigo']:<12} {r['situacao']:<8} {r['media']:<6} {r['nome']}")
    if len(registros) > 10:
        print(f"  ... e mais {len(registros) - 10} registros")
    '''

if __name__ == "__main__":
    main()