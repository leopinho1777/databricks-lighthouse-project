"""Divide documentos em chunks recuperáveis, preservando contexto e metadados.

Duas estratégias (§6.4 da spec):
  A) Cards gerados (doc_type em SEM_DIVISAO): 1 card = 1 chunk, sem divisão.
  B) Documentos escritos: divisão hierárquica por cabeçalho markdown e, se ainda
     exceder o teto, recursiva por parágrafo e por sentença -- nunca por
     contagem cega de caracteres. Breadcrumb prefixado em todo chunk.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SEM_DIVISAO = {
    "previsao_produto_loja", "previsao_produto", "previsao_loja",
    "crescimento_cd", "dicionario_dados", "sazonalidade_produto",
}

METADADOS_HERDADOS = (
    "doc_id", "doc_type", "titulo", "produto_id", "produto_nome",
    "loja_id", "loja_nome", "cd_id", "cd_nome", "periodo",
    "fonte", "atualizado_em",
)

# Schema DDL da tabela rag.chunks. Necessário no createDataFrame porque o Spark
# Connect não infere tipo de coluna 100% nula (cards ausentes -> metadados nulos).
CHUNK_DDL = (
    "chunk_id string, doc_id string, chunk_index int, texto string, "
    "doc_type string, titulo string, produto_id string, produto_nome string, "
    "loja_id string, loja_nome string, cd_id string, cd_nome string, "
    "periodo string, fonte string, atualizado_em timestamp"
)


@dataclass
class ChunkCfg:
    target_chars: int = 3200
    max_chars: int = 4000
    overlap_chars: int = 480

    @classmethod
    def from_config(cls, cfg) -> "ChunkCfg":
        c = cfg.chunking
        return cls(
            target_chars=int(c.get("target_chars", 3200)),
            max_chars=int(c.get("max_chars", 4000)),
            overlap_chars=int(c.get("overlap_chars", 480)),
        )


def _split_secoes(texto: str) -> list[tuple[str, str]]:
    """Divide markdown por cabeçalhos (# e ##) -> lista de (breadcrumb, conteúdo)."""
    partes: list[tuple[str, str]] = []
    h1 = h2 = ""
    buf: list[str] = []

    def flush() -> None:
        if "".join(buf).strip():
            bc = " > ".join(x for x in (h1, h2) if x)
            partes.append((bc, "".join(buf).strip()))

    for linha in texto.splitlines(keepends=True):
        m = re.match(r"^(#{1,2})\s+(.*)", linha)
        if m:
            flush()
            buf.clear()
            if len(m.group(1)) == 1:
                h1, h2 = m.group(2).strip(), ""
            else:
                h2 = m.group(2).strip()
        else:
            buf.append(linha)
    flush()
    return partes or [("", texto.strip())]


def _split_recursivo(texto: str, cfg: ChunkCfg) -> list[str]:
    """Quebra por parágrafo e depois por sentença, respeitando o teto.

    Nunca corta no meio de uma linha (logo, nunca no meio de uma linha de tabela
    markdown). O overlap entre blocos da mesma seção começa numa fronteira de
    linha, então também não fragmenta linhas.
    """
    texto = texto.strip()
    if not texto:
        return []
    if len(texto) <= cfg.max_chars:
        return [texto]

    blocos: list[str] = []
    atual = ""

    def push() -> None:
        nonlocal atual
        if atual:
            blocos.append(atual)
            atual = ""

    for par in re.split(r"\n\s*\n", texto):
        par = par.strip()
        if not par:
            continue
        if atual and len(atual) + len(par) + 2 > cfg.target_chars:
            push()
        if len(par) <= cfg.target_chars:
            atual = f"{atual}\n\n{par}".strip()
        else:  # parágrafo maior que o alvo: quebra por sentença
            for s in re.split(r"(?<=[.!?])\s+", par):
                s = s.strip()
                if not s:
                    continue
                if atual and len(atual) + len(s) + 1 > cfg.target_chars:
                    push()
                atual = f"{atual} {s}".strip()
    push()

    # overlap apenas entre blocos da MESMA seção, iniciando em fronteira de linha
    if cfg.overlap_chars and len(blocos) > 1:
        costurados = [blocos[0]]
        for i in range(1, len(blocos)):
            tail = blocos[i - 1][-cfg.overlap_chars:]
            nl = tail.find("\n")
            if nl != -1:
                tail = tail[nl + 1:]
            costurados.append(f"{tail}\n\n{blocos[i]}".strip())
        blocos = costurados

    # teto rígido: garante o limite do AI Search mesmo em entrada patológica
    final: list[str] = []
    for b in blocos:
        while len(b) > cfg.max_chars:
            corte = b.rfind(" ", 1, cfg.max_chars)
            if corte <= 0:
                corte = cfg.max_chars
            final.append(b[:corte].strip())
            b = b[corte:].strip()
        if b:
            final.append(b)
    return final


def chunk_document(doc: dict, cfg: ChunkCfg | None = None) -> list[dict]:
    """Devolve os chunks de um documento, já com breadcrumb e metadados herdados."""
    cfg = cfg or ChunkCfg()
    titulo = doc.get("titulo") or doc.get("doc_id", "")

    if doc.get("doc_type") in SEM_DIVISAO:
        pares = [(titulo, (doc.get("corpo") or "").strip())]
    else:
        pares = []
        for bc, conteudo in _split_secoes(doc.get("corpo") or ""):
            # breadcrumb = título + seções, sem repetir segmentos (o H1 do
            # markdown costuma ser igual ao próprio título).
            segmentos = [titulo, *(p.strip() for p in bc.split(" > ") if p.strip())]
            breadcrumb = " > ".join(dict.fromkeys(s for s in segmentos if s))
            for bloco in _split_recursivo(conteudo, cfg):
                pares.append((breadcrumb, bloco))
        if not pares:  # documento vazio ou só cabeçalho
            pares = [(titulo, (doc.get("corpo") or "").strip())]

    herdados = {k: doc.get(k) for k in METADADOS_HERDADOS}
    return [
        {
            **herdados,
            "chunk_id": f"{doc['doc_id']}#{i}",
            "chunk_index": i,
            "texto": f"[{bc}]\n{txt}",  # breadcrumb embutido no embedding
        }
        for i, (bc, txt) in enumerate(pares)
    ]
