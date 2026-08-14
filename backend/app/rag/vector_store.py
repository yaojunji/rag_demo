"""向量存储：ChromaDB 持久化封装。

- 每个知识库一个 collection（命名 kb_{id}），天然隔离
- metadata 携带 chunk_id / doc_id / kb_id / chunk_index / filename / page / section
- 文档级删除：collection.delete(where={"doc_id": ...})
"""
from __future__ import annotations

import logging
import threading
from typing import Any, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class VectorStoreError(RuntimeError):
    pass


class VectorStore:
    """Chroma 持久化向量库（进程内单例，线程安全）。"""

    def __init__(self, persist_dir: str | None = None) -> None:
        self._client: Any = None
        self._collections: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._persist_dir = persist_dir or str(settings.vector_dir)

    @property
    def client(self):
        if self._client is None:
            try:
                import chromadb
            except ImportError as e:  # pragma: no cover
                raise VectorStoreError("chromadb 未安装") from e
            self._client = chromadb.PersistentClient(path=self._persist_dir)
        return self._client

    def _collection(self, kb_id: int):
        name = f"kb_{kb_id}"
        with self._lock:
            if name not in self._collections:
                self._collections[name] = self.client.get_or_create_collection(
                    name=name, metadata={"hnsw:space": "cosine"}
                )
            return self._collections[name]

    # ---------------- 写 ----------------
    def upsert_chunks(
        self,
        kb_id: int,
        doc_id: int,
        chunks: List[dict],
        vectors: List[List[float]],
        base_metadata: dict,
    ) -> None:
        """写入/覆盖一个文档的全部块。

        chunks: [{"chunk_id": int, "text": str, "page": int|None, "section": str|None}]
        base_metadata: {filename, file_type, ...}
        """
        if not chunks:
            return
        ids: List[str] = [f"d{doc_id}_c{c['chunk_index']}" for c in chunks]
        texts = [c["text"] for c in chunks]
        metas: List[dict] = []
        for c in chunks:
            m = dict(base_metadata)
            m.update(
                {
                    "chunk_id": c["chunk_id"],
                    "doc_id": doc_id,
                    "kb_id": kb_id,
                    "chunk_index": c["chunk_index"],
                    "page": c.get("page"),
                    "section": c.get("section"),
                }
            )
            metas.append(m)
        self._collection(kb_id).upsert(ids=ids, documents=texts, embeddings=vectors, metadatas=metas)

    def delete_document(self, kb_id: int, doc_id: int) -> None:
        self._collection(kb_id).delete(where={"doc_id": doc_id})

    def delete_kb(self, kb_id: int) -> None:
        with self._lock:
            try:
                self.client.delete_collection(f"kb_{kb_id}")
            except Exception as e:  # noqa: BLE001  collection 可能不存在
                logger.debug("delete collection %s: %s", kb_id, e)
            self._collections.pop(f"kb_{kb_id}", None)

    # ---------------- 查 ----------------
    def search(
        self,
        kb_id: int,
        query_vector: List[float],
        top_k: int = 10,
        where: Optional[dict] = None,
    ) -> List[dict]:
        """向量相似度检索，返回 [{id, text, metadata, score}]（score 为余弦相似度）。"""
        col = self._collection(kb_id)
        n = min(top_k, col.count())
        if n <= 0:
            return []
        res = col.query(
            query_embeddings=[query_vector],
            n_results=n,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        out: List[dict] = []
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        ids = (res.get("ids") or [[]])[0]
        for i in range(len(docs)):
            out.append(
                {
                    "id": ids[i],
                    "text": docs[i],
                    "metadata": metas[i] or {},
                    "score": 1.0 - float(dists[i]),  # 余弦距离 → 相似度
                }
            )
        return out

    def count(self, kb_id: int) -> int:
        return self._collection(kb_id).count()

    def list_chunks(self, kb_id: int, doc_id: int, limit: int = 200) -> List[dict]:
        col = self._collection(kb_id)
        res = col.get(where={"doc_id": doc_id}, include=["documents", "metadatas"], limit=limit)
        out = []
        for i in range(len(res.get("ids") or [])):
            out.append(
                {
                    "chunk_index": (res["metadatas"][i] or {}).get("chunk_index", i),
                    "text": res["documents"][i],
                    "metadata": res["metadatas"][i] or {},
                }
            )
        out.sort(key=lambda c: c["chunk_index"])
        return out

    def stats(self) -> dict:
        try:
            cols = self.client.list_collections()
            return {"collections": len(cols), "dir": self._persist_dir}
        except Exception as e:  # noqa: BLE001
            return {"collections": 0, "dir": self._persist_dir, "error": str(e)}


vector_store = VectorStore()
