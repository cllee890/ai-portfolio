"""通用 RAG 知识库示例（示意实现）。

依赖：pip install openai numpy
仅演示切分、向量化、检索、拼接提示词的核心流程。
"""
from dataclasses import dataclass
import numpy as np
from openai import OpenAI

client = OpenAI()  # 读取环境变量 OPENAI_API_KEY


@dataclass
class Chunk:
    text: str
    source: str


def split_text(text: str, source: str, size: int = 400, overlap: int = 50) -> list[Chunk]:
    chunks, start = [], 0
    while start < len(text):
        chunks.append(Chunk(text[start:start + size], source))
        start += size - overlap
    return chunks


def embed(texts: list[str]) -> np.ndarray:
    resp = client.embeddings.create(model="text-embedding-3-small", input=texts)
    return np.array([d.embedding for d in resp.data])


class KnowledgeBase:
    def __init__(self):
        self.chunks: list[Chunk] = []
        self.vectors: np.ndarray | None = None

    def add_documents(self, docs: dict[str, str]):
        for source, text in docs.items():
            self.chunks.extend(split_text(text, source))
        self.vectors = embed([c.text for c in self.chunks])

    def search(self, query: str, top_k: int = 4, threshold: float = 0.6):
        q = embed([query])[0]
        sims = self.vectors @ q / (np.linalg.norm(self.vectors, axis=1) * np.linalg.norm(q))
        idx = np.argsort(sims)[::-1][:top_k]
        return [(self.chunks[i], float(sims[i])) for i in idx if sims[i] >= threshold]


def answer(kb: KnowledgeBase, question: str) -> str:
    hits = kb.search(question)
    if not hits:
        return "TRANSFER_TO_HUMAN"  # 无可靠依据，转人工
    context = "\n\n".join(f"[来源:{c.source}] {c.text}" for c, _ in hits)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "你是电商客服。仅依据提供的资料回答，并标注来源。资料不足时说明无法确定。"},
            {"role": "user", "content": f"资料：\n{context}\n\n问题：{question}"},
        ],
    )
    return resp.choices[0].message.content
