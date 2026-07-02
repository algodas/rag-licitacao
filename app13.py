import os
import json
import glob
import hashlib
import hmac
import re
import streamlit as st
from openai import OpenAI
from dotenv import load_dotenv

# ============================================================
# ENV (.env no mesmo diretório do app)
# ============================================================
HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(HERE, ".env"))

# ============================================================
# CONFIG UI
# ============================================================
st.set_page_config(page_title="Consulta Documental (RAG)", layout="wide")

# ============================================================
# LOGIN SIMPLES (fixo)
# ============================================================
DEFAULT_USER = os.getenv("APP_USER")
DEFAULT_PASS = os.getenv("APP_PASS")

if "auth_ok" not in st.session_state:
    st.session_state.auth_ok = False



def login_ui():
    st.title("🔐 Acesso restrito")
    c1, c2 = st.columns([1, 1])
    with c1:
        u = st.text_input("Usuário", value="")
    with c2:
        p = st.text_input("Senha", value="", type="password", placeholder="••••••••••")
    if st.button("Entrar", type="primary"):
        user_ok = hmac.compare_digest(u, DEFAULT_USER or "")
        pass_ok = hmac.compare_digest(p, DEFAULT_PASS or "")
        if user_ok and pass_ok:
            st.session_state.auth_ok = True
            st.rerun()
        else:
            st.error("Usuário ou senha inválidos.")


if not st.session_state.auth_ok:
    login_ui()
    st.stop()

# ============================================================
# HEADER
# ============================================================
st.title("📚 Consulta rápida na base documental")
st.caption(
    "Resposta + compilado semântico + evidências + explicação por ocorrência + download do arquivo considerado."
)

# ============================================================
# KEYS
# ============================================================
api_key = os.getenv("OPENAI_API_KEY")
vs_old = os.getenv("VECTOR_STORE_ID")   # Licitação ANTIGA
vs_new = os.getenv("VECTOR_STORE_ID2")  # Licitação NOVA

if not api_key or not vs_old or not vs_new:
    st.error("Defina OPENAI_API_KEY, VECTOR_STORE_ID e VECTOR_STORE_ID2 no .env.")
    st.stop()

client = OpenAI(api_key=api_key)


def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# Cache de explicações por snippet
if "snippet_explain_cache" not in st.session_state:
    st.session_state.snippet_explain_cache = {}

# Cache do compilado semântico
if "semantic_comp_cache" not in st.session_state:
    st.session_state.semantic_comp_cache = {}

# ============================================================
# MULTILINGUAL QUERY EXPANSION
# ============================================================
def expand_query_multilingual(question: str) -> dict:
    try:
        r = client.responses.create(
            model="gpt-4.1",
            input=(
                "Gere variações de busca (PT/EN/ES) e palavras-chave para a pergunta abaixo.\n"
                "Retorne APENAS JSON no formato:\n"
                "{\"pt\":\"...\",\"en\":\"...\",\"es\":\"...\",\"keywords\":[\"...\"],\"acronyms\":[\"...\"]}\n\n"
                f"Pergunta: {question}"
            ),
        )
        txt = _get(r, "output_text", "") or ""
        return json.loads(txt)
    except Exception:
        return {"pt": question, "en": question, "es": question, "keywords": [], "acronyms": []}


# ============================================================
# VARIANTES DE KEYWORDS + equivalências fortes para tempo
# ============================================================
def keyword_variants_set(q: str) -> set[str]:
    """
    Gera conjunto de variantes (singular/plural, abreviações e PT).
    """
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9_]+", q)
    variants: set[str] = set()

    for t in tokens:
        if len(t) < 3:
            continue

        variants.update({t, t.lower(), t.upper()})
        tl = t.lower()

        # singular/plural simples (EN)
        if tl.endswith("s") and len(t) > 3:
            variants.add(t[:-1])
            variants.add(t[:-1].lower())
            variants.add(t[:-1].upper())
        else:
            variants.add(t + "s")
            variants.add((t + "s").lower())
            variants.add((t + "s").upper())

        # equivalências fortes para tempo
        if tl in {"hour", "hours", "hr", "hrs"}:
            variants.update({
                "hour", "hours", "hr", "hrs", "h",
                "hora", "horas",
                "carga horária", "carga horaria",
                "tempo", "duração", "duracao",
                "minutes", "minute", "min", "mins", "minuto", "minutos"
            })

    return variants


def keyword_variants_line(q: str) -> str:
    """
    Linha com variantes (para orientar o modelo a buscar equivalentes).
    """
    return " | ".join(sorted(keyword_variants_set(q)))


def equivalence_hint(q: str) -> str:
    """
    Hint explícito para o modelo NÃO diferenciar singular/plural em tempo.
    """
    ql = q.lower()
    if any(x in ql for x in ["hour", "hours", "hr", "hrs", "hora", "horas"]):
        return (
            "Equivalências a considerar como SINÔNIMOS (não diferenciar): "
            "hour == hours == hr == hrs == h == hora == horas. "
            "Também considerar termos relacionados: carga horária/carga horaria, duration/duração, tempo, minutes/minutos."
        )
    return ""


