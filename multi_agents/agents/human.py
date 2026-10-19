class HumanAgent:
    def __init__(self, headers=None):
        self.headers = headers or {}

    async def review_plan(self, research_state: dict):
        task = research_state.get("task")
        layout = research_state.get("sections")

        user_feedback = None

        if task.get("include_human_feedback"):
            user_feedback = input(
                f"Any feedback on this plan? {layout}? If not, please reply with 'no'.\n>> "
            )

        if user_feedback and "no" in user_feedback.strip().lower():
            user_feedback = None

        plan_revision_count = research_state.get("plan_revision_count", 0)
        if user_feedback:
            plan_revision_count += 1

        print(f"User feedback before return: {user_feedback}")

        return {
            "human_feedback": user_feedback,
            "plan_revision_count": plan_revision_count,
        }
