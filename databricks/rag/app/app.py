"""Chat Streamlit do RAG LH Nautical (Databricks Apps).

Cada pergunta é independente (§9.3): o histórico só é exibido na tela, nunca entra
no prompt. Toda a lógica de RAG vem de `src/rag` -- este arquivo é só a interface.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import streamlit as st

# Coloca src/ no sys.path (o app roda com CWD na raiz do bundle, mas não dependemos disso)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag.config import Config  # noqa: E402
from rag.generator import Generator  # noqa: E402
from rag.observability import QueryLogger  # noqa: E402
from rag.retriever import Retriever  # noqa: E402

NOME_BOT = "Teslinha"
AVATAR_BOT = "🤖"
AVATAR_USUARIO = "🧑‍💼"
RECUSA = "Não encontrei"
# Bloco "Fontes:" que o LLM acrescenta ao final da resposta (uso interno, não mostrado ao cliente)
_BLOCO_FONTES = re.compile(r"\n\s*[*_#]*\s*Fontes\s*:?[*_]*.*", re.DOTALL | re.IGNORECASE)
EXEMPLOS = [
    "Como funciona a arquitetura de ingestão do projeto?",
    "Quais são as tabelas da camada marts?",
    "Por que o RAG não usa Text-to-SQL?",
]

st.set_page_config(page_title=NOME_BOT, page_icon=AVATAR_BOT, layout="centered")

# Estilo do chat. Só HTML/CSS estático: nenhum texto do usuário passa por unsafe_allow_html.
_ESTILO = """
<style>
:root {
  --navy: #0B2545; --teal: #0E7490; --teal-soft: #E6F4F8;
  --bg: #F4F7FA; --card: #FFFFFF; --borda: #DCE5ED; --texto: #14283C; --suave: #5B7083;
}
.stApp, [data-testid="stHeader"], [data-testid="stBottom"],
[data-testid="stBottom"] > div { background: var(--bg); }
#MainMenu, footer { visibility: hidden; }
.block-container { max-width: 780px; padding-top: 3.5rem; padding-bottom: 6rem; }

/* cabeçalho */
.tv-hero { text-align: center; padding: 1.4rem 1rem 0.6rem; }
.tv-hero.compacto { padding: 0.2rem 1rem 0.2rem; }
.tv-logo {
  width: 72px; height: 72px; margin: 0 auto 0.7rem; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; font-size: 38px;
  background: var(--card); border: 3px solid var(--teal);
  box-shadow: 0 6px 18px rgba(14, 116, 144, 0.22);
}
.tv-hero.compacto .tv-logo { width: 44px; height: 44px; font-size: 24px; margin-bottom: 0.3rem; }
.tv-titulo { margin: 0; font-size: 2rem; font-weight: 700; color: var(--navy); letter-spacing: -0.02em; }
.tv-hero.compacto .tv-titulo { font-size: 1.3rem; }
.tv-sub { margin: 0.3rem 0 0; color: var(--navy); font-size: 1.05rem; font-weight: 500; }
.tv-nota { margin: 0.2rem 0 0; color: var(--suave); font-size: 0.82rem; }
.tv-hero.compacto .tv-sub, .tv-hero.compacto .tv-nota { display: none; }

/* mensagens */
[data-testid="stChatMessage"] {
  background: var(--card); border: 1px solid var(--borda); border-radius: 16px;
  padding: 0.9rem 1.1rem; margin-bottom: 0.8rem; box-shadow: 0 1px 3px rgba(11, 37, 69, 0.05);
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  background: var(--teal-soft); border-color: #BFE0EA;
}
[data-testid="stChatMessage"] p { color: var(--texto); line-height: 1.6; }
[data-testid="stChatMessage"] strong:first-child { color: var(--teal); font-size: 0.82rem;
  text-transform: uppercase; letter-spacing: 0.05em; }