# ============================================================
# EXPLICAÇÃO CONTEXTUAL POR OCORRÊNCIA
# ============================================================
def explain_snippet(question: str, filename: str, snippet: str) -> str:
    h = hashlib.sha256((question + "||" + filename + "||" + (snippet or "")).encode("utf-8")).hexdigest()
    if h in st.session_state.snippet_explain_cache:
        return st.session_state.snippet_explain_cache[h]

    if not snippet or len(snippet.strip()) < 20:
        txt = "Trecho curto/indisponível para contextualizar."
        st.session_state.snippet_explain_cache[h] = txt
        return txt

    resp = client.responses.create(
        model="gpt-4.1",
        input=(
            "Você é um analista técnico de licitações.\n"
            "Explique de forma curta e prática como este trecho responde/ajuda a responder a pergunta.\n"
            "Regras:\n"
            "- 2 a 6 bullet points\n"
            "- Não invente nada além do trecho\n"
            "- Se o trecho não responder, diga o que falta procurar.\n\n"
            f"Pergunta: {question}\n"
            f"Arquivo: {filename}\n"
            f"Trecho:\n{snippet}\n"
        )
    )
    out = _get(resp, "output_text") or ""
    if not out.strip():
        out = "Sem explicação retornada."
    st.session_state.snippet_explain_cache[h] = out
    return out


# ============================================================
# COMPILADO SEMÂNTICO DO QUE FOI ENCONTRADO
# ============================================================
def semantic_compilation(question: str, results: list) -> str:
    parts = [question]
    for r in results[:40]:
        fn = _get(r, "filename") or _get(_get(r, "file"), "filename") or ""
        tx = _get(r, "text") or _get(r, "content") or ""
        parts.append(fn + "::" + tx[:800])

    cache_key = hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()
    if cache_key in st.session_state.semantic_comp_cache:
        return st.session_state.semantic_comp_cache[cache_key]

    blocks = []
    for i, r in enumerate(results[:40], start=1):
        fn = _get(r, "filename")
        if not fn:
            fobj = _get(r, "file")
            fn = _get(fobj, "filename", "arquivo")
        tx = _get(r, "text") or _get(r, "content") or ""
        tx = (tx or "").strip()
        if not tx:
            continue
        blocks.append(f"[{i}] Arquivo: {fn}\nTrecho: {tx[:900]}\n")

    joined = "\n".join(blocks)[:32000]
    if not joined.strip():
        txt = "Não houve trechos suficientes para compilar um resumo semântico."
        st.session_state.semantic_comp_cache[cache_key] = txt
        return txt

    resp = client.responses.create(
        model="gpt-4.1",
        input=(
            "Você é um assistente de RAG. Sua tarefa aqui NÃO é responder a pergunta.\n"
            "Você deve produzir um *COMPILADO SEMÂNTICO* do que apareceu nos trechos retornados.\n\n"
            "Regras:\n"
            "- Seja objetivo.\n"
            "- Agrupe por temas (bullets curtos).\n"
            "- Não invente; só descreva o que aparece.\n"
            "- Termine com 1 frase sugerindo ao usuário validar navegando pelos trechos abaixo.\n\n"
            f"Pergunta: {question}\n\n"
            f"Trechos retornados:\n{joined}"
        )
    )
    out = _get(resp, "output_text") or ""
    if not out.strip():
        out = "Sem compilado semântico retornado."
    st.session_state.semantic_comp_cache[cache_key] = out
    return out


# ============================================================
# LOCAL FILE FINDER (match exato)
# ============================================================
def find_local_file(filename: str, roots: list[str]) -> str | None:
    if not filename:
        return None
    target = os.path.basename(filename.strip()).lower()
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for p in glob.glob(os.path.join(root, "**", "*"), recursive=True):
            if os.path.isfile(p) and os.path.basename(p).strip().lower() == target:
                return p
    return None


# ============================================================
# MIME
# ============================================================
def guess_mime(filename: str) -> str:
    ext = (os.path.splitext(filename)[1] or "").lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext == ".png":
        return "image/png"
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".pptx":
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if ext == ".ppt":
        return "application/vnd.ms-powerpoint"
    if ext == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if ext == ".doc":
        return "application/msword"
    return "application/octet-stream"


# ============================================================
# FORM
# ============================================================
with st.form("search_form", clear_on_submit=False):
    colA, colB, colC = st.columns([2.2, 1.6, 1])

    with colA:
        question = st.text_input(
            "Sua pergunta",
            placeholder="Ex.: Quais são os tempos/SLAs exigidos e onde aparecem?"
        )

    with colB:
        base = st.selectbox(
            "Base documental",
            options=[
                "Licitação NOVA (doc2 → VECTOR_STORE_ID2)",
                "Licitação ANTIGA (docs → VECTOR_STORE_ID)"
            ],
            index=0
        )

    with colC:
        # ✅ até 40
        max_results = st.slider("Top-k", 2, 40, 30)

    status_slot = st.empty()
    submitted = st.form_submit_button("Buscar")  # Enter envia

