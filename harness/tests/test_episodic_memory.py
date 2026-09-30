from engine.memory.episodic_memory import EpisodicMemoryEngine, IncidentEpisode


def test_episodic_memory_custom_episode(tmp_path):
    engine = EpisodicMemoryEngine(data_dir=str(tmp_path / "episodes"))
    # 手动添加一段检修案卷
    engine.episodes.append(IncidentEpisode(
        id="EP-001",
        title="冷通道冷凝水漏液告警",
        symptoms="静电地板下漏水传感器发出警报，A02机柜局部温升",
        root_cause="空调排水管保温层老化破裂导致冷凝水溢出",
        resolution="关闭对应支路排水阀，切换备用空调CRAC-02，清理地板下积水",
        tags=["HVAC", "WaterLeak"]
    ))

    # 测试检索
    results = engine.recall_similar_episodes("机房地面漏水与空调冷凝水", top_k=1)
    assert len(results) >= 1
    assert results[0]["episode_id"] == "EP-001"
    assert "空调排水管" in results[0]["root_cause"]


def test_few_shot_formatting(tmp_path):
    engine = EpisodicMemoryEngine(data_dir=str(tmp_path / "episodes"))
    engine.episodes.append(IncidentEpisode(
        id="EP-002",
        title="UPS输出纹波超标",
        symptoms="UPS-B02 逆变器输出电压纹波达到 8%",
        root_cause="滤波电容电解液干涸",
        resolution="倒换至维修旁路，更换电容包",
        tags=["Power", "UPS"]
    ))

    formatted = engine.format_as_few_shot("UPS逆变器纹波告警", top_k=1)
    assert "专家情景记忆检索" in formatted
    assert "UPS-B02" in formatted
    assert "滤波电容电解液干涸" in formatted
