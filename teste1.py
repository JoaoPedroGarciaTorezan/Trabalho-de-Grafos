import networkx as nx

grafo_curricular = {

    # ===== 1º SEMESTRE =====
    "MATA01 - Cálculo A": [
        "MATA02 - Cálculo B",
        "CMAC04 - Modelagem Computacional"
    ],

    "XMCA01 - Matemática Discreta": [
        "CMAC03 - Algoritmos em Grafos"
    ],

    "XDES01 - Fundamentos de Programação": [
        "CTC001 - Algoritmos e Estruturas de Dados I"
    ],

    "CRSC03 - Arquitetura de Computadores I": [
        "CRSC04 - Arquitetura de Computadores II"
    ],


    # ===== 2º SEMESTRE =====
    "MATA02 - Cálculo B": [
        "XMCA02 - Métodos Matemáticos para Análise de Dados"
    ],

    "CTC001 - Algoritmos e Estruturas de Dados I": [
        "CTC002 - Algoritmos e Estruturas de Dados II",
        "XDES02 - Programação Orientada a Objetos"
    ],

    "CRSC04 - Arquitetura de Computadores II": [
        "CRSC02 - Sistemas Operacionais"
    ],


    # ===== 3º SEMESTRE =====
    "CTC002 - Algoritmos e Estruturas de Dados II": [
        "CTC004 - Projeto e Análise de Algoritmos",
        "CMAC03 - Algoritmos em Grafos"
    ],

    "XDES02 - Programação Orientada a Objetos": [
        "XDES03 - Programação Web",
        "CTC003 - Análise e Projeto Orientados a Objetos"
    ],

    "CRSC02 - Sistemas Operacionais": [
        "XCSC01 - Redes de Computadores"
    ],


    # ===== 4º SEMESTRE =====
    "CTC004 - Projeto e Análise de Algoritmos": [
        "CTC005 - Teoria da Computação"
    ],

    "XDES03 - Programação Web": [
        "XAHC02 - Interação Humano-Computador"
    ],

    "XCSC01 - Redes de Computadores": [
        "XCSC06 - Computação em Nuvem",
        "XCSC08 - Programação Paralela"
    ],


    # ===== 5º SEMESTRE =====
    "CTC005 - Teoria da Computação": [
        "CTC006 - Compiladores"
    ],

    "XPAD01 - Banco de Dados I": [
        "XPAD02 - Banco de Dados II",
        "XPAD04 - Banco de Dados NoSQL"
    ],

    "XMCO01 - Inteligência Artificial": [
        "XMCO09 - Ciência de Redes"
    ],


    # ===== 6º SEMESTRE =====
    "CTC006 - Compiladores": [
        "TCC1"
    ],

    "XAHC02 - Interação Humano-Computador": [
        "XAHC03 - Metodologia Científica"
    ],


    # ===== 7º SEMESTRE =====
    "TCC1": [
        "TCC2"
    ],


    # ===== OPTATIVAS =====
    "Optativa 1": [],
    "Optativa 2": [],
    "Optativa 3": [],
    "Optativa 4": [],
    "Optativa 5": [],
    "Optativa 6": [],
    "Optativa 7": [],
    "Optativa 8": [],
    "Optativa 9": [],
    "Optativa 10": []
}

# Ordenação teste
G = nx.DiGraph(grafo_curricular)

ordem = list(nx.topological_sort(G))

for disciplina in ordem:
    print(disciplina)