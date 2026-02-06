# RAG Licitações — Busca Semântica com Evidências (Streamlit + OpenAI)

## Parte 1 — Explicação “humana” (o que isso resolve)

### Qual é o propósito da aplicação?
Esta aplicação foi criada para **evitar retrabalho** na análise de documentos de licitações que já foram realizadas anteriormente.

Quando uma nova licitação vai ser preparada e esta licitação já ocorreu no passado para objetos similares a serem licitados, é comum que a equipe precise revisar novamente:
- Termos de Referência (TR)
- RFPs / editais
- anexos técnicos
- requisitos, SLAs, prazos, “horas de treinamento”, arquitetura, módulos, entregas, etc.

O problema é que essa leitura completa é demorada e repetitiva — e a licitação anterior normalmente já contém a maior parte do que você precisa.

**O app resolve isso permitindo que você:**
- faça perguntas em linguagem natural (como num chat)
- receba uma resposta **baseada nos documentos**
- veja os **trechos exatos** encontrados (com contexto)
- baixe o arquivo usado em cada evidência, para validar rapidamente

Em outras palavras: você sai do modo “ler 60 arquivos” para o modo “perguntar e confirmar”.

---

### Como usar (visão rápida)
1. Escolha qual base você quer consultar:
   - **Licitação NOVA** (pasta `doc2` / Vector Store 2)
   - **Licitação ANTIGA** (pasta `docs` / Vector Store 1)
2. Digite sua pergunta.
3. Ajuste o Top-K (quantidade de trechos retornados).
4. Leia:
   - um **compilado semântico** do que foi encontrado
   - a **resposta curta**
   - os **trechos/ocorrências** com explicação contextual
5. Baixe o arquivo de cada ocorrência para conferir.

---

## Parte 2 — Explicação técnica (como funciona de verdade)

### O que é RAG?
RAG = **Retrieval-Augmented Generation**.

A ideia é simples:
1) **Recuperar (Retrieval)** trechos relevantes dos documentos  
2) **Gerar (Generation)** uma resposta usando esses trechos como base

Isso reduz alucinação e aumenta confiança, porque a resposta vem **ancorada em evidências**.

---

### Onde entram os embeddings?
Embeddings são o mecanismo que permite busca semântica:
- um modelo transforma texto em um vetor numérico (lista de números)
- textos com significado parecido ficam “perto” nesse espaço vetorial
- a busca retorna os trechos “mais próximos” da sua pergunta

⚠️ No nosso caso, **você não gera embeddings manualmente no código**.
Quem faz isso é o **Vector Store** do OpenAI durante o processo de ingestão:
- extrai texto de PDF/PPT/DOC
- divide em “chunks”
- cria embeddings
- indexa para busca

---

### Arquitetura do app
- **Frontend**: Streamlit (formulário + expander por ocorrência)
- **Busca**: `file_search` do OpenAI apontando para um **Vector Store**
- **Duas bases**:
  - `VECTOR_STORE_ID` (Licitação ANTIGA)
  - `VECTOR_STORE_ID2` (Licitação NOVA)
- **Transparência**:
  - Top-K configurável (até 40)
  - Compilado semântico do conjunto de trechos retornados
  - Explicação contextual por ocorrência
  - Download do arquivo considerado em cada ocorrência

---

### Fluxo de execução (passo a passo)
1. Usuário digita a pergunta
2. O app:
   - gera variantes da consulta (PT/EN/ES)
   - adiciona variantes para recall (ex.: `hour/hours/hr/hrs/hora/horas`)
3. O app chama o OpenAI com ferramenta:
   - `file_search` + `vector_store_ids=[store_escolhido]` + `max_num_results=TopK`
4. O OpenAI retorna uma lista de resultados:
   - filename + trecho + score (similaridade)
5. O app exibe:
   - compilado semântico (resumo dos achados)
   - resposta curta
   - lista de ocorrências com:
     - trecho
     - explicação contextual
     - download do arquivo local correspondente

---

## Segurança e boas práticas
- Não commite `.env` no GitHub
- Guarde `OPENAI_API_KEY` apenas como:
  - `.env` no servidor, e/ou
  - GitHub Secrets (para deploy)
- Rotacione a chave se ela já foi exposta

---

## Roadmap (opcional)
- Deploy automatizado via GitHub Actions (CI/CD)
- Ingestão automatizada (workflow manual `workflow_dispatch`)
- Links servidos via Nginx (URL real) para “abrir” arquivos no browser sem data-URL
- Normalização de nomes (acentos/case) para mapear filename ↔ arquivo local com mais tolerância