/* sugestões */
.stButton > button {
  width: 100%; text-align: left; justify-content: flex-start; padding: 0.75rem 1rem;
  border-radius: 12px; border: 1px solid var(--borda); background: var(--card);
  color: var(--texto); font-weight: 500; transition: all 0.15s ease;
}
.stButton > button div, .stButton > button p { text-align: left; width: 100%; }
.stButton > button:hover {
  border-color: var(--teal); color: var(--teal); background: var(--teal-soft);
  transform: translateY(-1px); box-shadow: 0 3px 10px rgba(14, 116, 144, 0.12);
}

/* campo de entrada */
[data-testid="stChatInput"] { background: var(--card); border-radius: 14px;
  border: 1px solid var(--borda); box-shadow: 0 2px 10px rgba(11, 37, 69, 0.08); }
[data-testid="stChatInput"] textarea { color: var(--texto); background: var(--card); }
[data-testid="stChatInput"]:focus-within { border-color: var(--teal); }

/* cartão de fontes */
[data-testid="stExpander"] { background: var(--card); border: 1px solid var(--borda);
  border-radius: 12px; margin-top: 0.4rem; }
[data-testid="stExpander"] summary { color: var(--teal); font-weight: 600; }

/* avatares */
[data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] {
  background: var(--teal-soft); border: 1px solid #BFE0EA; }
</style>
"""
st.markdown(_ESTILO, unsafe_allow_html=True)


# show_spinner=False: o único indicador de carregamento é o da própria caixa da resposta
@st.cache_resource(show_spinner=False)
def _carregar():
    """Instancia config, retriever, generator e logger uma única vez por processo."""
    cfg = Config.load()
    warehouse_id = os.getenv("RAG_WAREHOUSE_ID")
    logger = QueryLogger(cfg, warehouse_id) if warehouse_id else None
    return cfg, Retriever(cfg), Generator(cfg), logger


def _responder(pergunta: str) -> tuple[str, str]:
    """Recupera trechos, gera a resposta e registra a interação (sem derrubar o chat).

    Devolve (texto, fontes): o texto sem o bloco "Fontes:" e as fontes separadas, para
    aparecerem num cartão recolhível. O log guarda a resposta original.
    """
    cfg, retriever, generator, logger = _carregar()
    erro = None
    chunks, resposta, lat_ret, lat_llm = [], "", 0, 0
    try:
        t0 = time.time()
        chunks = retriever.search(pergunta)
        lat_ret = int((time.time() - t0) * 1000)
        resposta, lat_llm = generator.answer(pergunta, chunks)
    except Exception as e:  # noqa: BLE001 -- mostra mensagem amigável, loga o erro
        erro = f"{type(e).__name__}: {e}"
        resposta = "Ocorreu um erro ao consultar o assistente. Tente novamente em instantes."

    if logger:
        logger.log(
            pergunta=pergunta,
            chunk_ids=[c.chunk_id for c in chunks],
            scores=[c.score for c in chunks],
            n_recuperados=len(chunks),
            n_usados=len(chunks),
            modelo_llm=cfg.llm["endpoint"],
            modelo_embedding=cfg.vs["embedding_model"],
            resposta=resposta,
            recusou=resposta.startswith(RECUSA),
            lat_retrieval_ms=lat_ret,
            lat_llm_ms=lat_llm,
            erro=erro,
        )
    texto, bloco = _separar_fontes(resposta)
    return texto, _nomes_fontes(chunks, bloco)


def _nome_fonte(fonte: str) -> str:
    """Só o nome: "docs/arquitetura.md" -> "arquitetura.md"; tabela "cat.sch.tab" -> "tab"."""
    fonte = (fonte or "").strip().replace("\\", "/")
    if "/" in fonte:
        return fonte.rsplit("/", 1)[-1]
    if "information_schema" in fonte:
        return "information_schema.columns"
    return fonte.rsplit(".", 1)[-1]


def _nomes_fontes(chunks, bloco: str) -> str:
    """Lista (markdown) só com os nomes das fontes que o modelo citou na resposta."""
    if not bloco:
        return ""  # recusa ou resposta sem fontes
    citados = [c.fonte for c in chunks if c.titulo and c.titulo.lower() in bloco.lower()]
    if not citados:  # o modelo parafraseou o título: usa a "origem" escrita por ele
        citados = re.findall(r"origem:\s*([^,)]+)", bloco)
    nomes = list(dict.fromkeys(n for n in map(_nome_fonte, citados) if n))
    return "\n".join(f"- {n}" for n in nomes)


def _separar_fontes(resposta: str) -> tuple[str, str]:
    """Separa o texto da resposta do bloco final "Fontes:" (devolvido sem o cabeçalho)."""
    m = _BLOCO_FONTES.search(resposta)
    if not m:
        return resposta.strip(), ""
    bloco = re.sub(r"^\s*[*_#]*\s*Fontes\s*:?[*_]*\s*", "", m.group(0), flags=re.IGNORECASE)
    return resposta[: m.start()].strip(), bloco.strip()


def _nome_usuario() -> str:
    """Nome exibido ao usuário: parte local do login do Databricks (header do App), senão "Você"."""
    try:
        login = st.context.headers.get("X-Forwarded-Preferred-Username") or ""
    except Exception:  # noqa: BLE001 -- fora do Databricks Apps não há header
        login = ""
    return login.split("@")[0] or "Você"


def _fontes(caixa, fontes: str) -> None:
    """Cartão recolhível (com a setinha) listando só as fontes usadas na resposta."""
    if fontes:
        caixa.expander("Fontes", expanded=False).markdown(fontes)


def _mensagem(role: str, nome: str, texto: str | None = None, fontes: str = ""):
    """Desenha uma mensagem do chat com o nome do autor em negrito acima do texto."""
    avatar = AVATAR_BOT if role == "assistant" else AVATAR_USUARIO
    caixa = st.chat_message(role, avatar=avatar)
    caixa.markdown(f"**{nome}**")
    if texto is not None:
        caixa.markdown(texto)
        _fontes(caixa, fontes)
    return caixa


NOME_USUARIO = _nome_usuario()

if "mensagens" not in st.session_state:
    st.session_state.mensagens = []

# Cabeçalho grande na tela inicial; compacto depois da primeira mensagem
def _cabecalho(compacto: bool) -> str:
    classe = "tv-hero compacto" if compacto else "tv-hero"
    return (
        f'<div class="{classe}"><div class="tv-logo">{AVATAR_BOT}</div>'
        f'<h1 class="tv-titulo">{NOME_BOT}</h1>'
        '<p class="tv-sub">Assistente do projeto LH Nautical</p>'
        '<p class="tv-nota">Responde apenas com base nos documentos do projeto · '
        "cada pergunta é independente</p></div>"
    )


cabecalho = st.empty()
cabecalho.markdown(_cabecalho(bool(st.session_state.mensagens)), unsafe_allow_html=True)

# Reexibe o histórico da sessão (só visual)
for m in st.session_state.mensagens:
    _mensagem(m["role"], NOME_BOT if m["role"] == "assistant" else NOME_USUARIO,
              m["conteudo"], m.get("fontes", ""))

# Sugestões de pergunta só aparecem antes da primeira interação
pergunta = None
sugestoes = st.empty()
if not st.session_state.mensagens:
    with sugestoes.container():
        st.markdown("**Experimente:**")
        for ex in EXEMPLOS:
            if st.button(ex, key=ex, use_container_width=True):
                pergunta = ex

pergunta = st.chat_input("Pergunte sobre o projeto...") or pergunta

if pergunta:
    sugestoes.empty()  # some com as sugestões assim que a conversa começa
    cabecalho.markdown(_cabecalho(True), unsafe_allow_html=True)
    st.session_state.mensagens.append({"role": "user", "conteudo": pergunta})
    _mensagem("user", NOME_USUARIO, pergunta)
    caixa = _mensagem("assistant", NOME_BOT)
    with caixa, st.spinner("Consultando os documentos..."):
        resp, fontes = _responder(pergunta)
    caixa.markdown(resp)
    _fontes(caixa, fontes)
    st.session_state.mensagens.append({"role": "assistant", "conteudo": resp, "fontes": fontes})
