from multi_agents.agents import ChiefEditorAgent

chief_editor = ChiefEditorAgent({
  "query": "生成式 AI 在企业的落地现状与瓶颈",
  "max_sections": 3,
  "max_plan_revisions": 3,
  "follow_guidelines": False,
  "model": "deepseek-chat",
  "guidelines": [
    "报告必须使用 APA 引用格式",
    "每个小节必须包含可点击的来源链接；没有来源时应删除该小节或并入上一节",
    "报告必须使用简体中文撰写"
  ],
  "verbose": False
})
graph = chief_editor.init_research_team()
graph = graph.compile()