# ============================================================
# MAP BASE -> VECTOR STORE + PASTAS LOCAIS
# ============================================================
is_new = base.startswith("Licitação NOVA")
selected_vs = vs_new if is_new else vs_old
local_roots = [os.path.join(HERE, "doc2")] if is_new else [os.path.join(HERE, "docs")]

# ============================================================
# SEARCH
# ============================================================
if submitted and question.strip():
    with status_slot:
        with st.spinner("🔎 Buscando na base documental..."):
            exp = expand_query_multilingual(question)
            variants_line = keyword_variants_line(question)
            eq_hint = equivalence_hint(question)

            expanded_block = (
                f"Pergunta original: {question}\n"
                f"PT: {exp.get('pt','')}\n"
                f"EN: {exp.get('en','')}\n"
                f"ES: {exp.get('es','')}\n"
                f"Keywords: {', '.join(exp.get('keywords', []))}\n"
                f"Acronyms: {', '.join(exp.get('acronyms', []))}\n"
                f"Termos/variantes para maximizar recall: {variants_line}\n"
                f"{eq_hint}\n"
            )

            response = client.responses.create(
                model="gpt-4.1",
                input=(
                    "Responda usando APENAS os documentos disponíveis via file_search.\n"
                    "IMPORTANTE: não diferencie singular/plural quando for claramente a mesma palavra (ex.: hour/hours).\n"
                    "Use variações de idioma e equivalências para maximizar recall.\n"
                    "Formato obrigatório:\n"
                    "1) Resposta (curta e objetiva)\n"
                    "2) Evidências usadas (citações/trechos)\n"
                    "3) Tópicos relacionados (outros documentos/trechos relevantes)\n"
                    "Se não houver evidência suficiente, diga que não encontrou nos documentos.\n\n"
                    f"Base selecionada: {base}\n"
                    f"{expanded_block}\n"
                ),
                tools=[{
                    "type": "file_search",
                    "vector_store_ids": [selected_vs],
                    "max_num_results": max_results
                }],
                include=["file_search_call.results"]
            )

    status_slot.empty()

    # ===== Extrai resultados do file_search =====
    results = []
    for item in _get(response, "output", []) or []:
        if _get(item, "type") == "file_search_call":
            results = _get(item, "results") or _get(item, "search_results") or []
            break

    # ===== 1) ANSWER TEXT =====
    answer_text = _get(response, "output_text")
    if not answer_text:
        answer_text = ""
        for item in _get(response, "output", []) or []:
            if _get(item, "type") == "message":
                for part in _get(item, "content", []) or []:
                    if _get(part, "type") == "output_text":
                        answer_text += _get(part, "text", "")

    # ===== Compilado semântico =====
    st.subheader("🧾 Compilado semântico do que apareceu nos trechos")
    if results:
        with st.spinner("Compilando semanticamente os trechos retornados..."):
            st.write(semantic_compilation(question, results))
    else:
        st.info("Nenhum trecho retornado para compilar. Tente aumentar o top-k ou variar o termo.")

    st.subheader("✅ Resposta")
    st.write(answer_text or "Sem texto retornado.")

    # ===== Ocorrências + download =====
    st.subheader("📌 Ocorrências nos documentos (trechos + contexto + arquivo considerado)")

    if results:
        for i, r in enumerate(results, start=1):
            filename = _get(r, "filename")
            if not filename:
                fobj = _get(r, "file")
                filename = _get(fobj, "filename", "arquivo")

            score = _get(r, "score")
            snippet = _get(r, "text") or _get(r, "content") or ""

            title = f"{i}. {filename}"
            if isinstance(score, (int, float)):
                title += f" (score {score:.3f})"

            with st.expander(title):
                st.markdown("**Trecho**")
                st.write(snippet[:4000] if snippet else "(sem trecho retornado)")

                st.markdown("**Explicação contextual desta ocorrência**")
                with st.spinner("Gerando contexto desta ocorrência..."):
                    st.write(explain_snippet(question, filename, snippet))

                st.divider()
                st.markdown("**Arquivo considerado (baixar)**")

                local_path = find_local_file(filename, local_roots)
                if local_path and os.path.exists(local_path):
                    base_name = os.path.basename(local_path)
                    uniq = hashlib.sha1(local_path.encode("utf-8")).hexdigest()[:10]
                    with open(local_path, "rb") as f:
                        data = f.read()

                    st.download_button(
                        label=f"⬇️ Baixar este arquivo: {base_name}",
                        data=data,
                        file_name=base_name,
                        mime=guess_mime(base_name),
                        key=f"dl_{uniq}_{i}"
                    )
                else:
                    st.warning(
                        "⚠️ Não encontrei esse arquivo localmente para baixar. "
                        "Isso costuma ocorrer quando o nome retornado pelo file_search não bate exatamente com o nome no disco."
                    )
    else:
        st.info("Nenhum resultado detalhado retornado pelo file_search. Aumente o top-k ou use termos mais específicos.")
 
