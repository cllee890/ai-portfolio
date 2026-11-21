"""knowledge_base.py 的单元测试。

不调用 OpenAI 接口：向量化与聊天调用全部通过 mock 替换。
运行：python -m unittest test_knowledge_base -v   （或 pytest）
"""
import os
import unittest
from unittest import mock

# knowledge_base 在导入时会创建 OpenAI() 客户端，需要一个占位密钥；测试中不会真正联网。
os.environ.setdefault("OPENAI_API_KEY", "test-placeholder")

import numpy as np

import knowledge_base as kb


def keyword_embed(texts):
    """确定性的玩具向量：每个关键词一维，便于构造可预测的相似度。"""
    vocab = ["退款", "物流", "发票", "保修"]
    return np.array(
        [[t.count(w) + 0.01 for w in vocab] for t in texts], dtype=float
    )


def fake_completion(content):
    msg = mock.Mock()
    msg.content = content
    choice = mock.Mock()
    choice.message = msg
    resp = mock.Mock()
    resp.choices = [choice]
    return resp


class SplitTextTests(unittest.TestCase):
    def test_short_text_is_single_chunk(self):
        chunks = kb.split_text("短文本", "a.md")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "短文本")
        self.assertEqual(chunks[0].source, "a.md")

    def test_empty_text_returns_no_chunks(self):
        self.assertEqual(kb.split_text("", "empty.md"), [])

    def test_chunk_size_limit(self):
        text = "字" * 1000
        chunks = kb.split_text(text, "a.md", size=400, overlap=50)
        self.assertTrue(all(len(c.text) <= 400 for c in chunks))

    def test_consecutive_chunks_overlap_by_configured_amount(self):
        text = "".join(str(i % 10) for i in range(1000))
        chunks = kb.split_text(text, "a.md", size=400, overlap=50)
        for prev, nxt in zip(chunks, chunks[1:]):
            self.assertEqual(prev.text[-50:], nxt.text[:50])

    def test_chunks_cover_entire_text(self):
        text = "".join(chr(0x4E00 + i % 100) for i in range(1234))
        chunks = kb.split_text(text, "a.md", size=400, overlap=50)
        self.assertEqual(chunks[0].text[0], text[0])
        self.assertEqual(chunks[-1].text[-1], text[-1])
        # 按步长 350 拼接应还原原文
        rebuilt = chunks[0].text + "".join(c.text[50:] for c in chunks[1:])
        self.assertEqual(rebuilt, text)


class AddDocumentsTests(unittest.TestCase):
    def test_chunks_from_all_documents_are_indexed(self):
        base = kb.KnowledgeBase()
        with mock.patch.object(kb, "embed", side_effect=keyword_embed) as emb:
            base.add_documents({
                "refund.md": "退款政策：7天内可退款。",
                "shipping.md": "物流说明：3-7天送达。",
            })
        self.assertEqual([c.source for c in base.chunks], ["refund.md", "shipping.md"])
        self.assertEqual(base.vectors.shape, (2, 4))
        emb.assert_called_once()
        self.assertEqual(len(emb.call_args[0][0]), 2)

    def test_add_documents_appends_to_existing_chunks(self):
        base = kb.KnowledgeBase()
        with mock.patch.object(kb, "embed", side_effect=keyword_embed):
            base.add_documents({"a.md": "退款"})
            base.add_documents({"b.md": "发票"})
        self.assertEqual(len(base.chunks), 2)
        self.assertEqual(base.vectors.shape[0], 2)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.base = kb.KnowledgeBase()
        with mock.patch.object(kb, "embed", side_effect=keyword_embed):
            self.base.add_documents({
                "refund.md": "退款政策：签收后7天内可申请退款。",
                "shipping.md": "物流说明：一般3-7个工作日送达。",
                "warranty.md": "保修政策：保修期一年。",
            })

    def test_returns_most_similar_chunk_first(self):
        with mock.patch.object(kb, "embed", side_effect=keyword_embed):
            hits = self.base.search("我想申请退款")
        self.assertEqual(hits[0][0].source, "refund.md")
        self.assertGreaterEqual(hits[0][1], 0.6)

    def test_respects_top_k(self):
        with mock.patch.object(kb, "embed", side_effect=keyword_embed):
            hits = self.base.search("退款 物流 保修", top_k=1, threshold=0.0)
        self.assertEqual(len(hits), 1)

    def test_scores_are_sorted_descending(self):
        with mock.patch.object(kb, "embed", side_effect=keyword_embed):
            hits = self.base.search("退款 物流", top_k=3, threshold=0.0)
        scores = [s for _, s in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_below_threshold_returns_empty(self):
        with mock.patch.object(kb, "embed", side_effect=keyword_embed):
            hits = self.base.search("今天天气怎么样")
        self.assertEqual(hits, [])

    def test_custom_threshold_filters_weak_matches(self):
        with mock.patch.object(kb, "embed", side_effect=keyword_embed):
            strict = self.base.search("退款 物流", threshold=0.99)
            loose = self.base.search("退款 物流", threshold=0.0)
        self.assertLessEqual(len(strict), len(loose))
        self.assertTrue(all(s >= 0.99 for _, s in strict))


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.base = kb.KnowledgeBase()
        with mock.patch.object(kb, "embed", side_effect=keyword_embed):
            self.base.add_documents({"refund.md": "退款政策：签收后7天内可申请退款。"})

    def test_no_reliable_hit_transfers_to_human_without_llm_call(self):
        with mock.patch.object(kb, "embed", side_effect=keyword_embed), \
             mock.patch.object(kb, "client") as client:
            result = kb.answer(self.base, "今天天气怎么样")
        self.assertEqual(result, "TRANSFER_TO_HUMAN")
        client.chat.completions.create.assert_not_called()

    def test_hit_builds_prompt_with_source_and_returns_model_reply(self):
        with mock.patch.object(kb, "embed", side_effect=keyword_embed), \
             mock.patch.object(kb, "client") as client:
            client.chat.completions.create.return_value = fake_completion("可在7天内申请退款。[来源:refund.md]")
            result = kb.answer(self.base, "我想申请退款")
        self.assertEqual(result, "可在7天内申请退款。[来源:refund.md]")
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-4o-mini")
        user_msg = kwargs["messages"][1]["content"]
        self.assertIn("[来源:refund.md]", user_msg)
        self.assertIn("问题：我想申请退款", user_msg)


class EmbedTests(unittest.TestCase):
    def test_embed_calls_api_and_returns_matrix(self):
        item = lambda v: mock.Mock(embedding=v)
        resp = mock.Mock(data=[item([0.1, 0.2]), item([0.3, 0.4])])
        with mock.patch.object(kb, "client") as client:
            client.embeddings.create.return_value = resp
            out = kb.embed(["a", "b"])
        client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small", input=["a", "b"]
        )
        self.assertEqual(out.shape, (2, 2))
        np.testing.assert_allclose(out[1], [0.3, 0.4])


if __name__ == "__main__":
    unittest.main()
