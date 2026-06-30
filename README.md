# 🎓 Sistema Inteligente de Recomendação de Matrícula

[![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Trabalho prático final desenvolvido para a disciplina **CMAC03 — Algoritmos em Grafos** (Prof. Rafael Frinhani) no curso de Ciência da Computação e Sistemas de Informação da **Universidade Federal de Itajubá (UNIFEI)**.

O sistema resolve o problema de otimização de matrícula acadêmica utilizando uma abordagem de modelagem em grafos baseada na metodologia **CRISP-NET**, tratando tanto a progressão pedagógica (pré-requisitos) quanto restrições físicas (choques de horários).

---

## 🧠 Modelagem em Grafos e Inteligência do Sistema

A arquitetura do motor de recomendação está dividida em duas camadas matemáticas de grafos:

### 1. O DAG Curricular ($G_d$)
A estrutura de disciplinas e pré-requisitos é modelada como um **Grafo Dirigido Acíclico** $G_d = (V_d, A_d)$. O sistema aplica o **Algoritmo de Kahn** para validação topológica e determinação das camadas de profundidade de cada matéria. 
A partir daí, calcula-se um **Score Pedagógico** para cada disciplina candidata usando uma busca em largura (BFS) ponderada pelo fator de destrancamento futuro e pelo tamanho do **Caminho Crítico** local.

### 2. O Grafo de Conflitos de Horários ($G_c$)  
As disciplinas elegíveis com seus respectivos scores tornam-se vértices em um grafo não-dirigido $G_c = (V_c, E_c, w)$. Uma aresta existe se duas matérias compartilham o mesmo slot de horário. O problema de selecionar a melhor matrícula sem choques de horário e respeitando o limite de Carga Horária (Mochila) é resolvido computando o **Conjunto Independente de Peso Máximo (MWIS)**.

* **Instâncias pequenas ($\le 20$ candidatas):** Resolução por Enumeração Exata ($O(2^n)$), garantindo otimalidade absoluta.
* **Instâncias grandes ($> 20$ candidatas):** Heurística Gulosa Ponderada pela densidade de score/CH ($O(n \log n)$).

---

## 📂 Estrutura do Repositório

.  
├── curriculo_CCO_HORARIOS.csv             # Grade curricular estruturada com horários (CCO)  
├── curriculo_SIN_HORARIOS.csv             # Grade curricular estruturada com horários (SIN)   
├── dag_cco.py                             # Construção do DAG e Ordenação Topológica (Kahn)   
├── filtro_disciplinas.py                  # Subsistema de validação de elegibilidade e co-requisitos   
├── main.py                                # Orquestrador central e interface do pipeline   
├── mwis.py                                # Algoritmo do Grafo de Conflitos (Exato / Guloso)   
├── parse_historico.py                     # Extrator Regex/Textual para PDFs de histórico do SIGAA  
├── read_historico.py                      # Processamento do perfil do aluno (CRA, CH, Afinidades)     
└── score.py                               # Inteligência Pedagógica (BFS + Caminho Crítico) 

---

## 🚀 Como Executar o Projeto

### Pré-requisitos
Certifique-se de ter o Python 3.12 ou superior instalado.

1. **Clone o repositório:**
   ```bash
    git clone https://github.com/JoaoPedroGarciaTorezan/Sistema-de-Recomendacao-de-Matriculas.git
    cd Sistema-de-Recomendacao-de-Matriculas
2. **Instale as dependências:**
    - `pandas >= 2.0.0`
    - `openpyxl >= 3.1.0`
    - `poppler-utils` (necessário para `pdftotext`)

    ### Como instalar a dependência do PDF (poppler-utils):
    * **Linux:** `sudo apt install poppler-utils` (ou `sudo pacman -S poppler` no Arch)
    * **macOS:** `brew install poppler`
    * **Windows:** Baixe os binários diretamente em [xpdfreader](https://www.xpdfreader.com/download.html) ou utilize o pacote oficial do [poppler-windows](https://github.com/oschwartz10612/poppler-windows)
3. **Execute o pipiline:**
    ```bash
    python main.py
    ```
    Siga as instruções no terminal informando o curso (CCO/SIN), o caminho do PDF do histórico e o semestre letivo desejado.  
    O sistema exportará um relatório detalhado chamado recomendacao_[CURSO]_[SEMESTRE].txt.

## 📄 Licença   
Este projeto está licenciado sob a licença [MIT](LICENSE). Consulte o arquivo [LICENSE](LICENSE) para obter mais detalhes.
