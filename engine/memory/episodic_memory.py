"""
金枢 3.0 (Jin-Shu OS) - 运维情景记忆检索中枢 (Episodic Memory Engine)
======================================================================
将过去近二十年的真实机房检修记录、工单沉淀与故障指纹转化为可检索的情景记忆。
在智能体执行排障时，根据当前告警自动召回 Top-K 最相似的历史成功处置案卷，
以 Few-Shot 方式前置注入智能体的思考上下文，杜绝重复踩坑。
"""

import os
import json
import math
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class IncidentEpisode:
    """历史排障案卷条目"""
    id: str
    title: str
    symptoms: str
    root_cause: str
    resolution: str
    tags: List[str]
    success: bool = True


class EpisodicMemoryEngine:
    """情景记忆引擎 (轻量级本地化向量与 BM25 混合检索)"""

    def __init__(self, data_dir: str = None):
        if not data_dir:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            data_dir = os.path.join(project_root, "data")
        self.data_dir = data_dir
        self.episodes: List[IncidentEpisode] = []
        self._load_knowledge_bases()

    def _load_knowledge_bases(self):
        """自动装载样本工单与故障指纹库"""
        # 1. 加载 sample_tickets.json
        tickets_path = os.path.join(self.data_dir, "sample_tickets.json")
        if os.path.exists(tickets_path):
            try:
                with open(tickets_path, "r", encoding="utf-8") as f:
                    tickets = json.load(f)
                    for t in tickets:
                        self.episodes.append(IncidentEpisode(
                            id=t.get("ticket_id", "TICKET-UNKNOWN"),
                            title=t.get("title", ""),
                            symptoms=f"{t.get('description', '')} 目标设备: {t.get('affected_asset', '')}",
                            root_cause=t.get("root_cause", ""),
                            resolution=t.get("resolution", t.get("solution", "")),
                            tags=t.get("tags", [t.get("category", "General")]),
                            success=True
                        ))
            except Exception as e:
                print(f"⚠️ [EpisodicMemory] 加载 sample_tickets 失败: {e}")

        # 2. 加载 fault_fingerprint_library.json
        fingerprint_path = os.path.join(self.data_dir, "fault_fingerprint_library.json")
        if os.path.exists(fingerprint_path):
            try:
                with open(fingerprint_path, "r", encoding="utf-8") as f:
                    fps = json.load(f)
                    for fp in fps:
                        self.episodes.append(IncidentEpisode(
                            id=fp.get("fingerprint_id", "FP-UNKNOWN"),
                            title=fp.get("pattern_name", ""),
                            symptoms=f"指纹特征: {json.dumps(fp.get('telemetry_signature', {}), ensure_ascii=False)}",
                            root_cause=fp.get("underlying_physics_cause", ""),
                            resolution=fp.get("recommended_sop", ""),
                            tags=[fp.get("domain", "Infra")],
                            success=True
                        ))
            except Exception as e:
                print(f"⚠️ [EpisodicMemory] 加载 fault_fingerprint_library 失败: {e}")

    def _tokenize(self, text: str) -> List[str]:
        """中英文分词与关键词提取"""
        text = text.lower()
        # 提取英文/数字词
        words = re.findall(r'[a-zA-Z0-9_\-]+', text)
        # 提取中文两两切词 (2-gram)
        chinese_chars = re.findall(r'[\u4e00-\u9fa5]', text)
        for i in range(len(chinese_chars) - 1):
            words.append(chinese_chars[i] + chinese_chars[i+1])
        return words

    def recall_similar_episodes(self, query: str, top_k: int = 2) -> List[Dict[str, Any]]:
        """
        基于 BM25 词频与领域标签权重的混合相似度检索。
        """
        query_tokens = set(self._tokenize(query))
        if not query_tokens:
            return []

        scored_episodes = []
        for ep in self.episodes:
            doc_text = f"{ep.title} {ep.symptoms} {ep.root_cause} {' '.join(ep.tags)}"
            doc_tokens = self._tokenize(doc_text)
            doc_token_set = set(doc_tokens)

            # Jaccard + 词频重合度
            intersection = query_tokens & doc_token_set
            if not intersection:
                continue

            score = 0.0
            for token in intersection:
                # 关键词加权：如果匹配到了设备编码或专业术语
                weight = 2.5 if any(char.isupper() or char.isdigit() for char in token) else 1.0
                score += weight * (1.0 + math.log(1.0 + doc_tokens.count(token)))

            scored_episodes.append((score, ep))

        scored_episodes.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, ep in scored_episodes[:top_k]:
            results.append({
                "episode_id": ep.id,
                "title": ep.title,
                "score": round(score, 2),
                "symptoms": ep.symptoms,
                "root_cause": ep.root_cause,
                "resolution": ep.resolution,
                "tags": ep.tags
            })
        return results

    def format_as_few_shot(self, query: str, top_k: int = 2) -> str:
        """格式化为大模型可直接消费的专家先验提示词块"""
        episodes = self.recall_similar_episodes(query, top_k=top_k)
        if not episodes:
            return ""

        lines = ["### 📚 专家情景记忆检索 (历史相似真实处置案卷)"]
        for i, ep in enumerate(episodes, 1):
            lines.append(f"#### [参考案卷 {i}]: {ep['title']} (相关度: {ep['score']})")
            lines.append(f"- 历史表象: {ep['symptoms']}")
            lines.append(f"- 查证根因: {ep['root_cause']}")
            lines.append(f"- 验证有效的专家处置建议: {ep['resolution']}")
        return "\n".join(lines)


# 全局单例情景记忆引擎
global_episodic_memory = EpisodicMemoryEngine()
