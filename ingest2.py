import os
import glob
import time
from dotenv import load_dotenv
from openai import OpenAI

SUPPORTED_EXTENSIONS = {
    "art","bat","brf","c","cls","cpp","cs","css","csv","diff","doc","docx","dot","eml","es","gif","go","h","hs",
    "htm","html","ics","ifb","java","jpeg","jpg","js","json","keynote","ksh","ltx","mail","markdown","md","mht",
    "mhtml","mjs","nws","odt","pages","patch","pdf","php","pkl","pl","pm","png","pot","ppa","pps","ppt","pptx",
    "pwz","py","rb","rst","rtf","scala","sh","shtml","srt","sty","tar","tex","text","ts","txt","vcf","vtt",
    "webp","wiz","xla","xlb","xlc","xlm","xls","xlsx","xlt","xlw","xml","yaml","yml","zip"
}

POLL_INTERVAL_SEC = 2.0
POLL_TIMEOUT_SEC = 15 * 60  # 15 min por arquivo (ajuste se precisar)

def load_env():
    here = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(here, ".env")
    load_dotenv(dotenv_path=env_path)

def human_size(num_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"

def normalize_extension(path: str) -> str:
    base, ext = os.path.splitext(path)
    if not ext:
        return path
    ext_no_dot = ext[1:]
    if ext_no_dot and ext_no_dot != ext_no_dot.lower():
        new_path = base + "." + ext_no_dot.lower()
        try:
            os.rename(path, new_path)
            print(f"    🔧 Renomeado: {os.path.basename(path)} -> {os.path.basename(new_path)}")
            return new_path
        except Exception as e:
            print(f"    ⚠️  Não consegui renomear extensão para minúsculo: {e}")
            return path
    return path

def get_ext(path: str) -> str:
    return os.path.splitext(path)[1].lower().lstrip(".")

def safe_print_kv(k, v):
    print(f"    {k}: {v}")

def poll_vector_file_status(client: OpenAI, vector_store_id: str, vs_file_id: str):
    """
    Espera o arquivo anexado no vector store ficar completed ou failed.
    Retorna status final e (se existir) last_error.
    """
    deadline = time.time() + POLL_TIMEOUT_SEC
    last_status = None

    while time.time() < deadline:
        vs_file = client.vector_stores.files.retrieve(
            vector_store_id=vector_store_id,
            file_id=vs_file_id
        )
        status = getattr(vs_file, "status", None)
        last_error = getattr(vs_file, "last_error", None)

        if status != last_status:
            safe_print_kv("status", status)
            last_status = status

        if status in ("completed", "failed", "cancelled"):
            return status, last_error

        time.sleep(POLL_INTERVAL_SEC)

    return "timeout", None

def list_all_vector_store_files(client: OpenAI, vector_store_id: str, limit: int = 10000):
    """
    Lista arquivos anexados no vector store com paginação.
    Retorna lista completa.
    """
    all_items = []
    cursor = None

    while True:
        page = client.vector_stores.files.list(
            vector_store_id=vector_store_id,
            limit=100,
            after=cursor
        )
        data = getattr(page, "data", []) or []
        all_items.extend(data)

        if len(all_items) >= limit:
            break

        cursor = getattr(page, "last_id", None)
        has_more = getattr(page, "has_more", False)
        if not has_more:
            break

    return all_items

def main():
    load_env()

    api_key = os.getenv("OPENAI_API_KEY")
    vector_store_id = os.getenv("VECTOR_STORE_ID2")

    if not api_key:
        raise SystemExit("ERRO: OPENAI_API_KEY não encontrado no .env")
    if not vector_store_id:
        raise SystemExit("ERRO: VECTOR_STORE_ID não encontrado no .env")

    client = OpenAI(api_key=api_key)

    here = os.path.dirname(os.path.abspath(__file__))
    docs_dir = os.path.join(here, "doc2")

    _docs_real = os.path.realpath(docs_dir)
    paths = sorted(
        p for p in glob.glob(os.path.join(docs_dir, "**", "*"), recursive=True)
        if os.path.isfile(p)
        and not os.path.islink(p)                                        # skip symlinks
        and os.path.realpath(p).startswith(_docs_real + os.sep)          # stay inside docs_dir
        and os.path.getsize(p) > 0
    )

    if not paths:
        raise SystemExit(f"ERRO: Nenhum arquivo encontrado em {docs_dir}/")

    print("============================================================")
    print("INGEST ASSISTIDO — OpenAI Vector Store + File Search")
    print("============================================================")
    print(f"Docs dir:     {docs_dir}")
    print(f"Vector Store: {vector_store_id}")
    print(f"Arquivos no disco: {len(paths)}")
    print("------------------------------------------------------------")

    # Valida acesso ao Vector Store e mostra contagem inicial
    try:
        client.vector_stores.retrieve(vector_store_id=vector_store_id)
    except Exception as e:
        raise SystemExit(f"ERRO: não consegui acessar o Vector Store {vector_store_id}. Detalhe: {e}")

    try:
        initial_items = list_all_vector_store_files(client, vector_store_id)
        print(f"Arquivos já anexados no Vector Store (antes): {len(initial_items)}")
    except Exception as e:
        print(f"⚠️  Não consegui listar arquivos do Vector Store antes de iniciar. Detalhe: {e}")
        initial_items = []

    print("------------------------------------------------------------\n")

    ok = 0
    fail = 0
    skip = 0

    failures = []  # (fname, stage, err)
    skipped = []   # (fname, ext, reason)
    processed = [] # (fname, status_final, vs_file_id)

    total = len(paths)
    start_ts = time.time()

    for idx, original_path in enumerate(paths, start=1):
        print(f"\n[{idx}/{total}] ================================================")
        path = normalize_extension(original_path)

        fname = os.path.basename(path)
        ext = get_ext(path)
        size = human_size(os.path.getsize(path))

        safe_print_kv("arquivo", fname)
        safe_print_kv("ext", f".{ext}" if ext else "(sem extensão)")
        safe_print_kv("tamanho", size)

        # valida extensão
        if ext not in SUPPORTED_EXTENSIONS:
            skip += 1
            reason = f"Extensão .{ext} não suportada"
            skipped.append((fname, ext, reason))
            print(f"    ⏭️  SKIP: {reason}")
            if ext in ("vsd", "vsdx"):
                print("    👉 Ação: exporte/converta para .pdf (ou .png/.jpg) e rode novamente.")
            continue

        # 1) upload
        _fsize = os.path.getsize(path)
        if _fsize > 100 * 1024 * 1024:
            skip += 1
            skipped.append((fname, ext, f"Arquivo muito grande ({_fsize // (1024*1024)} MB > 100 MB)"))
            print(f"    ⏭️  SKIP: arquivo muito grande ({_fsize // (1024*1024)} MB). Limite: 100 MB.")
            continue
        try:
            print("    ⬆️  Uploading para OpenAI (files.create)...")
            with open(path, "rb") as f:
                uploaded = client.files.create(file=f, purpose="assistants")
            file_id = uploaded.id
            safe_print_kv("file_id", file_id)
        except Exception as e:
            fail += 1
            failures.append((fname, "upload", str(e)))
            print(f"    ❌ FALHA no upload: {e}")
            continue

        # 2) attach no vector store
        try:
            print("    📎 Anexando ao Vector Store (vector_stores.files.create)...")
            vs_file = client.vector_stores.files.create(
                vector_store_id=vector_store_id,
                file_id=file_id
            )
            vs_file_id = getattr(vs_file, "id", None)
            safe_print_kv("vs_file_id", vs_file_id)
        except Exception as e:
            fail += 1
            failures.append((fname, "attach", str(e)))
            print(f"    ❌ FALHA ao anexar no vector store: {e}")
            continue

        # 3) polling de status (indexação)
        try:
            print("    🔎 Aguardando indexação (status)...")
            status, last_error = poll_vector_file_status(client, vector_store_id, vs_file_id)

            if status == "completed":
                ok += 1
                processed.append((fname, status, vs_file_id))
                print("    ✅ COMPLETED (indexado e pronto para busca)")
            else:
                fail += 1
                processed.append((fname, status, vs_file_id))
                err_msg = ""
                if last_error:
                    # last_error pode ser objeto; tenta string
                    err_msg = getattr(last_error, "message", None) or str(last_error)
                failures.append((fname, f"index:{status}", err_msg))
                print(f"    ❌ NÃO COMPLETO: status final = {status}")
                if err_msg:
                    print(f"       last_error: {err_msg}")

        except Exception as e:
            fail += 1
            failures.append((fname, "poll", str(e)))
            print(f"    ❌ FALHA no polling: {e}")
            continue

    elapsed = time.time() - start_ts

    print("\n============================================================")
    print("RESUMO FINAL")
    print("============================================================")
    print(f"Tempo total: {elapsed:.1f}s")
    print(f"Sucesso:     {ok}")
    print(f"Falhas:      {fail}")
    print(f"Pulados:     {skip}")

    if skipped:
        print("\n--- Pulados (não suportados) ---")
        for fname, ext, reason in skipped:
            print(f"- {fname} (.{ext}): {reason}")

    if failures:
        print("\n--- Falhas (detalhe por etapa) ---")
        for fname, stage, err in failures:
            print(f"- {fname} | etapa={stage}")
            if err:
                print(f"  erro: {err}")

    # Contagem final no Vector Store (dentro do próprio script)
    print("\n------------------------------------------------------------")
    print("CONFIRMAÇÃO NO VECTOR STORE (após ingest)")
    print("------------------------------------------------------------")
    try:
        final_items = list_all_vector_store_files(client, vector_store_id)
        print(f"Arquivos anexados no Vector Store (depois): {len(final_items)}")
        # mostra alguns statuses
        for it in final_items[:15]:
            print("-", getattr(it, "id", None), getattr(it, "status", None))
    except Exception as e:
        print(f"⚠️  Não consegui listar arquivos do Vector Store após ingest. Detalhe: {e}")

    print("\nPronto. ✅")

if __name__ == "__main__":
    main()
 
