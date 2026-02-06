# RAG for Public Tenders — Semantic Search with Evidence (Streamlit + OpenAI)

## Part 1 — Plain-English overview (what this solves)

### What is the purpose of this app?
This application was built to **avoid rework** when analyzing tender/bidding documents that have already been processed in the past.

When a new tender is being prepared—and a similar tender has happened before—it’s common for the team to re-read and re-check:
- Terms of Reference (ToR)
- RFPs / tender notices
- technical annexes
- requirements, SLAs, timelines, training hours, architecture, modules, deliverables, etc.

The issue is that a full read-through is slow and repetitive—while the previous tender usually already contains most of what you need.

**This app solves that by enabling you to:**
- ask questions in natural language (chat-style)
- get an answer **grounded in the documents**
- see the **exact excerpts** found (with context)
- download the source file behind each piece of evidence to validate quickly

In other words: you move from “read 60 files” to “ask and confirm”.

---

### How to use (quick view)
1. Choose which knowledge base to query:
   - **NEW Tender** (folder `doc2` / Vector Store 2)
   - **OLD Tender** (folder `docs` / Vector Store 1)
2. Type your question.
3. Adjust Top-K (number of excerpts returned).
4. Review:
   - a **semantic digest** of what was found
   - a **short answer**
   - the **excerpts/occurrences** with contextual explanation
5. Download the file for each occurrence to confirm.

---

## Part 2 — Technical explanation (how it really works)

### What is RAG?
RAG = **Retrieval-Augmented Generation**.

The idea is straightforward:
1) **Retrieve** relevant excerpts from the documents  
2) **Generate** an answer using those excerpts as the grounding context

This reduces hallucination and increases trust, because the response is **anchored in evidence**.

---

### Where do embeddings fit in?
Embeddings are what enables semantic search:
- a model transforms text into a numeric vector (a list of numbers)
- texts with similar meaning end up “close” to each other in vector space
- search returns the chunks that are “closest” to your question

⚠️ In this project, **you don’t generate embeddings manually in the code**.
That is handled by the OpenAI **Vector Store** during ingestion:
- extracts text from PDF/PPT/DOC
- splits it into chunks
- creates embeddings
- indexes everything for retrieval

---

### App architecture
- **Frontend**: Streamlit (form + expander per occurrence)
- **Retrieval**: OpenAI `file_search` tool targeting a **Vector Store**
- **Two knowledge bases**:
  - `VECTOR_STORE_ID` (OLD tender)
  - `VECTOR_STORE_ID2` (NEW tender)
- **Transparency features**:
  - configurable Top-K (up to 40)
  - semantic digest across returned chunks
  - contextual explanation per occurrence
  - file download for each retrieved source

---

### Execution flow (step by step)
1. User enters a question
2. The app:
   - generates query variants (PT/EN/ES)
   - adds recall variants (e.g., `hour/hours/hr/hrs/hora/horas`)
3. The app calls OpenAI with:
   - `file_search` + `vector_store_ids=[selected_store]` + `max_num_results=TopK`
4. OpenAI returns a list of results:
   - filename + excerpt + score (similarity)
5. The app displays:
   - semantic digest (summary of findings)
   - short answer
   - list of occurrences with:
     - excerpt
     - contextual explanation
     - download link to the corresponding local file

---

### Environment variables (required)
- `OPENAI_API_KEY`
- `VECTOR_STORE_ID` (old tender)
- `VECTOR_STORE_ID2` (new tender)
- `APP_USER` (app login)
- `APP_PASS` (app password)

**Security notes**
- Do not commit `.env` to GitHub
- Store `OPENAI_API_KEY` only as:
  - a server-side `.env`, and/or
  - GitHub Secrets (for deployment)
- Rotate the key if it has been exposed

